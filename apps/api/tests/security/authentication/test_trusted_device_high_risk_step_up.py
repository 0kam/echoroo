"""US5 guardrails: trusted-device sessions do not satisfy high-risk step-up."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from echoroo.middleware.auth_router import Principal
from echoroo.middleware.two_factor_enforcement import TwoFactorEnforcementMiddleware


@dataclass
class _TrustedDeviceSessionUser:
    id: UUID
    two_factor_enabled: bool = True
    deleted_at: datetime | None = None
    two_factor_reset_cooldown_until: datetime | None = None


class _TrustedDevicePrincipalMiddleware(BaseHTTPMiddleware):
    """Stand in for a completed trusted-device login session."""

    def __init__(self, app: ASGIApp, *, user: _TrustedDeviceSessionUser) -> None:
        super().__init__(app)
        self.user = user

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.principal = Principal.for_session(
            user_id=self.user.id,
            security_stamp="s" * 64,
        )
        request.state.trusted_device_used = True
        return await call_next(request)


def _build_trusted_device_client() -> TestClient:
    user = _TrustedDeviceSessionUser(id=uuid.uuid4())
    app = FastAPI()

    @app.post("/web-api/v1/api-keys")
    async def issue_api_key() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/web-api/v1/projects/{project_id}/transfer-ownership")
    async def transfer_ownership(project_id: str) -> dict[str, str]:  # noqa: ARG001
        return {"status": "transferred"}

    @app.delete("/web-api/v1/projects/{project_id}")
    async def delete_project(project_id: str) -> dict[str, str]:  # noqa: ARG001
        return {"status": "deleted"}

    @app.get("/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export")
    async def export_dataset(
        project_id: str,  # noqa: ARG001
        dataset_id: str,  # noqa: ARG001
    ) -> dict[str, str]:
        return {"status": "exported"}

    async def _resolver(user_id: UUID) -> _TrustedDeviceSessionUser | None:
        if user_id == user.id:
            return user
        return None

    audit_calls: list[dict[str, Any]] = []

    async def _audit_writer(**kwargs: Any) -> None:
        audit_calls.append(kwargs)

    app.add_middleware(
        TwoFactorEnforcementMiddleware,
        user_resolver=_resolver,  # type: ignore[arg-type]
        audit_writer=_audit_writer,
    )
    app.add_middleware(_TrustedDevicePrincipalMiddleware, user=user)
    app.state.audit_calls = audit_calls
    return TestClient(app)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/web-api/v1/api-keys"),
        ("POST", "/web-api/v1/projects/project-1/transfer-ownership"),
        ("DELETE", "/web-api/v1/projects/project-1"),
        ("GET", "/web-api/v1/projects/project-1/datasets/dataset-1/export"),
    ],
    ids=[
        "api_key_issuance",
        "ownership_transfer",
        "project_delete",
        "dataset_export",
    ],
)
def test_trusted_device_session_without_recent_step_up_blocked_on_high_risk_paths(
    method: str,
    path: str,
) -> None:
    response = _build_trusted_device_client().request(
        method,
        path,
        cookies={"echoroo_trusted_device": "trusted-device-cookie"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Recent step-up required",
        "error_code": "recent_step_up_required",
    }


def test_trusted_device_session_is_not_blocked_on_low_risk_get() -> None:
    user = _TrustedDeviceSessionUser(
        id=uuid.uuid4(),
        two_factor_reset_cooldown_until=datetime.now(UTC) + timedelta(minutes=10),
    )
    app = FastAPI()

    @app.get("/web-api/v1/projects")
    async def list_projects() -> dict[str, bool]:
        return {"ok": True}

    async def _resolver(user_id: UUID) -> _TrustedDeviceSessionUser | None:
        if user_id == user.id:
            return user
        return None

    app.add_middleware(
        TwoFactorEnforcementMiddleware,
        user_resolver=_resolver,  # type: ignore[arg-type]
    )
    app.add_middleware(_TrustedDevicePrincipalMiddleware, user=user)

    response = TestClient(app).get(
        "/web-api/v1/projects",
        cookies={"echoroo_trusted_device": "trusted-device-cookie"},
    )

    assert response.status_code == 200
