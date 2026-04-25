"""Integration coverage for 2FA enforcement middleware (T155)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
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


def _build_client(user: _User | None = None) -> TestClient:
    app = FastAPI()

    @app.api_route("/api/v1/projects", methods=["GET", "POST", "DELETE"])
    async def projects() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/invitations/{token}/accept")
    async def accept_invitation(token: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    @app.api_route("/api/v1/api-keys", methods=["GET", "POST", "DELETE"])
    async def api_keys() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/reports/export")
    async def export_report() -> dict[str, bool]:
        return {"ok": True}

    @app.api_route("/api/v1/projects/{project_id}/members", methods=["GET", "POST", "DELETE"])
    async def members(project_id: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    @app.post("/api/v1/projects/{project_id}/join")
    async def join_project(project_id: str) -> dict[str, bool]:  # noqa: ARG001
        return {"ok": True}

    @app.get("/web-api/v1/auth/2fa/setup/totp")
    async def setup_totp() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    captured_user = user

    async def _resolver(user_id: UUID) -> _User | None:
        if captured_user is not None and captured_user.id == user_id:
            return captured_user  # type: ignore[return-value]
        return None

    async def _audit_writer(**_kwargs: Any) -> None:
        # Silenced in unit tests — the integration test exercises the
        # real audit writer end-to-end against Postgres.
        return None

    app.add_middleware(
        TwoFactorEnforcementMiddleware,
        user_resolver=_resolver,
        audit_writer=_audit_writer,
    )
    app.add_middleware(_PrincipalStateMiddleware, user=user)
    return TestClient(app)


def _enabled_user() -> _User:
    return _User(id=uuid.uuid4(), two_factor_enabled=True)


def _unenrolled_user() -> _User:
    return _User(id=uuid.uuid4(), two_factor_enabled=False)


def _cooldown_user() -> _User:
    return _User(
        id=uuid.uuid4(),
        two_factor_enabled=True,
        two_factor_reset_cooldown_until=datetime.now(UTC) + timedelta(hours=1),
    )


def test_unauthenticated_request_passes_through() -> None:
    response = _build_client().get("/api/v1/projects")

    assert response.status_code == 200


def test_user_without_2fa_blocked_on_protected_endpoint() -> None:
    response = _build_client(_unenrolled_user()).get("/api/v1/projects")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "2FA enrollment required",
        "next_action": "/web-api/v1/auth/2fa/setup/totp",
    }


def test_user_without_2fa_can_access_2fa_setup() -> None:
    response = _build_client(_unenrolled_user()).get(
        "/web-api/v1/auth/2fa/setup/totp"
    )

    assert response.status_code == 200


def test_user_with_2fa_can_access_protected_endpoint() -> None:
    response = _build_client(_enabled_user()).get("/api/v1/projects")

    assert response.status_code == 200


def test_user_in_2fa_cooldown_blocked_on_invite_accept() -> None:
    response = _build_client(_cooldown_user()).post("/api/v1/invitations/token/accept")

    assert response.status_code == 423
    assert int(response.headers["Retry-After"]) > 0
    assert response.json()["detail"] == "2FA reset cooldown active"


def test_user_in_2fa_cooldown_blocked_on_api_key_create() -> None:
    response = _build_client(_cooldown_user()).post("/api/v1/api-keys")

    assert response.status_code == 423


def test_user_in_2fa_cooldown_blocked_on_export() -> None:
    response = _build_client(_cooldown_user()).get("/api/v1/reports/export")

    assert response.status_code == 423


def test_user_in_2fa_cooldown_blocked_on_project_create() -> None:
    response = _build_client(_cooldown_user()).post("/api/v1/projects")

    assert response.status_code == 423


def test_user_in_2fa_cooldown_blocked_on_member_management() -> None:
    response = _build_client(_cooldown_user()).post("/api/v1/projects/project-1/members")

    assert response.status_code == 423


def test_user_in_2fa_cooldown_can_view_projects() -> None:
    response = _build_client(_cooldown_user()).get("/api/v1/projects")

    assert response.status_code == 200


def test_2fa_disabled_after_cooldown_expires() -> None:
    user = _User(
        id=uuid.uuid4(),
        two_factor_enabled=True,
        two_factor_reset_cooldown_until=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = _build_client(user).post("/api/v1/api-keys")

    assert response.status_code == 200


def test_health_endpoint_bypassed() -> None:
    response = _build_client(_unenrolled_user()).get("/health")

    assert response.status_code == 200


def test_soft_deleted_user_is_failed_closed() -> None:
    user = _User(
        id=uuid.uuid4(),
        two_factor_enabled=True,
        deleted_at=datetime.now(UTC),
    )

    response = _build_client(user).get("/api/v1/projects")

    assert response.status_code == 403
    assert response.json()["detail"] == "2FA enrollment required"
