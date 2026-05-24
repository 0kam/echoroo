"""Smoke coverage for spec/009 PR 3a clip write BFF adapters.

PR 3a moves the project clip write surface (create / update / delete /
auto-generate) from ``/api/v1`` to ``/web-api/v1``. The clip GET list +
GET detail counterparts already live on ``/web-api/v1`` via the
:mod:`._media` module (spec/009 PR D0), so this module only adds the
mutation surface.
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

from echoroo.api.v1 import clips as legacy_clips
from echoroo.api.web_v1.projects import _clips as bff_clips
from echoroo.core.actions import (
    CLIP_CREATE_ACTION,
    CLIP_DELETE_ACTION,
    CLIP_GENERATE_ACTION,
    CLIP_UPDATE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.schemas.clip import (
    ClipDetailResponse,
    ClipGenerateResponse,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_clip_detail(*, recording_id: UUID, clip_id: UUID) -> ClipDetailResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return ClipDetailResponse(
        id=clip_id,
        recording_id=recording_id,
        start_time=0.0,
        end_time=2.0,
        note=None,
        created_at=now,
        updated_at=now,
        duration=2.0,
        recording=None,
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
    app.include_router(bff_clips.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_clips.get_clip_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_clip_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    clip_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create_clip(**kwargs: object) -> ClipDetailResponse:
        captured.update(kwargs)
        return _fake_clip_detail(recording_id=recording_id, clip_id=clip_id)

    monkeypatch.setattr(legacy_clips, "create_clip", fake_create_clip)
    monkeypatch.setattr(
        bff_clips, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips",
            json={"start_time": 0.0, "end_time": 2.0, "note": None},
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    payload = captured["request"]
    assert isinstance(payload, legacy_clips.ClipCreate)
    assert payload.start_time == 0.0
    assert payload.end_time == 2.0
    assert gate_captured["action"] is CLIP_CREATE_ACTION


@pytest.mark.asyncio
async def test_clip_update_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    clip_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update_clip(**kwargs: object) -> ClipDetailResponse:
        captured.update(kwargs)
        return _fake_clip_detail(recording_id=recording_id, clip_id=clip_id)

    monkeypatch.setattr(legacy_clips, "update_clip", fake_update_clip)
    monkeypatch.setattr(
        bff_clips, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}",
            json={"note": "patched"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    assert captured["clip_id"] == clip_id
    payload = captured["request"]
    assert isinstance(payload, legacy_clips.ClipUpdate)
    assert payload.note == "patched"
    assert gate_captured["action"] is CLIP_UPDATE_ACTION


@pytest.mark.asyncio
async def test_clip_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    clip_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_clip(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_clips, "delete_clip", fake_delete_clip)
    monkeypatch.setattr(
        bff_clips, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    assert captured["clip_id"] == clip_id
    assert gate_captured["action"] is CLIP_DELETE_ACTION


@pytest.mark.asyncio
async def test_clip_generate_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_generate(**kwargs: object) -> ClipGenerateResponse:
        captured.update(kwargs)
        return ClipGenerateResponse(clips_created=0, clips=[])

    monkeypatch.setattr(legacy_clips, "generate_clips", fake_generate)
    monkeypatch.setattr(
        bff_clips, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate",
            json={"clip_length": 2.0, "overlap": 0.0, "start_time": 0.0},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    payload = captured["request"]
    assert isinstance(payload, legacy_clips.ClipGenerateRequest)
    assert payload.clip_length == 2.0
    assert gate_captured["action"] is CLIP_GENERATE_ACTION


def test_clip_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    clips_root = "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips"
    assert "post" in paths[clips_root]
    assert "post" in paths[f"{clips_root}/generate"]

    clip_item = f"{clips_root}/{{clip_id}}"
    assert "patch" in paths[clip_item]
    assert "delete" in paths[clip_item]


@pytest.mark.asyncio
async def test_clip_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    clip_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips",
        body={"start_time": 0.0, "end_time": 1.0},
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate",
        body={"clip_length": 2.0},
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}",
        body={"note": "x"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}",
    )
