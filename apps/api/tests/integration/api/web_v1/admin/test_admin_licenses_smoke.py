"""Smoke coverage for spec/009 PR 5 admin license BFF adapters.

PR 5 moves the four superuser-only admin surfaces onto the cookie +
CSRF ``/web-api/v1/admin/*`` mount. This module covers the
license-catalog subset (list + get + create + update + delete).

License BFF endpoints share the legacy admin module's
``_gate_admin_platform_action`` helper (re-exported through the sibling
``_admin_recorders`` module). The license module imports it from there
to avoid a second copy of the same helper. Tests assert delegation,
OpenAPI declaration, gate-helper invocation with the canonical
``Action`` constant, and API-key cross-rejection on all five paths.
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
from echoroo.api.web_v1 import _admin_licenses as bff_admin_licenses
from echoroo.api.web_v1 import _admin_recorders as bff_admin_recorders
from echoroo.core.actions import (
    ADMIN_LICENSE_CREATE_ACTION,
    ADMIN_LICENSE_DELETE_ACTION,
    ADMIN_LICENSE_GET_ACTION,
    ADMIN_LICENSE_LIST_ACTION,
    ADMIN_LICENSE_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_active_superuser
from echoroo.schemas.license import LicenseListResponse, LicenseResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_license_response(*, license_id: str = "CC-BY-4.0") -> LicenseResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return LicenseResponse(
        id=license_id,
        name="Creative Commons Attribution 4.0",
        short_name="CC-BY-4.0",
        url="https://creativecommons.org/licenses/by/4.0/",
        description=None,
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
    app.include_router(bff_admin_licenses.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_active_superuser] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


def _patch_gate(monkeypatch: pytest.MonkeyPatch, captured: dict[str, object]) -> None:
    """Patch BOTH the canonical helper in ``_admin_recorders`` AND the
    re-imported binding in ``_admin_licenses``.

    ``_admin_licenses`` does ``from ._admin_recorders import
    _gate_admin_platform_action`` at import time, which binds the
    function object on the licenses module's namespace at module load.
    Monkey-patching only the recorders module would leave the licenses
    module's binding pointing at the original gate. Patching both keeps
    the test honest about WHICH helper the BFF endpoints invoke.
    """
    fake = _capturing_gate(captured)
    monkeypatch.setattr(
        bff_admin_recorders, "_gate_admin_platform_action", fake
    )
    monkeypatch.setattr(
        bff_admin_licenses, "_gate_admin_platform_action", fake
    )


@pytest.mark.asyncio
async def test_list_licenses_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list_licenses(**kwargs: object) -> LicenseListResponse:
        captured.update(kwargs)
        return LicenseListResponse(items=[])

    monkeypatch.setattr(legacy_admin, "list_licenses", fake_list_licenses)
    _patch_gate(monkeypatch, gate_captured)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/admin/licenses")

    assert response.status_code == 200, response.text
    assert captured["current_user"] is user
    assert gate_captured["action"] is ADMIN_LICENSE_LIST_ACTION


@pytest.mark.asyncio
async def test_create_license_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create_license(**kwargs: object) -> LicenseResponse:
        captured.update(kwargs)
        return _fake_license_response()

    monkeypatch.setattr(legacy_admin, "create_license", fake_create_license)
    _patch_gate(monkeypatch, gate_captured)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/web-api/v1/admin/licenses",
            json={
                "id": "CC-BY-4.0",
                "name": "Creative Commons Attribution 4.0",
                "short_name": "CC-BY-4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
            },
        )

    assert response.status_code == 201, response.text
    payload = captured["request"]
    assert isinstance(payload, legacy_admin.LicenseCreate)
    assert payload.id == "CC-BY-4.0"
    assert gate_captured["action"] is ADMIN_LICENSE_CREATE_ACTION


@pytest.mark.asyncio
async def test_get_license_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_license(**kwargs: object) -> LicenseResponse:
        captured.update(kwargs)
        return _fake_license_response(license_id="CC-BY-4.0")

    monkeypatch.setattr(legacy_admin, "get_license", fake_get_license)
    _patch_gate(monkeypatch, gate_captured)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/admin/licenses/CC-BY-4.0")

    assert response.status_code == 200, response.text
    assert captured["license_id"] == "CC-BY-4.0"
    assert gate_captured["action"] is ADMIN_LICENSE_GET_ACTION


@pytest.mark.asyncio
async def test_update_license_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_license(**kwargs: object) -> LicenseResponse:
        captured.update(kwargs)
        return _fake_license_response(license_id="CC-BY-4.0")

    monkeypatch.setattr(legacy_admin, "update_license", fake_update_license)
    _patch_gate(monkeypatch, gate_captured)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            "/web-api/v1/admin/licenses/CC-BY-4.0",
            json={"description": "Updated description"},
        )

    assert response.status_code == 200, response.text
    assert captured["license_id"] == "CC-BY-4.0"
    payload = captured["request"]
    assert isinstance(payload, legacy_admin.LicenseUpdate)
    assert payload.description == "Updated description"
    assert gate_captured["action"] is ADMIN_LICENSE_UPDATE_ACTION


@pytest.mark.asyncio
async def test_delete_license_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4(), is_superuser=True)
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_license(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_admin, "delete_license", fake_delete_license)
    _patch_gate(monkeypatch, gate_captured)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete("/web-api/v1/admin/licenses/CC-BY-4.0")

    assert response.status_code == 204, response.text
    assert captured["license_id"] == "CC-BY-4.0"
    assert gate_captured["action"] is ADMIN_LICENSE_DELETE_ACTION


def test_admin_licenses_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4(), is_superuser=True))
    paths = app.openapi()["paths"]

    list_path = "/web-api/v1/admin/licenses"
    assert "get" in paths[list_path]
    assert "post" in paths[list_path]

    detail_path = "/web-api/v1/admin/licenses/{license_id}"
    assert "get" in paths[detail_path]
    assert "patch" in paths[detail_path]
    assert "delete" in paths[detail_path]


@pytest.mark.asyncio
async def test_admin_licenses_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/admin/licenses",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        "/web-api/v1/admin/licenses",
        body={"id": "x", "name": "y", "short_name": "z"},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/admin/licenses/CC-BY-4.0",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        "/web-api/v1/admin/licenses/CC-BY-4.0",
        body={"description": "x"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        "/web-api/v1/admin/licenses/CC-BY-4.0",
    )
