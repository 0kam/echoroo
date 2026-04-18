"""Tests for annotation segment service invariants (spec 003-annotation §5).

These tests exercise the service layer logic directly using mock repositories
so they run without a database connection.  The invariants under test are pure
Python guard clauses that raise ``HTTPException``; no SQL is needed to verify
them.

Invariants covered:
- is_empty auto-flip to False when an annotation is created
- is_empty=True rejected (409) when TimeRangeAnnotations already exist
- end_time_sec > segment_duration raises 422
- start_time_sec >= end_time_sec rejected by Pydantic schema
- status=annotated with no annotations and is_empty=False raises 409
- status=annotated with is_empty=True succeeds (no annotations required)
- Adding a non-existent taxon to the palette raises 404
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.schemas.annotation_set import (
    AnnotationSegmentStatusUpdate,
    PaletteItemCreate,
    TimeRangeAnnotationCreate,
)
from echoroo.services.annotation_segment import AnnotationSegmentService
from echoroo.services.annotation_set import AnnotationSetService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_segment(
    *,
    is_empty: bool = False,
    status: AnnotationSegmentStatus = AnnotationSegmentStatus.UNANNOTATED,
    annotations: list[Any] | None = None,
    notes: list[Any] | None = None,
    start_time_sec: float = 0.0,
    end_time_sec: float = 30.0,
) -> MagicMock:
    """Return a MagicMock that behaves like an AnnotationSegment."""
    seg = MagicMock(spec=False)
    seg.id = uuid4()
    seg.annotation_set_id = uuid4()
    seg.recording_id = uuid4()
    seg.start_time_sec = start_time_sec
    seg.end_time_sec = end_time_sec
    seg.is_empty = is_empty
    seg.status = status
    seg.annotations = annotations if annotations is not None else []
    seg.notes = notes if notes is not None else []
    seg.annotated_by_id = None
    seg.annotated_at = None
    return seg


def _build_segment_service(
    *,
    segment: MagicMock,
    taxon_exists: bool = True,
    taxon_id_to_return: Any = None,
) -> AnnotationSegmentService:
    """Build AnnotationSegmentService with mocked repositories.

    Args:
        segment: Segment returned by both ``get_by_id`` and
            ``get_with_annotations_and_notes``.
        taxon_exists: When False, ``_require_taxon`` will raise 404.
        taxon_id_to_return: Taxon ID returned by the select for taxon lookup.
    """
    segment_repo = MagicMock()
    segment_repo.db = MagicMock()
    segment_repo.get_by_id = AsyncMock(return_value=segment)
    segment_repo.get_with_annotations_and_notes = AsyncMock(return_value=segment)

    annotation_repo = MagicMock()
    # count_notes returns 0 so response-building doesn't error.
    annotation_repo.count_notes = AsyncMock(return_value=0)

    # create returns a mock annotation with the needed fields.
    created_annotation = MagicMock()
    created_annotation.id = uuid4()
    created_annotation.segment_id = segment.id
    created_annotation.start_time_sec = 1.0
    created_annotation.end_time_sec = 5.0
    created_annotation.taxon_id = taxon_id_to_return or uuid4()
    created_annotation.confidence = None
    created_annotation.created_by_id = uuid4()
    _now = datetime.now(UTC)
    created_annotation.created_at = _now
    created_annotation.updated_at = _now
    annotation_repo.create = AsyncMock(return_value=created_annotation)

    set_service = MagicMock()
    set_service.recompute_status = AsyncMock()

    svc = AnnotationSegmentService(segment_repo, annotation_repo, set_service)

    # Mock the db.flush and db.refresh calls.
    svc.segment_repo.db.flush = AsyncMock()
    svc.segment_repo.db.refresh = AsyncMock()

    # Mock the taxon lookup used by _require_taxon and _annotation_to_response.
    taxon_mock = MagicMock()
    taxon_mock.scientific_name = "Turdus merula"
    taxon_mock.id = created_annotation.taxon_id

    mock_result = MagicMock()
    if taxon_exists:
        mock_result.scalar_one_or_none = MagicMock(return_value=taxon_mock)
    else:
        mock_result.scalar_one_or_none = MagicMock(return_value=None)

    svc.segment_repo.db.execute = AsyncMock(return_value=mock_result)

    return svc


# ---------------------------------------------------------------------------
# Tests: is_empty invariants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestIsEmptyFlip:
    """Creating an annotation must flip is_empty to False."""

    async def test_annotation_creation_flips_is_empty(self) -> None:
        segment = _make_segment(is_empty=True)
        svc = _build_segment_service(segment=segment)

        await svc.create_annotation(
            segment.id,
            user_id=uuid4(),
            request=TimeRangeAnnotationCreate(
                species_id=uuid4(),
                start_time_sec=1.0,
                end_time_sec=5.0,
            ),
        )

        assert segment.is_empty is False


@pytest.mark.asyncio
class TestIsEmptyRejectedWhenAnnotationsExist:
    """Setting is_empty=True must raise 409 when annotations already exist."""

    async def test_rejected_409(self) -> None:
        # Segment that already has 1 annotation.
        existing_ann = MagicMock()
        segment = _make_segment(is_empty=False, annotations=[existing_ann])
        svc = _build_segment_service(segment=segment)

        with pytest.raises(HTTPException) as exc_info:
            await svc.update(
                segment.id,
                user_id=uuid4(),
                request=AnnotationSegmentStatusUpdate(is_empty=True),
            )
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Tests: time bound validation
# ---------------------------------------------------------------------------


class TestAnnotationTimeBounds:
    """Time-range validation on TimeRangeAnnotationCreate."""

    @pytest.mark.asyncio
    async def test_end_time_exceeds_segment_length_raises_422(self) -> None:
        # Segment duration = 30 s; request end_time_sec = 35.0.
        segment = _make_segment(start_time_sec=0.0, end_time_sec=30.0)
        svc = _build_segment_service(segment=segment)

        with pytest.raises(HTTPException) as exc_info:
            await svc.create_annotation(
                segment.id,
                user_id=uuid4(),
                request=TimeRangeAnnotationCreate(
                    species_id=uuid4(),
                    start_time_sec=0.0,
                    end_time_sec=35.0,
                ),
            )
        assert exc_info.value.status_code == 422

    def test_start_gte_end_raises_pydantic_validation_error(self) -> None:
        """Pydantic schema rejects start >= end before service is reached."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TimeRangeAnnotationCreate(
                species_id=uuid4(),
                start_time_sec=10.0,
                end_time_sec=10.0,
            )

    def test_negative_start_raises_pydantic_validation_error(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            TimeRangeAnnotationCreate(
                species_id=uuid4(),
                start_time_sec=-1.0,
                end_time_sec=5.0,
            )


# ---------------------------------------------------------------------------
# Tests: complete segment requirements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCompleteSegmentRequirements:
    """status=annotated requires annotations or is_empty=True."""

    async def test_annotated_with_no_annotations_no_is_empty_raises_409(self) -> None:
        segment = _make_segment(is_empty=False, annotations=[])
        svc = _build_segment_service(segment=segment)

        with pytest.raises(HTTPException) as exc_info:
            await svc.update(
                segment.id,
                user_id=uuid4(),
                request=AnnotationSegmentStatusUpdate(
                    status=AnnotationSegmentStatus.ANNOTATED.value,
                ),
            )
        assert exc_info.value.status_code == 409

    async def test_annotated_with_is_empty_true_succeeds(self) -> None:
        """Guard passes; the mutated segment fields are confirmed before get_detail is reached."""
        segment = _make_segment(is_empty=False, annotations=[])
        svc = _build_segment_service(segment=segment)

        # Patch get_detail to avoid the full DB machinery — the invariant we are
        # testing is the guard logic, not the response serialisation.
        detail_response = MagicMock()
        detail_response.status = AnnotationSegmentStatus.ANNOTATED.value
        detail_response.is_empty = True
        svc.get_detail = AsyncMock(return_value=detail_response)

        result = await svc.update(
            segment.id,
            user_id=uuid4(),
            request=AnnotationSegmentStatusUpdate(
                is_empty=True,
                status=AnnotationSegmentStatus.ANNOTATED.value,
            ),
        )
        # Guard must NOT have raised — and the segment object was mutated.
        assert segment.is_empty is True
        assert segment.status == AnnotationSegmentStatus.ANNOTATED
        assert result.status == AnnotationSegmentStatus.ANNOTATED.value


# ---------------------------------------------------------------------------
# Tests: species palette validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpeciesPaletteRequiresValidTaxon:
    """Adding a non-existent taxon to the palette must raise 404."""

    async def test_invalid_taxon_raises_404(self) -> None:
        set_repo = MagicMock()
        segment_repo = MagicMock()

        # AnnotationSet exists (so _require_set passes).
        anno_set_mock = MagicMock()
        anno_set_mock.id = uuid4()
        set_repo.get_by_id = AsyncMock(return_value=anno_set_mock)
        set_repo.db = MagicMock()

        # Taxon does NOT exist.
        taxon_result = MagicMock()
        taxon_result.scalar_one_or_none = MagicMock(return_value=None)
        set_repo.db.execute = AsyncMock(return_value=taxon_result)

        set_service = AnnotationSetService(set_repo, segment_repo)

        with pytest.raises(HTTPException) as exc_info:
            await set_service.add_palette(
                anno_set_mock.id,
                PaletteItemCreate(species_id=uuid4()),
            )
        assert exc_info.value.status_code == 404
