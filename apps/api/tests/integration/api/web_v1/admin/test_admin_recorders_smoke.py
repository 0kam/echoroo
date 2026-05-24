"""Smoke coverage for spec/009 PR 5 admin recorder BFF adapters.

PR 5 moves the four superuser-only admin surfaces onto the cookie +
CSRF ``/web-api/v1/admin/*`` mount. This module covers the
recorder-catalog subset (list + get + create + update + delete).

Tests assert delegation, OpenAPI declaration, gate-helper invocation
with the canonical ``Action`` constant for each endpoint, and API-key
cross-rejection on all five paths.
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
from echoroo.api.web_v1 import _admin_recorders as bff_admin_recorders
from echoroo.core.actions import (
    ADMIN_RECORDER_CREATE_ACTION,
    ADMIN_RECORDER_DELETE_ACTION,
    ADMIN_RECORDER_GET_ACTION,
    ADMIN_RECORDER_LIST_ACTION,
    ADMIN_RECORDER_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_active_superuser
from echoroo.schemas.recorder import RecorderListResponse, RecorderResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_recorder_response(*, recorder_id: str = "am120") -> RecorderResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return RecorderResponse(
        id=recorder_id,
        manufacturer="Open Acoustic Devices",
        recorder_name="AudioMoth",
        version="1.2.0",
        created_at=now,
        updated_at=now,
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _capturing_gate(captured: dict[str, object]) -> Any:
    def fake(**kwargs: object) -> None:
        captured.update(kwargs)

    return fake


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_admin_recorders.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_active_superuser] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_list_recorders_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list_recorders(**kwargs: object) -> RecorderListResponse:
        captured.update(kwargs)
        return RecorderListResponse(items=[], total=0, page=1, limit=20)

    monkeypatch.setattr(legacy_admin, "list_recorders", fake_list_recorders)
    monkeypatch.setattr(
        bff_admin_recorders,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            "/web-api/v1/admin/recorders?page=3&limit=25"
        )

    assert response.status_code == 200, response.text
    assert captured["current_user"] is user
    assert captured["page"] == 3
    assert captured["limit"] == 25
    assert gate_captured["action"] is ADMIN_RECORDER_LIST_ACTION


@pytest.mark.asyncio
async def test_create_recorder_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create_recorder(**kwargs: object) -> RecorderResponse:
        captured.update(kwargs)
        return _fake_recorder_response()

    monkeypatch.setattr(legacy_admin, "create_recorder", fake_create_recorder)
    monkeypatch.setattr(
        bff_admin_recorders,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/web-api/v1/admin/recorders",
            json={
                "id": "am120",
                "manufacturer": "Open Acoustic Devices",
                "recorder_name": "AudioMoth",
                "version": "1.2.0",
            },
        )

    assert response.status_code == 201, response.text
    payload = captured["request"]
    assert isinstance(payload, legacy_admin.RecorderCreate)
    assert payload.id == "am120"
    assert gate_captured["action"] is ADMIN_RECORDER_CREATE_ACTION


@pytest.mark.asyncio
async def test_get_recorder_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_recorder(**kwargs: object) -> RecorderResponse:
        captured.update(kwargs)
        return _fake_recorder_response(recorder_id="am120")

    monkeypatch.setattr(legacy_admin, "get_recorder", fake_get_recorder)
    monkeypatch.setattr(
        bff_admin_recorders,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/admin/recorders/am120")

    assert response.status_code == 200, response.text
    assert captured["recorder_id"] == "am120"
    assert gate_captured["action"] is ADMIN_RECORDER_GET_ACTION


@pytest.mark.asyncio
async def test_update_recorder_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_recorder(**kwargs: object) -> RecorderResponse:
        captured.update(kwargs)
        return _fake_recorder_response(recorder_id="am120")

    monkeypatch.setattr(legacy_admin, "update_recorder", fake_update_recorder)
    monkeypatch.setattr(
        bff_admin_recorders,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            "/web-api/v1/admin/recorders/am120",
            json={"version": "1.2.1"},
        )

    assert response.status_code == 200, response.text
    assert captured["recorder_id"] == "am120"
    payload = captured["request"]
    assert isinstance(payload, legacy_admin.RecorderUpdate)
    assert payload.version == "1.2.1"
    assert gate_captured["action"] is ADMIN_RECORDER_UPDATE_ACTION


@pytest.mark.asyncio
async def test_delete_recorder_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_recorder(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_admin, "delete_recorder", fake_delete_recorder)
    monkeypatch.setattr(
        bff_admin_recorders,
        "_gate_admin_platform_action",
        _capturing_gate(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete("/web-api/v1/admin/recorders/am120")

    assert response.status_code == 204, response.text
    assert captured["recorder_id"] == "am120"
    assert gate_captured["action"] is ADMIN_RECORDER_DELETE_ACTION


def test_admin_recorders_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4(), is_superuser=True))
    paths = app.openapi()["paths"]

    list_path = "/web-api/v1/admin/recorders"
    assert "get" in paths[list_path]
    assert "post" in paths[list_path]

    detail_path = "/web-api/v1/admin/recorders/{recorder_id}"
    assert "get" in paths[detail_path]
    assert "patch" in paths[detail_path]
    assert "delete" in paths[detail_path]


@pytest.mark.asyncio
async def test_admin_recorders_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/admin/recorders",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        "/web-api/v1/admin/recorders",
        body={"id": "x", "manufacturer": "y", "recorder_name": "z"},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/admin/recorders/am120",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        "/web-api/v1/admin/recorders/am120",
        body={"version": "9.9.9"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        "/web-api/v1/admin/recorders/am120",
    )
