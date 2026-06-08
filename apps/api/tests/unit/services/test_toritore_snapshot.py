"""Snapshot-population tests for ``AnnotationSegmentService.create_annotation``.

Verifies that creating a TimeRangeAnnotation snapshots the annotator's
ToriTore proficiency onto the row (Part B) and applies the participation
gate. The gate is enforced UNCONDITIONALLY: on the BFF path the caller
supplies ``project_id``; on the legacy path it is resolved from the segment's
AnnotationSet (so the gate cannot be bypassed by calling the legacy endpoint).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.schemas.annotation_set import TimeRangeAnnotationCreate
from echoroo.services.annotation_segment import AnnotationSegmentService


def _make_segment() -> MagicMock:
    seg = MagicMock()
    seg.id = uuid4()
    seg.annotation_set_id = uuid4()
    seg.recording_id = uuid4()
    seg.start_time_sec = 0.0
    seg.end_time_sec = 30.0
    seg.is_empty = True
    seg.status = AnnotationSegmentStatus.UNANNOTATED
    return seg


def _make_service(*, segment: MagicMock, taxon_gbif_key: int | None) -> tuple[
    AnnotationSegmentService, MagicMock, SimpleNamespace
]:
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    seg_repo = MagicMock()
    seg_repo.db = db
    seg_repo.get_by_id = AsyncMock(return_value=segment)

    created_row = SimpleNamespace(
        id=uuid4(),
        segment_id=segment.id,
        start_time_sec=1.0,
        end_time_sec=2.0,
        taxon_id=uuid4(),
        confidence=None,
        created_by_id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        annotator_species_score=None,
        annotator_total_score=None,
        annotator_test_reference=None,
    )

    ann_repo = MagicMock()
    ann_repo.db = db
    ann_repo.create = AsyncMock(return_value=created_row)
    ann_repo.count_notes = AsyncMock(return_value=0)

    set_service = MagicMock()

    service = AnnotationSegmentService(
        segment_repo=seg_repo,
        annotation_repo=ann_repo,
        set_service=set_service,
    )

    # Stub _require_taxon + _set_min_total_score + the response builder so the
    # test focuses on the snapshot wiring.
    taxon = SimpleNamespace(id=created_row.taxon_id, gbif_taxon_key=taxon_gbif_key)
    service._require_taxon = AsyncMock(return_value=taxon)  # type: ignore[method-assign]
    service._set_min_total_score = AsyncMock(return_value=None)  # type: ignore[method-assign]
    # The legacy path resolves the project from the set; stub it so the gate
    # has a project_id to evaluate against (the gate is a no-op when
    # min_total_score is None).
    service._resolve_project_id = AsyncMock(return_value=uuid4())  # type: ignore[method-assign]
    service._annotation_to_response = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]
    return service, ann_repo, created_row


@pytest.mark.asyncio
async def test_snapshot_populated_on_create() -> None:
    """The created row gets species/total/reference snapshot values."""
    segment = _make_segment()
    service, _ann_repo, created_row = _make_service(
        segment=segment, taxon_gbif_key=9515886
    )
    request = TimeRangeAnnotationCreate(
        start_time_sec=1.0, end_time_sec=2.0, species_id=created_row.taxon_id,
    )
    with (
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_species_rate",
            new=AsyncMock(return_value=0.75),
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=0.769),
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_test_reference",
            new=AsyncMock(return_value="test#1@2026-06-04T14:23:25+09:00"),
        ),
    ):
        await service.create_annotation(
            segment.id, user_id=uuid4(), request=request,
        )

    assert created_row.annotator_species_score == 0.75
    assert created_row.annotator_total_score == 0.769
    assert created_row.annotator_test_reference == "test#1@2026-06-04T14:23:25+09:00"


@pytest.mark.asyncio
async def test_snapshot_species_score_none_when_no_gbif_key() -> None:
    """A taxon without a GBIF key yields a NULL species snapshot."""
    segment = _make_segment()
    service, _ann_repo, created_row = _make_service(
        segment=segment, taxon_gbif_key=None
    )
    request = TimeRangeAnnotationCreate(
        start_time_sec=1.0, end_time_sec=2.0, species_id=created_row.taxon_id,
    )
    species_rate = AsyncMock(return_value=0.9)
    with (
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_species_rate",
            new=species_rate,
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=0.5),
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_test_reference",
            new=AsyncMock(return_value=None),
        ),
    ):
        await service.create_annotation(
            segment.id, user_id=uuid4(), request=request,
        )

    species_rate.assert_not_awaited()
    assert created_row.annotator_species_score is None
    assert created_row.annotator_total_score == 0.5


@pytest.mark.asyncio
async def test_gate_blocks_create_when_project_id_supplied() -> None:
    """When project_id is set and the gate denies, create raises 403."""
    segment = _make_segment()
    service, ann_repo, created_row = _make_service(
        segment=segment, taxon_gbif_key=9515886
    )
    service._set_min_total_score = AsyncMock(return_value=0.2)  # type: ignore[method-assign]
    request = TimeRangeAnnotationCreate(
        start_time_sec=1.0, end_time_sec=2.0, species_id=created_row.taxon_id,
    )
    with (
        patch(
            "echoroo.services.annotation_segment.enforce_participation_gate",
            new=AsyncMock(
                side_effect=HTTPException(status_code=403, detail={"code": "x"})
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await service.create_annotation(
            segment.id,
            user_id=uuid4(),
            request=request,
            project_id=uuid4(),
        )
    assert exc_info.value.status_code == 403
    ann_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_enforced_on_legacy_path_resolves_project_and_blocks() -> None:
    """Legacy path (no project_id): project is resolved + below-threshold blocks.

    A monitor below the threshold must be blocked even when the caller omits
    ``project_id`` (the legacy ``/segments/{id}/annotations`` endpoint), proving
    the gate is no longer bypassable.
    """
    segment = _make_segment()
    service, ann_repo, created_row = _make_service(
        segment=segment, taxon_gbif_key=9515886
    )
    service._set_min_total_score = AsyncMock(return_value=0.2)  # type: ignore[method-assign]
    resolved_project_id = uuid4()
    service._resolve_project_id = AsyncMock(  # type: ignore[method-assign]
        return_value=resolved_project_id
    )
    request = TimeRangeAnnotationCreate(
        start_time_sec=1.0, end_time_sec=2.0, species_id=created_row.taxon_id,
    )
    gate = AsyncMock(
        side_effect=HTTPException(
            status_code=403, detail={"code": "toritore_score_insufficient"}
        )
    )
    with (
        patch(
            "echoroo.services.annotation_segment.enforce_participation_gate",
            new=gate,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await service.create_annotation(
            segment.id,
            user_id=uuid4(),
            request=request,
        )
    assert exc_info.value.status_code == 403
    # The gate was invoked with the project resolved from the segment chain.
    service._resolve_project_id.assert_awaited_once_with(segment.annotation_set_id)
    assert gate.await_args.kwargs["project_id"] == resolved_project_id
    assert gate.await_args.kwargs["min_total_score"] == 0.2
    ann_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_gate_enforced_on_legacy_path_owner_admin_exempt() -> None:
    """Legacy path: owner/admin is exempt so create succeeds (gate is a no-op)."""
    segment = _make_segment()
    service, ann_repo, created_row = _make_service(
        segment=segment, taxon_gbif_key=None
    )
    service._set_min_total_score = AsyncMock(return_value=0.2)  # type: ignore[method-assign]
    service._resolve_project_id = AsyncMock(return_value=uuid4())  # type: ignore[method-assign]
    request = TimeRangeAnnotationCreate(
        start_time_sec=1.0, end_time_sec=2.0, species_id=created_row.taxon_id,
    )
    # Gate returns without raising (owner/admin exemption handled inside it).
    gate = AsyncMock(return_value=None)
    with (
        patch(
            "echoroo.services.annotation_segment.enforce_participation_gate",
            new=gate,
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_test_reference",
            new=AsyncMock(return_value=None),
        ),
    ):
        await service.create_annotation(
            segment.id,
            user_id=uuid4(),
            request=request,
        )
    gate.assert_awaited_once()
    ann_repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_enforced_on_legacy_path_no_threshold_passes() -> None:
    """Legacy path: a set with no threshold (min_total_score=None) passes.

    The gate is still invoked (unconditional enforcement) but is a no-op, so
    the annotation is created normally.
    """
    segment = _make_segment()
    service, ann_repo, created_row = _make_service(
        segment=segment, taxon_gbif_key=None
    )
    # _set_min_total_score already returns None in _make_service.
    request = TimeRangeAnnotationCreate(
        start_time_sec=1.0, end_time_sec=2.0, species_id=created_row.taxon_id,
    )
    gate = AsyncMock(return_value=None)
    with (
        patch(
            "echoroo.services.annotation_segment.enforce_participation_gate",
            new=gate,
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_total_score",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "echoroo.services.annotation_segment.toritore_service.get_latest_test_reference",
            new=AsyncMock(return_value=None),
        ),
    ):
        await service.create_annotation(
            segment.id,
            user_id=uuid4(),
            request=request,
        )
    # Gate invoked unconditionally with the no-op threshold.
    gate.assert_awaited_once()
    assert gate.await_args.kwargs["min_total_score"] is None
    ann_repo.create.assert_awaited_once()
