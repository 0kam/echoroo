"""Coverage uplift unit tests for ``echoroo.services.annotation_segment``.

Phase 17 §C heavy-gap batch: targets the ``_require_segment`` 404 branch
(lines 76, 86), the ``_note_to_response`` builder (line 93), the detail
view's recording row branch (lines 130-156), the empty-with-annotations
guard (lines 174-176), the ``create_annotation`` end-time guard (lines
238-240), and the ``create_note`` add+attach path (lines 304-315) so
the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.schemas.annotation_set import (
    AnnotationNoteCreate,
    AnnotationSegmentStatusUpdate,
    TimeRangeAnnotationCreate,
)
from echoroo.services.annotation_segment import AnnotationSegmentService


def _make_service(
    *,
    db: MagicMock,
    segment: MagicMock | None,
) -> AnnotationSegmentService:
    """Wire an AnnotationSegmentService with mocked repos and AnnotationSetService."""
    seg_repo = MagicMock()
    seg_repo.db = db
    seg_repo.get_by_id = AsyncMock(return_value=segment)
    seg_repo.get_with_annotations_and_notes = AsyncMock(return_value=segment)
    seg_repo.attach_note = AsyncMock(return_value=None)

    ann_repo = MagicMock()
    ann_repo.create = AsyncMock()
    ann_repo.count_notes = AsyncMock(return_value=0)

    set_service = MagicMock()
    set_service.recompute_status = AsyncMock(return_value=None)

    return AnnotationSegmentService(
        segment_repo=seg_repo,
        annotation_repo=ann_repo,
        set_service=set_service,
    )


def _make_segment(
    *,
    is_empty: bool = True,
    annotations: list[MagicMock] | None = None,
    notes: list[MagicMock] | None = None,
) -> MagicMock:
    seg = MagicMock()
    seg.id = uuid4()
    seg.annotation_set_id = uuid4()
    seg.recording_id = uuid4()
    seg.start_time_sec = 0.0
    seg.end_time_sec = 30.0
    seg.is_empty = is_empty
    seg.status = AnnotationSegmentStatus.UNANNOTATED
    seg.annotated_at = None
    seg.annotated_by_id = None
    seg.created_at = datetime.now(UTC)
    seg.updated_at = datetime.now(UTC)
    seg.annotations = annotations or []
    seg.notes = notes or []
    return seg


@pytest.mark.asyncio
async def test_require_segment_raises_404_when_missing() -> None:
    """_require_segment raises 404 when get_by_id returns None (lines 76)."""
    db = MagicMock()
    service = _make_service(db=db, segment=None)
    with pytest.raises(HTTPException) as exc_info:
        await service._require_segment(uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_require_taxon_raises_404_when_missing() -> None:
    """_require_taxon raises 404 when no row matches (line 86)."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)
    service = _make_service(db=db, segment=None)
    with pytest.raises(HTTPException) as exc_info:
        await service._require_taxon(uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_create_annotation_rejects_out_of_range_end_time() -> None:
    """create_annotation rejects end_time_sec exceeding segment duration (lines 238-240)."""
    seg = _make_segment(annotations=[])
    db = MagicMock()
    service = _make_service(db=db, segment=seg)
    request = TimeRangeAnnotationCreate(
        start_time_sec=0.0,
        end_time_sec=100.0,  # exceeds 30s segment
        species_id=uuid4(),
        confidence=0.9,
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.create_annotation(seg.id, user_id=uuid4(), request=request)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_update_rejects_is_empty_true_with_annotations() -> None:
    """update() rejects is_empty=True when annotations exist."""
    annotation = MagicMock()
    seg = _make_segment(is_empty=False, annotations=[annotation])
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = _make_service(db=db, segment=seg)
    request = AnnotationSegmentStatusUpdate(is_empty=True)
    with pytest.raises(HTTPException) as exc_info:
        await service.update(seg.id, user_id=uuid4(), request=request)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_rejects_annotated_status_without_annotations_or_empty() -> None:
    """Transitioning to ANNOTATED without annotations or is_empty fails (line 229)."""
    seg = _make_segment(is_empty=False, annotations=[])
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    service = _make_service(db=db, segment=seg)
    request = AnnotationSegmentStatusUpdate(
        status=AnnotationSegmentStatus.ANNOTATED.value
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.update(seg.id, user_id=uuid4(), request=request)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_note_persists_and_attaches() -> None:
    """create_note() builds a Note, persists it, and attaches to segment (lines 304-315)."""
    seg = _make_segment()
    db = MagicMock()

    captured: dict[str, MagicMock] = {}

    def _add(obj: MagicMock) -> None:
        # Stamp an id on the note so the attach call has something to use.
        obj.id = uuid4()
        obj.created_by_id = uuid4()
        obj.created_at = datetime.now(UTC)
        captured["note"] = obj

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    service = _make_service(db=db, segment=seg)
    request = AnnotationNoteCreate(
        content="hello",
        is_issue=False,
    )
    out = await service.create_note(seg.id, user_id=uuid4(), request=request)
    assert out.content == "hello"
    db.add.assert_called_once()
    service.segment_repo.attach_note.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_marks_empty_and_recomputes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """update() with is_empty=True succeeds when no annotations exist (line 218).

    Also exercises the post-flush refresh + parent set recomputation
    (lines 243-249), and the get_detail path returning the new state.
    """
    seg = _make_segment(is_empty=False, annotations=[])
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    # get_detail() will be called at the end → stub the recording row
    # SELECT to return a tuple-like first().
    rec_result = MagicMock()
    rec_result.first.return_value = ("clip.wav", 30.0, 1.0)
    taxon_result = MagicMock()
    taxon_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(side_effect=[rec_result, taxon_result])

    service = _make_service(db=db, segment=seg)
    request = AnnotationSegmentStatusUpdate(is_empty=True)
    detail = await service.update(seg.id, user_id=uuid4(), request=request)
    assert detail.is_empty is True
    service.set_service.recompute_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_transitions_to_annotated_with_existing_annotation() -> None:
    """update() flips status to ANNOTATED + stamps annotated_at/by_id (lines 236-244)."""
    annotation = MagicMock()
    annotation.id = uuid4()
    annotation.segment_id = uuid4()
    annotation.start_time_sec = 0.0
    annotation.end_time_sec = 1.0
    annotation.taxon_id = uuid4()
    annotation.confidence = 0.9
    annotation.created_by_id = uuid4()
    annotation.created_at = datetime.now(UTC)
    annotation.updated_at = datetime.now(UTC)
    seg = _make_segment(is_empty=False, annotations=[annotation])

    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    rec_result = MagicMock()
    rec_result.first.return_value = None
    taxon_result = MagicMock()
    taxon_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(side_effect=[rec_result, taxon_result])

    service = _make_service(db=db, segment=seg)
    user_id = uuid4()
    request = AnnotationSegmentStatusUpdate(
        status=AnnotationSegmentStatus.ANNOTATED.value
    )
    await service.update(seg.id, user_id=user_id, request=request)
    assert seg.status == AnnotationSegmentStatus.ANNOTATED
    assert seg.annotated_by_id == user_id
    assert seg.annotated_at is not None


@pytest.mark.asyncio
async def test_update_transitions_to_unannotated_clears_stamps() -> None:
    """update() flipping back to UNANNOTATED clears annotated_at + by_id (lines 238-240)."""
    seg = _make_segment(is_empty=False, annotations=[])
    seg.status = AnnotationSegmentStatus.ANNOTATED
    seg.annotated_at = datetime.now(UTC)
    seg.annotated_by_id = uuid4()

    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    rec_result = MagicMock()
    rec_result.first.return_value = None
    taxon_result = MagicMock()
    taxon_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(side_effect=[rec_result, taxon_result])

    service = _make_service(db=db, segment=seg)
    request = AnnotationSegmentStatusUpdate(
        status=AnnotationSegmentStatus.UNANNOTATED.value
    )
    await service.update(seg.id, user_id=uuid4(), request=request)
    assert seg.status == AnnotationSegmentStatus.UNANNOTATED
    assert seg.annotated_at is None
    assert seg.annotated_by_id is None


@pytest.mark.asyncio
async def test_create_annotation_persists_and_flips_is_empty() -> None:
    """create_annotation() persists row + flips is_empty (lines 275-291)."""
    seg = _make_segment(is_empty=True, annotations=[])

    taxon_row = MagicMock()
    taxon_row.scientific_name = "Turdus merula"
    db = MagicMock()
    db.flush = AsyncMock()
    # _require_taxon → SELECT taxon → row + _annotation_to_response taxon SELECT.
    taxon_select_result = MagicMock()
    taxon_select_result.scalar_one_or_none.return_value = taxon_row
    db.execute = AsyncMock(return_value=taxon_select_result)

    created_annotation = MagicMock()
    created_annotation.id = uuid4()
    created_annotation.segment_id = seg.id
    created_annotation.start_time_sec = 0.0
    created_annotation.end_time_sec = 1.0
    created_annotation.taxon_id = uuid4()
    created_annotation.confidence = 0.9
    created_annotation.created_by_id = uuid4()
    created_annotation.created_at = datetime.now(UTC)
    created_annotation.updated_at = datetime.now(UTC)

    service = _make_service(db=db, segment=seg)
    service.annotation_repo.create = AsyncMock(return_value=created_annotation)
    service.annotation_repo.count_notes = AsyncMock(return_value=0)

    request = TimeRangeAnnotationCreate(
        start_time_sec=0.0,
        end_time_sec=1.0,
        species_id=created_annotation.taxon_id,
        confidence=0.9,
    )
    out = await service.create_annotation(seg.id, user_id=uuid4(), request=request)
    assert out.id == created_annotation.id
    # Invariant: is_empty flips to False.
    assert seg.is_empty is False


@pytest.mark.asyncio
async def test_get_detail_with_recording_row_and_annotations() -> None:
    """get_detail() loads recording row + maps annotations (lines 130-156)."""
    annotation = MagicMock()
    annotation.id = uuid4()
    annotation.segment_id = uuid4()
    annotation.start_time_sec = 1.0
    annotation.end_time_sec = 2.0
    annotation.taxon_id = uuid4()
    annotation.confidence = 0.8
    annotation.created_by_id = uuid4()
    annotation.created_at = datetime.now(UTC)
    annotation.updated_at = datetime.now(UTC)

    note = MagicMock()
    note.id = uuid4()
    note.content = "n"
    note.is_issue = False
    note.is_review = False
    note.created_by_id = uuid4()
    note.created_at = datetime.now(UTC)

    seg = _make_segment(annotations=[annotation], notes=[note])

    # Recording row + taxon name lookup.
    rec_result = MagicMock()
    rec_result.first.return_value = ("clip.wav", 30.0, 1.0)
    taxon_result = MagicMock()
    taxon_result.all = MagicMock(return_value=[(annotation.taxon_id, "Turdus merula")])

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[rec_result, taxon_result])

    service = _make_service(db=db, segment=seg)
    detail = await service.get_detail(seg.id)
    assert detail.recording_filename == "clip.wav"
    assert detail.recording_duration_sec == 30.0
    assert len(detail.annotations) == 1
    assert detail.annotations[0].species_scientific_name == "Turdus merula"
    assert len(detail.notes) == 1
