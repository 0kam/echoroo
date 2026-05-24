"""Smoke coverage for spec/009 PR 5 admin system-settings BFF adapters.

PR 5 moves the four superuser-only admin surfaces onto the cookie +
CSRF ``/web-api/v1/admin/*`` mount. This module covers the
system-settings subset (get + update).

Tests assert delegation, OpenAPI declaration, gate-helper invocation
with the canonical ``Action`` constant, and API-key cross-rejection on
both paths.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import admin as legacy_admin
from echoroo.api.web_v1 import _admin_settings as bff_admin_settings
from echoroo.core.actions import (
    ADMIN_SETTINGS_GET_ACTION,
    ADMIN_SETTINGS_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_active_superuser
from echoroo.schemas.admin import SystemSettingResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _capturing_gate(captured: dict[str, object]) -> Any:
    def fake(**kwargs: object) -> None:
        captured.update(kwargs)

    return fake


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_admin_settings.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_active_superuser] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_get_system_settings_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_settings(**kwargs: object) -> dict[str, SystemSettingResponse]:
        captured.update(kwargs)
        now = datetime(2026, 5, 24, tzinfo=UTC)
        return {
            "session_timeout_minutes": SystemSettingResponse(
                key="session_timeout_minutes",
                value=60,
                value_type="number",
                updated_at=now,
            )
        }

    monkeypatch.setattr(legacy_admin, "get_system_settings", fake_get_settings)
    monkeypatch.setattr(
        bff_admin_settings,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/admin/settings")

    assert response.status_code == 200, response.text
    assert captured["current_user"] is user
    assert gate_captured["action"] is ADMIN_SETTINGS_GET_ACTION
    assert gate_captured["current_user"] is user


@pytest.mark.asyncio
async def test_update_system_settings_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_settings(**kwargs: object) -> dict[str, str]:
        captured.update(kwargs)
        return {"message": "ok"}

    monkeypatch.setattr(legacy_admin, "update_system_settings", fake_update_settings)
    monkeypatch.setattr(
        bff_admin_settings,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            "/web-api/v1/admin/settings",
            json={"session_timeout_minutes": 120},
        )

    assert response.status_code == 200, response.text
    payload = captured["request"]
    assert isinstance(payload, legacy_admin.SystemSettingsUpdateRequest)
    assert payload.session_timeout_minutes == 120
    assert captured["current_user"] is user
    assert gate_captured["action"] is ADMIN_SETTINGS_UPDATE_ACTION
    assert gate_captured["current_user"] is user


def test_admin_settings_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4(), is_superuser=True))
    paths = app.openapi()["paths"]

    assert "get" in paths["/web-api/v1/admin/settings"]
    assert "patch" in paths["/web-api/v1/admin/settings"]


@pytest.mark.asyncio
async def test_admin_settings_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/admin/settings",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        "/web-api/v1/admin/settings",
        body={"session_timeout_minutes": 120},
    )
