"""TDD coverage for the 72-hour 2FA-reset cooldown gate (FR-073).

When an admin resets a user's 2FA, the user's
``two_factor_reset_cooldown_until`` is bumped 72 hours into the future.
During that window the :class:`TwoFactorEnforcementMiddleware` MUST
return HTTP 423 (with a ``Retry-After`` header) for every state-changing
endpoint listed in :data:`COOLDOWN_RESTRICTED_PATTERNS` — the user can
still browse read-only routes but cannot exfiltrate data, accept
invitations, or escalate privilege.

The contract surface this suite locks in:

* ``POST /web-api/v1/projects``                       (project create)
* ``POST /web-api/v1/_test/ping`` (state-changing test surface)        — adapted
* ``POST /web-api/v1/invitations/{token}/accept``     (invitation accept)
* ``POST | DELETE /web-api/v1/api-keys[/...]``        (API key ops)
* ``GET  /web-api/v1/.../export(...)``                (data export)
* ``GET  /web-api/v1/.../download(...)``              (download)

After the cooldown expires (``two_factor_reset_cooldown_until`` is in
the past), the same calls return their normal status code (in our test
harness — 200 from the stub handler), proving the gate is time-bounded
rather than permanent.

The test suite exclusively uses the lightweight in-process FastAPI
fixture from ``test_two_factor_enforcement.py`` to keep TDD coverage
fast — the *real-chain* end-to-end variant lives in
``tests/integration/middleware/test_two_factor_enforcement_real_chain.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from echoroo.middleware.auth_router import Principal
from echoroo.middleware.two_factor_enforcement import TwoFactorEnforcementMiddleware


@dataclass
class _User:
    id: UUID
    two_factor_enabled: bool
    deleted_at: datetime | None = None
    two_factor_reset_cooldown_until: datetime | None = None


class _PrincipalStateMiddleware(BaseHTTPMiddleware):
    """Stand-in for :class:`AuthRouterMiddleware` in fast unit tests."""

    def __init__(self, app: ASGIApp, *, user: _User | None) -> None:
        super().__init__(app)
        self.user = user

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if self.user is not None:
            request.state.principal = Principal.for_session(
                user_id=self.user.id,
                security_stamp="s" * 64,
            )
        else:
            request.state.principal = None
        return await call_next(request)


def _build_client(user: _User) -> TestClient:
    app = FastAPI()

    # Project create / delete (POST + DELETE protected by the cooldown
    # pattern, GET is read-only).
    @app.api_route("/web-api/v1/projects", methods=["GET", "POST", "DELETE"])
    async def projects() -> dict[str, bool]:
        return {"ok": True}

    # Direct project DELETE — separate from collection-level DELETE.
    @app.delete("/web-api/v1/projects/{project_id}")
    async def delete_project(project_id: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    # Invitation accept (POST).
    @app.post("/web-api/v1/invitations/{token}/accept")
    async def accept_invitation(token: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    # API key collection + per-id (POST/DELETE both protected).
    @app.api_route("/web-api/v1/api-keys", methods=["GET", "POST", "DELETE"])
    async def api_keys_collection() -> dict[str, bool]:
        return {"ok": True}

    @app.api_route("/web-api/v1/api-keys/{key_id}", methods=["GET", "DELETE"])
    async def api_keys_item(key_id: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    # Download / export endpoints (GET pattern matched by /.*download.*$
    # and /.*export.*$).
    @app.get("/web-api/v1/datasets/{dataset_id}/export.csv")
    async def export_dataset(dataset_id: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    @app.get("/web-api/v1/recordings/{recording_id}/download")
    async def download_recording(recording_id: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    # State-changing test surface — kept symmetric with the existing
    # T155 real-chain harness.
    @app.api_route("/web-api/v1/_test/ping", methods=["GET", "POST"])
    async def test_ping() -> dict[str, bool]:
        return {"ok": True}

    captured_user = user

    async def _resolver(user_id: UUID) -> _User | None:
        if captured_user is not None and captured_user.id == user_id:
            return captured_user  # type: ignore[return-value]
        return None

    async def _audit_writer(**_kwargs: object) -> None:
        return None

    app.add_middleware(
        TwoFactorEnforcementMiddleware,
        user_resolver=_resolver,
        audit_writer=_audit_writer,
    )
    app.add_middleware(_PrincipalStateMiddleware, user=user)
    return TestClient(app)


def _cooldown_user(*, expires_in: timedelta = timedelta(hours=12)) -> _User:
    return _User(
        id=uuid.uuid4(),
        two_factor_enabled=True,
        two_factor_reset_cooldown_until=datetime.now(UTC) + expires_in,
    )


def _expired_cooldown_user() -> _User:
    return _User(
        id=uuid.uuid4(),
        two_factor_enabled=True,
        # 1 second in the past — the gate must release immediately.
        two_factor_reset_cooldown_until=datetime.now(UTC) - timedelta(seconds=1),
    )


# ---------------------------------------------------------------------------
# During the 72-hour cooldown, every protected endpoint returns 423.
# ---------------------------------------------------------------------------


def test_cooldown_blocks_post_projects_with_423() -> None:
    response = _build_client(_cooldown_user()).post("/web-api/v1/projects")

    assert response.status_code == 423
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["detail"] == "2FA reset cooldown active"


def test_cooldown_blocks_invitation_accept_with_423() -> None:
    response = _build_client(_cooldown_user()).post(
        "/web-api/v1/invitations/some-token/accept"
    )

    assert response.status_code == 423


def test_cooldown_blocks_api_key_collection_post_with_423() -> None:
    response = _build_client(_cooldown_user()).post("/web-api/v1/api-keys")

    assert response.status_code == 423


def test_cooldown_blocks_api_key_item_delete_with_423() -> None:
    response = _build_client(_cooldown_user()).delete(
        f"/web-api/v1/api-keys/{uuid.uuid4()}"
    )

    assert response.status_code == 423


def test_cooldown_blocks_dataset_export_with_423() -> None:
    response = _build_client(_cooldown_user()).get(
        f"/web-api/v1/datasets/{uuid.uuid4()}/export.csv"
    )

    assert response.status_code == 423


def test_cooldown_blocks_recording_download_with_423() -> None:
    response = _build_client(_cooldown_user()).get(
        f"/web-api/v1/recordings/{uuid.uuid4()}/download"
    )

    assert response.status_code == 423


def test_cooldown_blocks_project_delete_with_423() -> None:
    response = _build_client(_cooldown_user()).delete(
        f"/web-api/v1/projects/{uuid.uuid4()}"
    )

    assert response.status_code == 423


# ---------------------------------------------------------------------------
# Read-only endpoints stay reachable during cooldown — the user can still
# observe their data; we just block side-effecting calls.
# ---------------------------------------------------------------------------


def test_cooldown_does_not_block_read_only_get_projects() -> None:
    response = _build_client(_cooldown_user()).get("/web-api/v1/projects")

    assert response.status_code == 200


def test_cooldown_does_not_block_get_test_ping() -> None:
    """Symmetric with the T155 real-chain test: GET stays reachable."""
    response = _build_client(_cooldown_user()).get("/web-api/v1/_test/ping")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# After cooldown expires, the same calls succeed (return 200 from stubs).
# ---------------------------------------------------------------------------


def test_post_projects_succeeds_after_cooldown_expires() -> None:
    response = _build_client(_expired_cooldown_user()).post("/web-api/v1/projects")

    assert response.status_code == 200


def test_invitation_accept_succeeds_after_cooldown_expires() -> None:
    response = _build_client(_expired_cooldown_user()).post(
        "/web-api/v1/invitations/some-token/accept"
    )

    assert response.status_code == 200


def test_api_key_create_succeeds_after_cooldown_expires() -> None:
    response = _build_client(_expired_cooldown_user()).post("/web-api/v1/api-keys")

    assert response.status_code == 200


def test_dataset_export_succeeds_after_cooldown_expires() -> None:
    response = _build_client(_expired_cooldown_user()).get(
        f"/web-api/v1/datasets/{uuid.uuid4()}/export.csv"
    )

    assert response.status_code == 200


def test_recording_download_succeeds_after_cooldown_expires() -> None:
    response = _build_client(_expired_cooldown_user()).get(
        f"/web-api/v1/recordings/{uuid.uuid4()}/download"
    )

    assert response.status_code == 200
