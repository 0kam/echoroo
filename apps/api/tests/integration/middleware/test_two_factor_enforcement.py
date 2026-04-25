"""Integration coverage for 2FA enforcement middleware (T155)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from echoroo.middleware.two_factor_enforcement import TwoFactorEnforcementMiddleware


@dataclass
class _User:
    two_factor_enabled: bool
    two_factor_reset_cooldown_until: datetime | None = None


class _UserStateMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, user: _User) -> None:
        super().__init__(app)
        self.user = user

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.user = self.user
        return await call_next(request)


def _build_client(user: _User | None = None) -> TestClient:
    app = FastAPI()

    @app.api_route("/api/v1/projects", methods=["GET", "POST", "DELETE"])
    async def projects() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/invitations/{token}/accept")
    async def accept_invitation(token: str) -> dict[str, bool]:
        return {"ok": True}

    @app.api_route("/api/v1/api-keys", methods=["GET", "POST", "DELETE"])
    async def api_keys() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/reports/export")
    async def export_report() -> dict[str, bool]:
        return {"ok": True}

    @app.api_route("/api/v1/projects/{project_id}/members", methods=["GET", "POST", "DELETE"])
    async def members(project_id: str) -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/v1/projects/{project_id}/join")
    async def join_project(project_id: str) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/web-api/v1/auth/2fa/setup/totp")
    async def setup_totp() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(TwoFactorEnforcementMiddleware)
    if user is not None:
        app.add_middleware(_UserStateMiddleware, user=user)
    return TestClient(app)


def _cooldown_user() -> _User:
    return _User(
        two_factor_enabled=True,
        two_factor_reset_cooldown_until=datetime.now(UTC) + timedelta(hours=1),
    )


def test_unauthenticated_request_passes_through() -> None:
    response = _build_client().get("/api/v1/projects")

    assert response.status_code == 200


def test_user_without_2fa_blocked_on_protected_endpoint() -> None:
    response = _build_client(_User(two_factor_enabled=False)).get("/api/v1/projects")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "2FA enrollment required",
        "next_action": "/2fa/setup/totp",
    }


def test_user_without_2fa_can_access_2fa_setup() -> None:
    response = _build_client(_User(two_factor_enabled=False)).get(
        "/web-api/v1/auth/2fa/setup/totp"
    )

    assert response.status_code == 200


def test_user_with_2fa_can_access_protected_endpoint() -> None:
    response = _build_client(_User(two_factor_enabled=True)).get("/api/v1/projects")

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
        two_factor_enabled=True,
        two_factor_reset_cooldown_until=datetime.now(UTC) - timedelta(seconds=1),
    )

    response = _build_client(user).post("/api/v1/api-keys")

    assert response.status_code == 200


def test_health_endpoint_bypassed() -> None:
    response = _build_client(_User(two_factor_enabled=False)).get("/health")

    assert response.status_code == 200
