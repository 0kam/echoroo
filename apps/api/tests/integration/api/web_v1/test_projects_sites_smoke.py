"""Smoke coverage for spec/009 PR 3a site BFF adapters.

PR 3a moves the project Site CRUD surface from ``/api/v1`` to
``/web-api/v1``. The legacy handlers continue to own service
orchestration plus the Stage-2 H3 geospatial filter; the BFF layer only
adds cookie + CSRF gating and re-uses :func:`gate_action` for the
permission decision.

These tests mirror :mod:`test_projects_annotations_smoke` (PR 2.5):
build a minimal FastAPI app with the BFF router mounted, monkey-patch
the legacy handler with a capture-style fake, and assert the BFF
(1) routes the call through to the legacy handler with the right
arguments, (2) preserves the legacy response shape, (3) declares each
path in the OpenAPI schema, and (4) invokes ``gate_action`` with the
canonical ``Action`` constant for each endpoint (Codex P2-1 from PR 2.5
follow-up).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import sites as legacy_sites
from echoroo.api.web_v1.projects import _sites as bff_sites
from echoroo.core.actions import (
    SITE_CREATE_ACTION,
    SITE_DELETE_ACTION,
    SITE_GET_ACTION,
    SITE_LIST_ACTION,
    SITE_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.schemas.site import (
    SiteDetailResponse,
    SiteListResponse,
    SiteResponse,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_site_response(*, project_id: UUID, site_id: UUID) -> SiteResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return SiteResponse(
        id=site_id,
        project_id=project_id,
        name="fake-site",
        h3_index_member="8f283470d92dbff",
        h3_index_member_resolution=15,
        created_at=now,
        updated_at=now,
    )


def _fake_site_detail(*, project_id: UUID, site_id: UUID) -> SiteDetailResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return SiteDetailResponse(
        id=site_id,
        project_id=project_id,
        name="fake-site",
        h3_index_member="8f283470d92dbff",
        h3_index_member_resolution=15,
        created_at=now,
        updated_at=now,
        dataset_count=0,
        recording_count=0,
        total_duration=0.0,
        boundary=None,
    )


def _fake_site_list(*, project_id: UUID) -> SiteListResponse:
    return SiteListResponse(items=[], total=0, page=1, page_size=20, pages=0)


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_sites.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_sites.get_site_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_site_list_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list_sites(**kwargs: object) -> SiteListResponse:
        captured.update(kwargs)
        return _fake_site_list(project_id=project_id)

    monkeypatch.setattr(legacy_sites, "list_sites", fake_list_sites)
    monkeypatch.setattr(
        bff_sites, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/web-api/v1/projects/{project_id}/sites")

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    assert gate_captured["action"] is SITE_LIST_ACTION


@pytest.mark.asyncio
async def test_site_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    site_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create_site(**kwargs: object) -> SiteResponse:
        captured.update(kwargs)
        return _fake_site_response(project_id=project_id, site_id=site_id)

    monkeypatch.setattr(legacy_sites, "create_site", fake_create_site)
    monkeypatch.setattr(
        bff_sites, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/sites",
            json={"name": "new-site", "h3_index_member": "8f283470d92dbff"},
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    payload = captured["request"]
    assert isinstance(payload, legacy_sites.SiteCreate)
    assert payload.name == "new-site"
    assert gate_captured["action"] is SITE_CREATE_ACTION


@pytest.mark.asyncio
async def test_site_get_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    site_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_site(**kwargs: object) -> SiteDetailResponse:
        captured.update(kwargs)
        return _fake_site_detail(project_id=project_id, site_id=site_id)

    monkeypatch.setattr(legacy_sites, "get_site", fake_get_site)
    monkeypatch.setattr(
        bff_sites, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/sites/{site_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["site_id"] == site_id
    assert gate_captured["action"] is SITE_GET_ACTION


@pytest.mark.asyncio
async def test_site_update_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    site_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_site(**kwargs: object) -> SiteResponse:
        captured.update(kwargs)
        return _fake_site_response(project_id=project_id, site_id=site_id)

    monkeypatch.setattr(legacy_sites, "update_site", fake_update_site)
    monkeypatch.setattr(
        bff_sites, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/sites/{site_id}",
            json={"name": "renamed"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["site_id"] == site_id
    payload = captured["request"]
    assert isinstance(payload, legacy_sites.SiteUpdate)
    assert payload.name == "renamed"
    assert gate_captured["action"] is SITE_UPDATE_ACTION


@pytest.mark.asyncio
async def test_site_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    site_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_site(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_sites, "delete_site", fake_delete_site)
    monkeypatch.setattr(
        bff_sites, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/sites/{site_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["site_id"] == site_id
    assert gate_captured["action"] is SITE_DELETE_ACTION


def test_site_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    list_path = "/web-api/v1/projects/{project_id}/sites"
    assert "get" in paths[list_path]
    assert "post" in paths[list_path]

    detail_path = "/web-api/v1/projects/{project_id}/sites/{site_id}"
    assert "get" in paths[detail_path]
    assert "patch" in paths[detail_path]
    assert "delete" in paths[detail_path]


@pytest.mark.asyncio
async def test_site_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    site_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/sites",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/sites",
        body={"name": "x", "h3_index_member": "8f283470d92dbff"},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/sites/{site_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/projects/{project_id}/sites/{site_id}",
        body={"name": "y"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/sites/{site_id}",
    )
