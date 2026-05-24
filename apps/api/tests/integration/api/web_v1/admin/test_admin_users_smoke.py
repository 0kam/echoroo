"""Smoke coverage for spec/009 PR 5 admin user BFF adapters.

PR 5 moves the four superuser-only admin surfaces (users / settings /
recorders / licenses) onto the cookie + CSRF ``/web-api/v1/admin/*``
mount so cookie-session admins stop 401-ing after spec/006 restricted
the legacy ``/api/v1/*`` namespace to M2M API-key callers. This module
covers the user-management subset (list + update).

Each test mirrors the PR 4 ``test_recorders_smoke`` pattern: build a
minimal FastAPI app with the BFF router mounted, monkey-patch the
legacy handler + the BFF-side ``_gate_admin_platform_action`` helper
with capture-style fakes, and assert the BFF (1) routes the call to
the legacy handler with the right kwargs, (2) preserves the legacy
response shape, (3) declares each path in the OpenAPI schema, and
(4) invokes the gate helper with the canonical ``Action`` constant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import admin as legacy_admin
from echoroo.api.web_v1 import _admin_users as bff_admin_users
from echoroo.core.actions import (
    ADMIN_USERS_LIST_ACTION,
    ADMIN_USERS_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_active_superuser
from echoroo.schemas.admin import AdminUserListResponse
from echoroo.schemas.auth import UserResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_user_response(*, user_id: UUID) -> UserResponse:
    from datetime import UTC, datetime

    now = datetime(2026, 5, 24, tzinfo=UTC)
    return UserResponse(
        id=user_id,
        email="fake@example.com",
        display_name="Fake User",
        created_at=now,
        last_login_at=None,
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _capturing_gate(captured: dict[str, object]) -> Any:
    def fake(**kwargs: object) -> None:
        captured.update(kwargs)

    return fake


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_admin_users.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_active_superuser] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_list_users_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list_users(**kwargs: object) -> AdminUserListResponse:
        captured.update(kwargs)
        return AdminUserListResponse(items=[], total=0, page=1, limit=20)

    monkeypatch.setattr(legacy_admin, "list_users", fake_list_users)
    monkeypatch.setattr(
        bff_admin_users,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/web-api/v1/admin/users?page=2&limit=50&search=ab&is_active=true"
        )

    assert response.status_code == 200, response.text
    assert captured["current_user"] is user
    assert captured["page"] == 2
    assert captured["limit"] == 50
    assert captured["search"] == "ab"
    assert captured["is_active"] is True
    assert gate_captured["action"] is ADMIN_USERS_LIST_ACTION
    assert gate_captured["current_user"] is user


@pytest.mark.asyncio
async def test_update_user_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    target_id = uuid4()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_user(**kwargs: object) -> UserResponse:
        captured.update(kwargs)
        return _fake_user_response(user_id=target_id)

    monkeypatch.setattr(legacy_admin, "update_user", fake_update_user)
    monkeypatch.setattr(
        bff_admin_users,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/admin/users/{target_id}",
            json={"is_active": False},
        )

    assert response.status_code == 200, response.text
    assert captured["user_id"] == target_id
    payload = captured["request"]
    assert isinstance(payload, legacy_admin.AdminUserUpdateRequest)
    assert payload.is_active is False
    assert captured["current_user"] is user
    assert gate_captured["action"] is ADMIN_USERS_UPDATE_ACTION
    assert gate_captured["current_user"] is user


def test_admin_users_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4(), is_superuser=True))
    paths = app.openapi()["paths"]

    assert "get" in paths["/web-api/v1/admin/users"]
    assert "patch" in paths["/web-api/v1/admin/users/{user_id}"]


@pytest.mark.asyncio
async def test_admin_users_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    target_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/admin/users",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/admin/users/{target_id}",
        body={"is_active": False},
    )
