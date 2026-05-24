"""Smoke coverage for spec/009 PR 3a tag BFF adapters.

PR 3a moves the project Tag CRUD + helper surface from ``/api/v1`` to
``/web-api/v1``. Read endpoints are intentionally NOT gated (legacy
parity); only POST/PATCH/DELETE go through :func:`gate_action`. Tests
assert the canonical Action constant for each mutation (Codex P2-1) and
that read endpoints reach the legacy handler without a gate call.
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

from echoroo.api.v1 import tags as legacy_tags
from echoroo.api.web_v1.projects import _tags as bff_tags
from echoroo.core.actions import (
    TAG_CREATE_ACTION,
    TAG_DELETE_ACTION,
    TAG_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.enums import TagCategory
from echoroo.schemas.tag import (
    GBIFSuggestion,
    TagDetailResponse,
    TagListResponse,
    TagResponse,
    TagStatistic,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_tag_response(*, project_id: UUID, tag_id: UUID) -> TagResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return TagResponse(
        id=tag_id,
        project_id=project_id,
        parent_id=None,
        name="fake-tag",
        category=TagCategory.SPECIES,
        gbif_taxon_key=None,
        scientific_name=None,
        common_name=None,
        vernacular_name=None,
        taxon_id=None,
        created_at=now,
        updated_at=now,
    )


def _fake_tag_detail(*, project_id: UUID, tag_id: UUID) -> TagDetailResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return TagDetailResponse(
        id=tag_id,
        project_id=project_id,
        parent_id=None,
        name="fake-tag",
        category=TagCategory.SPECIES,
        gbif_taxon_key=None,
        scientific_name=None,
        common_name=None,
        vernacular_name=None,
        taxon_id=None,
        created_at=now,
        updated_at=now,
        children=[],
        usage_count=0,
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_tags.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_tags.get_tag_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_tag_list_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_list_tags(**kwargs: object) -> TagListResponse:
        captured.update(kwargs)
        return TagListResponse(items=[], total=0, page=1, page_size=50, pages=0)

    monkeypatch.setattr(legacy_tags, "list_tags", fake_list_tags)

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/web-api/v1/projects/{project_id}/tags")

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    # Read endpoint: legacy does not gate, BFF mirrors that contract.


@pytest.mark.asyncio
async def test_tag_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create_tag(**kwargs: object) -> TagResponse:
        captured.update(kwargs)
        return _fake_tag_response(project_id=project_id, tag_id=tag_id)

    monkeypatch.setattr(legacy_tags, "create_tag", fake_create_tag)
    monkeypatch.setattr(
        bff_tags, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/tags",
            json={"name": "robin", "category": "species"},
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    payload = captured["request"]
    assert isinstance(payload, legacy_tags.TagCreate)
    assert payload.name == "robin"
    assert gate_captured["action"] is TAG_CREATE_ACTION


@pytest.mark.asyncio
async def test_tag_gbif_suggest_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_gbif(**kwargs: object) -> list[GBIFSuggestion]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(legacy_tags, "gbif_suggest", fake_gbif)

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/tags/gbif-suggest?q=robin"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["q"] == "robin"


@pytest.mark.asyncio
async def test_tag_statistics_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_stats(**kwargs: object) -> list[TagStatistic]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(legacy_tags, "get_statistics", fake_stats)

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/tags/statistics"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id


@pytest.mark.asyncio
async def test_tag_get_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_get_tag(**kwargs: object) -> TagDetailResponse:
        captured.update(kwargs)
        return _fake_tag_detail(project_id=project_id, tag_id=tag_id)

    monkeypatch.setattr(legacy_tags, "get_tag", fake_get_tag)

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/tags/{tag_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["tag_id"] == tag_id


@pytest.mark.asyncio
async def test_tag_update_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_tag(**kwargs: object) -> TagResponse:
        captured.update(kwargs)
        return _fake_tag_response(project_id=project_id, tag_id=tag_id)

    monkeypatch.setattr(legacy_tags, "update_tag", fake_update_tag)
    monkeypatch.setattr(
        bff_tags, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/tags/{tag_id}",
            json={"name": "renamed"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["tag_id"] == tag_id
    payload = captured["request"]
    assert isinstance(payload, legacy_tags.TagUpdate)
    assert payload.name == "renamed"
    assert gate_captured["action"] is TAG_UPDATE_ACTION


@pytest.mark.asyncio
async def test_tag_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_tag(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_tags, "delete_tag", fake_delete_tag)
    monkeypatch.setattr(
        bff_tags, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/tags/{tag_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["tag_id"] == tag_id
    assert gate_captured["action"] is TAG_DELETE_ACTION


def test_tag_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    list_path = "/web-api/v1/projects/{project_id}/tags"
    assert "get" in paths[list_path]
    assert "post" in paths[list_path]

    detail_path = "/web-api/v1/projects/{project_id}/tags/{tag_id}"
    assert "get" in paths[detail_path]
    assert "patch" in paths[detail_path]
    assert "delete" in paths[detail_path]

    assert "get" in paths["/web-api/v1/projects/{project_id}/tags/gbif-suggest"]
    assert "get" in paths["/web-api/v1/projects/{project_id}/tags/statistics"]


@pytest.mark.asyncio
async def test_tag_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    tag_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/tags",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/tags",
        body={"name": "x", "category": "species"},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/tags/gbif-suggest?q=robin",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/tags/statistics",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/tags/{tag_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/projects/{project_id}/tags/{tag_id}",
        body={"name": "y"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/tags/{tag_id}",
    )
