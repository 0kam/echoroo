"""Smoke coverage for spec/009 PR 4 annotation-set BFF adapters.

PR 4 project-scopes the spec/003-annotation ground-truth surface
(``AnnotationSet`` + ``AnnotationSegment`` + ``TimeRangeAnnotation`` +
``EvaluationRun``) under ``/web-api/v1/projects/{project_id}/...``. Each
BFF handler is a thin adapter that fires :func:`gate_action` with a
project-scoped Action and delegates to the legacy handler. Tests
assert:

* delegation: legacy handler is called with the right kwargs.
* gating: the canonical per-endpoint Action constant is captured.
* OpenAPI: every path is declared on the router.
* surface separation: every path rejects ``Authorization: Bearer
  echoroo_*`` (D-2a #3 / FR-006 mirror).
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

from echoroo.api.v1 import annotation_sets as legacy_annotation_sets
from echoroo.api.v1 import evaluation as legacy_evaluation
from echoroo.api.v1 import segments as legacy_segments
from echoroo.api.v1 import time_range_annotations as legacy_time_range_annotations
from echoroo.api.web_v1.projects import _annotation_sets as bff_annotation_sets
from echoroo.core.actions import (
    ANNOTATION_BATCH_TAG_ACTION,
    ANNOTATION_CLIP_GET_ACTION,
    ANNOTATION_NOTE_CREATE_ACTION,
    EVALUATION_CREATE_ACTION,
    EVALUATION_RUN_DELETE_ACTION,
    EVALUATION_RUN_GET_ACTION,
    EVALUATION_RUNS_BY_SET_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.schemas.annotation_set import (
    AnnotationNoteResponse,
    AnnotationSegmentDetailResponse,
    AnnotationSegmentListResponse,
    AnnotationSetDetailResponse,
    AnnotationSetListResponse,
    AnnotationSetProgress,
    PaletteEntryResponse,
    TimeRangeAnnotationResponse,
)
from echoroo.schemas.evaluation import (
    EvaluationRunListResponse,
    EvaluationRunResponse,
    EvaluationSummary,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


# ---------------------------------------------------------------------------
# Fixtures and fake response factories
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 5, 24, tzinfo=UTC)


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    """Mount the BFF router and override every legacy service factory.

    The annotation-set BFF module touches four legacy service factories
    (``get_annotation_set_service``, ``get_segment_service``,
    ``get_annotation_service``, ``get_evaluation_service``); each test
    case only needs one of them but overriding all four keeps the
    helper symmetric across cases.
    """
    app = FastAPI()
    app.include_router(
        bff_annotation_sets.router, prefix="/web-api/v1/projects"
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[
        legacy_annotation_sets.get_annotation_set_service
    ] = lambda: service
    app.dependency_overrides[legacy_segments.get_segment_service] = (
        lambda: service
    )
    app.dependency_overrides[
        legacy_time_range_annotations.get_annotation_service
    ] = lambda: service
    app.dependency_overrides[legacy_evaluation.get_evaluation_service] = (
        lambda: service
    )
    return app


def _fake_set_detail(
    *, project_id: UUID, set_id: UUID
) -> AnnotationSetDetailResponse:
    return AnnotationSetDetailResponse(
        id=set_id,
        project_id=project_id,
        dataset_id=uuid4(),
        created_by_id=uuid4(),
        name="fake-set",
        filter_date_range=None,
        filter_time_of_day_range=None,
        segment_length_sec=60,
        num_segments=10,
        status="sampling",
        sampling_warning=None,
        created_at=_NOW,
        updated_at=_NOW,
        palette=[],
        progress=AnnotationSetProgress(
            total=0, unannotated=0, annotated=0, skipped=0, empty=0
        ),
    )


def _fake_segment_detail(
    *, set_id: UUID, segment_id: UUID
) -> AnnotationSegmentDetailResponse:
    return AnnotationSegmentDetailResponse(
        id=segment_id,
        annotation_set_id=set_id,
        recording_id=uuid4(),
        recording_filename=None,
        recording_duration_sec=None,
        start_time_sec=0.0,
        end_time_sec=60.0,
        is_empty=False,
        status="unannotated",
        annotated_by_id=None,
        annotated_at=None,
        annotations=[],
        notes=[],
        created_at=_NOW,
        updated_at=_NOW,
    )


def _fake_annotation(
    *, segment_id: UUID, annotation_id: UUID
) -> TimeRangeAnnotationResponse:
    return TimeRangeAnnotationResponse(
        id=annotation_id,
        segment_id=segment_id,
        start_time_sec=0.0,
        end_time_sec=1.0,
        species_id=uuid4(),
        species_scientific_name=None,
        species_common_name=None,
        confidence=None,
        created_by_id=uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
        note_count=0,
    )


def _fake_note() -> AnnotationNoteResponse:
    return AnnotationNoteResponse(
        id=uuid4(),
        content="x",
        is_issue=False,
        is_review=False,
        created_by_id=uuid4(),
        created_at=_NOW,
    )


def _fake_evaluation_run(*, set_id: UUID, run_id: UUID) -> EvaluationRunResponse:
    return EvaluationRunResponse(
        id=run_id,
        annotation_set_id=set_id,
        created_by_id=uuid4(),
        status="pending",
        requested_model_refs=[],
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _fake_evaluation_summary(
    *, set_id: UUID, run_id: UUID
) -> EvaluationSummary:
    return EvaluationSummary(
        id=run_id,
        annotation_set_id=set_id,
        status="pending",
        requested_model_refs=[],
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=_NOW,
        updated_at=_NOW,
        models=[],
    )


# ---------------------------------------------------------------------------
# AnnotationSet CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_annotation_sets_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list(**kwargs: object) -> AnnotationSetListResponse:
        captured.update(kwargs)
        return AnnotationSetListResponse(
            items=[], total=0, page=1, page_size=20
        )

    monkeypatch.setattr(
        legacy_annotation_sets, "list_annotation_sets", fake_list
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets?page=2&page_size=50"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    pagination = captured["pagination"]
    assert pagination.page == 2
    assert pagination.page_size == 50
    assert gate_captured["action"] is ANNOTATION_CLIP_GET_ACTION


@pytest.mark.asyncio
async def test_create_annotation_set_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> AnnotationSetDetailResponse:
        captured.update(kwargs)
        return _fake_set_detail(project_id=project_id, set_id=set_id)

    monkeypatch.setattr(
        legacy_annotation_sets, "create_annotation_set", fake_create
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/annotation-sets",
            json={
                "project_id": str(project_id),
                "dataset_id": str(dataset_id),
                "name": "fresh",
                "segment_length_sec": 30,
                "num_segments": 5,
            },
        )

    assert response.status_code == 201, response.text
    payload = captured["request"]
    assert payload.name == "fresh"
    assert payload.project_id == project_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_get_annotation_set_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get(**kwargs: object) -> AnnotationSetDetailResponse:
        captured.update(kwargs)
        return _fake_set_detail(project_id=project_id, set_id=set_id)

    monkeypatch.setattr(legacy_annotation_sets, "get_annotation_set", fake_get)
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["set_id"] == set_id
    assert gate_captured["action"] is ANNOTATION_CLIP_GET_ACTION


@pytest.mark.asyncio
async def test_update_annotation_set_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> AnnotationSetDetailResponse:
        captured.update(kwargs)
        return _fake_set_detail(project_id=project_id, set_id=set_id)

    monkeypatch.setattr(
        legacy_annotation_sets, "update_annotation_set", fake_update
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}",
            json={"name": "renamed"},
        )

    assert response.status_code == 200, response.text
    payload = captured["request"]
    assert payload.name == "renamed"
    assert captured["set_id"] == set_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_delete_annotation_set_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        legacy_annotation_sets, "delete_annotation_set", fake_delete
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["set_id"] == set_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_palette_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    species_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_add(**kwargs: object) -> PaletteEntryResponse:
        captured.update(kwargs)
        return PaletteEntryResponse(
            species_id=species_id,
            scientific_name=None,
            common_name=None,
            position=0,
        )

    monkeypatch.setattr(
        legacy_annotation_sets, "add_palette_species", fake_add
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/palette",
            json={"species_id": str(species_id), "position": 0},
        )

    assert response.status_code == 201, response.text
    assert captured["set_id"] == set_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_remove_palette_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    species_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_remove(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        legacy_annotation_sets, "remove_palette_species", fake_remove
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            f"/palette/{species_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["set_id"] == set_id
    assert captured["species_id"] == species_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_set_segments_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list(**kwargs: object) -> AnnotationSegmentListResponse:
        captured.update(kwargs)
        return AnnotationSegmentListResponse(
            items=[], total=0, page=1, page_size=50
        )

    monkeypatch.setattr(
        legacy_annotation_sets, "list_set_segments", fake_list
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/segments"
        )

    assert response.status_code == 200, response.text
    assert captured["set_id"] == set_id
    assert gate_captured["action"] is ANNOTATION_CLIP_GET_ACTION


@pytest.mark.asyncio
async def test_get_segment_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    segment_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get(**kwargs: object) -> AnnotationSegmentDetailResponse:
        captured.update(kwargs)
        return _fake_segment_detail(set_id=set_id, segment_id=segment_id)

    monkeypatch.setattr(legacy_segments, "get_segment", fake_get)
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/segments/{segment_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["segment_id"] == segment_id
    assert gate_captured["action"] is ANNOTATION_CLIP_GET_ACTION


@pytest.mark.asyncio
async def test_update_segment_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    segment_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> AnnotationSegmentDetailResponse:
        captured.update(kwargs)
        return _fake_segment_detail(set_id=set_id, segment_id=segment_id)

    monkeypatch.setattr(legacy_segments, "update_segment", fake_update)
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/segments/{segment_id}",
            json={"status": "annotated"},
        )

    assert response.status_code == 200, response.text
    assert captured["segment_id"] == segment_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_create_annotation_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    segment_id = uuid4()
    annotation_id = uuid4()
    species_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> TimeRangeAnnotationResponse:
        captured.update(kwargs)
        return _fake_annotation(
            segment_id=segment_id, annotation_id=annotation_id
        )

    monkeypatch.setattr(legacy_segments, "create_annotation", fake_create)
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/segments/{segment_id}/annotations",
            json={
                "start_time_sec": 0.0,
                "end_time_sec": 1.0,
                "species_id": str(species_id),
            },
        )

    assert response.status_code == 201, response.text
    assert captured["segment_id"] == segment_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_create_segment_note_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    segment_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_note(**kwargs: object) -> AnnotationNoteResponse:
        captured.update(kwargs)
        return _fake_note()

    monkeypatch.setattr(legacy_segments, "create_segment_note", fake_note)
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/segments/{segment_id}/notes",
            json={"content": "first note"},
        )

    assert response.status_code == 201, response.text
    assert captured["segment_id"] == segment_id
    assert gate_captured["action"] is ANNOTATION_NOTE_CREATE_ACTION


# ---------------------------------------------------------------------------
# TimeRangeAnnotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_annotation_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> TimeRangeAnnotationResponse:
        captured.update(kwargs)
        return _fake_annotation(segment_id=uuid4(), annotation_id=annotation_id)

    monkeypatch.setattr(
        legacy_time_range_annotations, "update_annotation", fake_update
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}",
            json={"confidence": 0.5},
        )

    assert response.status_code == 200, response.text
    assert captured["annotation_id"] == annotation_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_delete_annotation_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        legacy_time_range_annotations, "delete_annotation", fake_delete
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["annotation_id"] == annotation_id
    assert gate_captured["action"] is ANNOTATION_BATCH_TAG_ACTION


@pytest.mark.asyncio
async def test_create_annotation_note_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_note(**kwargs: object) -> AnnotationNoteResponse:
        captured.update(kwargs)
        return _fake_note()

    monkeypatch.setattr(
        legacy_time_range_annotations, "create_annotation_note", fake_note
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/notes",
            json={"content": "ok"},
        )

    assert response.status_code == 201, response.text
    assert captured["annotation_id"] == annotation_id
    assert gate_captured["action"] is ANNOTATION_NOTE_CREATE_ACTION


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evaluate_annotation_set_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    run_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> EvaluationRunResponse:
        captured.update(kwargs)
        return _fake_evaluation_run(set_id=set_id, run_id=run_id)

    monkeypatch.setattr(
        legacy_evaluation, "create_evaluation_run", fake_create
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/evaluate",
            json={"model_refs": [{"kind": "perch"}]},
        )

    assert response.status_code == 202, response.text
    assert captured["annotation_set_id"] == set_id
    assert gate_captured["action"] is EVALUATION_CREATE_ACTION


@pytest.mark.asyncio
async def test_list_evaluation_runs_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list(**kwargs: object) -> EvaluationRunListResponse:
        captured.update(kwargs)
        return EvaluationRunListResponse(items=[], total=0)

    monkeypatch.setattr(
        legacy_evaluation, "list_evaluation_runs_for_set", fake_list
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            "/evaluation-runs?limit=10&offset=2"
        )

    assert response.status_code == 200, response.text
    assert captured["annotation_set_id"] == set_id
    assert captured["limit"] == 10
    assert captured["offset"] == 2
    assert gate_captured["action"] is EVALUATION_RUNS_BY_SET_ACTION


@pytest.mark.asyncio
async def test_get_evaluation_run_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get(**kwargs: object) -> EvaluationSummary:
        captured.update(kwargs)
        return _fake_evaluation_summary(set_id=set_id, run_id=run_id)

    monkeypatch.setattr(legacy_evaluation, "get_evaluation_run", fake_get)
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/evaluation-runs/{run_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["run_id"] == run_id
    assert gate_captured["action"] is EVALUATION_RUN_GET_ACTION


@pytest.mark.asyncio
async def test_delete_evaluation_run_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(
        legacy_evaluation, "delete_evaluation_run", fake_delete
    )
    monkeypatch.setattr(
        bff_annotation_sets,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/evaluation-runs/{run_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["run_id"] == run_id
    assert gate_captured["action"] is EVALUATION_RUN_DELETE_ACTION


# ---------------------------------------------------------------------------
# OpenAPI surface declaration
# ---------------------------------------------------------------------------


def test_annotation_sets_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]
    project_prefix = "/web-api/v1/projects/{project_id}"

    sets_path = f"{project_prefix}/annotation-sets"
    assert "get" in paths[sets_path]
    assert "post" in paths[sets_path]

    set_detail = f"{sets_path}/{{set_id}}"
    assert "get" in paths[set_detail]
    assert "patch" in paths[set_detail]
    assert "delete" in paths[set_detail]
    assert "post" in paths[f"{set_detail}/palette"]
    assert "delete" in paths[f"{set_detail}/palette/{{species_id}}"]
    assert "get" in paths[f"{set_detail}/segments"]
    assert "post" in paths[f"{set_detail}/evaluate"]
    assert "get" in paths[f"{set_detail}/evaluation-runs"]

    segments_path = f"{project_prefix}/segments/{{segment_id}}"
    assert "get" in paths[segments_path]
    assert "patch" in paths[segments_path]
    assert "post" in paths[f"{segments_path}/annotations"]
    assert "post" in paths[f"{segments_path}/notes"]

    annotations_path = f"{project_prefix}/annotations/{{annotation_id}}"
    assert "patch" in paths[annotations_path]
    assert "delete" in paths[annotations_path]
    assert "post" in paths[f"{annotations_path}/notes"]

    runs_path = f"{project_prefix}/evaluation-runs/{{run_id}}"
    assert "get" in paths[runs_path]
    assert "delete" in paths[runs_path]


# ---------------------------------------------------------------------------
# API-key cross-rejection sweep (D-2a #3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annotation_sets_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    set_id = uuid4()
    species_id = uuid4()
    segment_id = uuid4()
    annotation_id = uuid4()
    run_id = uuid4()
    project_prefix = f"/web-api/v1/projects/{project_id}"

    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/annotation-sets"
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/annotation-sets",
        body={
            "project_id": str(project_id),
            "dataset_id": str(uuid4()),
            "name": "x",
            "segment_length_sec": 10,
            "num_segments": 1,
        },
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/annotation-sets/{set_id}"
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"{project_prefix}/annotation-sets/{set_id}",
        body={"name": "x"},
    )
    await assert_api_key_cross_rejected(
        client, "DELETE", f"{project_prefix}/annotation-sets/{set_id}"
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/annotation-sets/{set_id}/palette",
        body={"species_id": str(species_id), "position": 0},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"{project_prefix}/annotation-sets/{set_id}/palette/{species_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/annotation-sets/{set_id}/segments",
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/segments/{segment_id}"
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"{project_prefix}/segments/{segment_id}",
        body={"status": "annotated"},
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/segments/{segment_id}/annotations",
        body={
            "start_time_sec": 0.0,
            "end_time_sec": 1.0,
            "species_id": str(uuid4()),
        },
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/segments/{segment_id}/notes",
        body={"content": "n"},
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"{project_prefix}/annotations/{annotation_id}",
        body={"confidence": 0.5},
    )
    await assert_api_key_cross_rejected(
        client, "DELETE", f"{project_prefix}/annotations/{annotation_id}"
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/annotations/{annotation_id}/notes",
        body={"content": "n"},
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/annotation-sets/{set_id}/evaluate",
        body={"model_refs": [{"kind": "perch"}]},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/annotation-sets/{set_id}/evaluation-runs",
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/evaluation-runs/{run_id}"
    )
    await assert_api_key_cross_rejected(
        client, "DELETE", f"{project_prefix}/evaluation-runs/{run_id}"
    )
