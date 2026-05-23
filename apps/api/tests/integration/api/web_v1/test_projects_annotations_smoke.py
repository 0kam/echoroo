"""Smoke coverage for spec/009 PR 2.5 annotation BFF adapters.

PR 2.5 migrates the 8 annotation-task surface endpoints from
``/api/v1`` to ``/web-api/v1`` (clip-annotation get/tag, sound-event
create/delete/tag, review). The legacy handlers continue to own service
orchestration and schema validation; the BFF layer only adds the
cookie + CSRF gating and re-uses :func:`gate_action` for the permission
decision.

These tests mirror :mod:`test_projects_write_mutations_smoke` (PR 2):
build a minimal FastAPI app with the BFF router mounted, monkey-patch
the legacy handler with a capture-style fake, and assert the BFF
(1) routes the call through to the legacy handler with the right
arguments, (2) preserves the legacy response shape, (3) declares each
path in the OpenAPI schema so downstream contract diff suites detect
drift, and (4) invokes ``gate_action`` with the canonical ``Action``
constant for each endpoint (Codex P2-1 improvement: assert the
permission gate is wired to the correct Action, not just that *some*
gate ran).

Spec/009 §D-2a contract checks (CSRF / API-key cross-rejection / 403
vs 401 / audit ``actor_kind == "session"``) are exercised at the
integration boundary by the existing helpers in :mod:`_helpers`; this
module focuses on the BFF→legacy wiring contract.
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

from echoroo.api.v1 import annotations as legacy_annotations
from echoroo.api.web_v1.projects import _annotations as bff_annotations
from echoroo.core.actions import (
    ANNOTATION_CLIP_GET_ACTION,
    ANNOTATION_CLIP_TAG_CREATE_ACTION,
    ANNOTATION_CLIP_TAG_DELETE_ACTION,
    ANNOTATION_REVIEW_ACTION,
    ANNOTATION_SOUND_EVENT_CREATE_ACTION,
    ANNOTATION_SOUND_EVENT_DELETE_ACTION,
    ANNOTATION_SOUND_EVENT_TAG_CREATE_ACTION,
    ANNOTATION_SOUND_EVENT_TAG_DELETE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.enums import AnnotationSource, ReviewStatus
from echoroo.schemas.annotation import (
    ClipAnnotationDetailResponse,
    SoundEventAnnotationResponse,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected

# ---------------------------------------------------------------------------
# Response-model builders.
# ---------------------------------------------------------------------------


def _fake_clip_annotation_detail(
    *, clip_annotation_id: UUID, task_id: UUID, user_id: UUID
) -> ClipAnnotationDetailResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return ClipAnnotationDetailResponse(
        id=clip_annotation_id,
        task_id=task_id,
        clip_id=uuid4(),
        review_status=ReviewStatus.UNREVIEWED,
        reviewed_by_id=None,
        reviewed_at=None,
        tags=[],
        sound_events=[],
        notes=[],
        created_by_id=user_id,
        created_at=now,
        updated_at=now,
    )


def _fake_sound_event_response(
    *, sound_event_id: UUID, clip_annotation_id: UUID, user_id: UUID
) -> SoundEventAnnotationResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return SoundEventAnnotationResponse(
        id=sound_event_id,
        clip_annotation_id=clip_annotation_id,
        geometry={"type": "TimeInterval", "coordinates": [0.0, 1.0]},
        source=AnnotationSource.HUMAN,
        confidence=None,
        tags=[],
        created_by_id=user_id,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Test app + utilities.
# ---------------------------------------------------------------------------


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    """Build a capture-style ``gate_action`` replacement.

    Spec/009 PR 2 follow-up (Codex P2-1): the BFF→legacy wiring is only
    fully verified if the test also asserts that ``gate_action`` was
    called with the canonical ``Action`` constant for the endpoint.
    The bare no-op replacement used in earlier tests only proved that
    *a* gate ran, not that the *right* gate ran. This helper records
    every kwarg so individual tests can assert ``captured["action"]``
    against the expected ``Action`` constant.
    """

    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    """Build a minimal FastAPI app with the annotation BFF router mounted."""
    app = FastAPI()
    app.include_router(bff_annotations.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_annotations.get_annotation_service] = (
        lambda: service
    )
    return app


# ---------------------------------------------------------------------------
# GET /annotation-tasks/{task_id}/clip-annotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_annotation_get_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    task_id = uuid4()
    clip_annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_or_create(**kwargs: object) -> ClipAnnotationDetailResponse:
        captured.update(kwargs)
        return _fake_clip_annotation_detail(
            clip_annotation_id=clip_annotation_id,
            task_id=task_id,
            user_id=user.id,
        )

    monkeypatch.setattr(
        legacy_annotations, "get_or_create_clip_annotation", fake_get_or_create
    )
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["task_id"] == task_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    assert gate_captured["action"] is ANNOTATION_CLIP_GET_ACTION
    assert gate_captured["project_id"] == project_id


# ---------------------------------------------------------------------------
# POST /clip-annotations/{cid}/tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_tag_add_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    clip_annotation_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_add_clip_tag(**kwargs: object) -> ClipAnnotationDetailResponse:
        captured.update(kwargs)
        return _fake_clip_annotation_detail(
            clip_annotation_id=clip_annotation_id,
            task_id=uuid4(),
            user_id=user.id,
        )

    monkeypatch.setattr(legacy_annotations, "add_clip_tag", fake_add_clip_tag)
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags",
            json={"tag_id": str(tag_id)},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["clip_annotation_id"] == clip_annotation_id
    payload = captured["request"]
    assert isinstance(payload, legacy_annotations.AddTagRequest)
    assert payload.tag_id == tag_id
    assert gate_captured["action"] is ANNOTATION_CLIP_TAG_CREATE_ACTION


# ---------------------------------------------------------------------------
# DELETE /clip-annotations/{cid}/tags/{tid}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_tag_remove_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    clip_annotation_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_remove_clip_tag(**kwargs: object) -> ClipAnnotationDetailResponse:
        captured.update(kwargs)
        return _fake_clip_annotation_detail(
            clip_annotation_id=clip_annotation_id,
            task_id=uuid4(),
            user_id=user.id,
        )

    monkeypatch.setattr(legacy_annotations, "remove_clip_tag", fake_remove_clip_tag)
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags/{tag_id}",
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["clip_annotation_id"] == clip_annotation_id
    assert captured["tag_id"] == tag_id
    assert gate_captured["action"] is ANNOTATION_CLIP_TAG_DELETE_ACTION


# ---------------------------------------------------------------------------
# POST /clip-annotations/{cid}/sound-events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sound_event_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    clip_annotation_id = uuid4()
    sound_event_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create_sound_event(**kwargs: object) -> SoundEventAnnotationResponse:
        captured.update(kwargs)
        return _fake_sound_event_response(
            sound_event_id=sound_event_id,
            clip_annotation_id=clip_annotation_id,
            user_id=user.id,
        )

    monkeypatch.setattr(
        legacy_annotations, "create_sound_event", fake_create_sound_event
    )
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/sound-events",
            json={
                "geometry": {"type": "TimeInterval", "coordinates": [0.0, 1.5]},
                "tag_ids": None,
                "confidence": None,
                "source": "human",
            },
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    assert captured["clip_annotation_id"] == clip_annotation_id
    payload = captured["request"]
    assert isinstance(payload, legacy_annotations.SoundEventAnnotationCreate)
    assert payload.geometry.type == "TimeInterval"
    assert payload.geometry.coordinates == [0.0, 1.5]
    assert gate_captured["action"] is ANNOTATION_SOUND_EVENT_CREATE_ACTION


# ---------------------------------------------------------------------------
# DELETE /sound-events/{sid}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sound_event_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    sound_event_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_sound_event(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        legacy_annotations, "delete_sound_event", fake_delete_sound_event
    )
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}",
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["sound_event_id"] == sound_event_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    assert gate_captured["action"] is ANNOTATION_SOUND_EVENT_DELETE_ACTION


# ---------------------------------------------------------------------------
# POST /sound-events/{sid}/tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sound_event_tag_add_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    sound_event_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_add_sound_event_tag(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        legacy_annotations, "add_sound_event_tag", fake_add_sound_event_tag
    )
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}/tags",
            json={"tag_id": str(tag_id)},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["sound_event_id"] == sound_event_id
    payload = captured["request"]
    assert isinstance(payload, legacy_annotations.AddTagRequest)
    assert payload.tag_id == tag_id
    assert gate_captured["action"] is ANNOTATION_SOUND_EVENT_TAG_CREATE_ACTION


# ---------------------------------------------------------------------------
# DELETE /sound-events/{sid}/tags/{tid}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sound_event_tag_remove_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    sound_event_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_remove_sound_event_tag(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(
        legacy_annotations, "remove_sound_event_tag", fake_remove_sound_event_tag
    )
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}/tags/{tag_id}",
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["sound_event_id"] == sound_event_id
    assert captured["tag_id"] == tag_id
    assert gate_captured["action"] is ANNOTATION_SOUND_EVENT_TAG_DELETE_ACTION


# ---------------------------------------------------------------------------
# POST /clip-annotations/{cid}/review
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clip_annotation_review_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    clip_annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_review(**kwargs: object) -> ClipAnnotationDetailResponse:
        captured.update(kwargs)
        return _fake_clip_annotation_detail(
            clip_annotation_id=clip_annotation_id,
            task_id=uuid4(),
            user_id=user.id,
        )

    monkeypatch.setattr(legacy_annotations, "review_clip_annotation", fake_review)
    monkeypatch.setattr(
        bff_annotations, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
            json={"status": "approved", "comment": "looks good"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["clip_annotation_id"] == clip_annotation_id
    payload = captured["request"]
    assert isinstance(payload, legacy_annotations.ReviewRequest)
    assert payload.status == "approved"
    assert payload.comment == "looks good"
    assert gate_captured["action"] is ANNOTATION_REVIEW_ACTION


# ---------------------------------------------------------------------------
# OpenAPI declaration check (contract diff suites).
# ---------------------------------------------------------------------------


def test_annotation_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    clip_get = (
        "/web-api/v1/projects/{project_id}"
        "/annotation-tasks/{task_id}/clip-annotation"
    )
    assert "get" in paths[clip_get]

    clip_tags = (
        "/web-api/v1/projects/{project_id}"
        "/clip-annotations/{clip_annotation_id}/tags"
    )
    assert "post" in paths[clip_tags]

    clip_tag_delete = (
        "/web-api/v1/projects/{project_id}"
        "/clip-annotations/{clip_annotation_id}/tags/{tag_id}"
    )
    assert "delete" in paths[clip_tag_delete]

    sound_events = (
        "/web-api/v1/projects/{project_id}"
        "/clip-annotations/{clip_annotation_id}/sound-events"
    )
    assert "post" in paths[sound_events]

    sound_event_root = "/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}"
    assert "delete" in paths[sound_event_root]

    sound_event_tags = f"{sound_event_root}/tags"
    assert "post" in paths[sound_event_tags]

    sound_event_tag_delete = f"{sound_event_root}/tags/{{tag_id}}"
    assert "delete" in paths[sound_event_tag_delete]

    review = (
        "/web-api/v1/projects/{project_id}"
        "/clip-annotations/{clip_annotation_id}/review"
    )
    assert "post" in paths[review]


# ---------------------------------------------------------------------------
# API key cross-rejection (spec/009 §D-2a #3).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annotation_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    task_id = uuid4()
    clip_annotation_id = uuid4()
    sound_event_id = uuid4()
    tag_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags",
        body={"tag_id": str(tag_id)},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags/{tag_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/sound-events",
        body={
            "geometry": {"type": "TimeInterval", "coordinates": [0.0, 1.0]},
            "tag_ids": None,
            "confidence": None,
            "source": "human",
        },
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}/tags",
        body={"tag_id": str(tag_id)},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/sound-events/{sound_event_id}/tags/{tag_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
        body={"status": "approved", "comment": None},
    )
