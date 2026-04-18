"""Service layer for :class:`AnnotationSegment` operations.

Enforces invariants that the repository layer deliberately does not touch:

- ``is_empty`` can only be set to ``True`` when the segment has zero child
  ``TimeRangeAnnotation`` rows.
- Creating a ``TimeRangeAnnotation`` on a segment flips ``is_empty`` to
  ``False`` automatically.
- Transitioning a segment to ``annotated`` requires either at least one
  ``TimeRangeAnnotation`` or ``is_empty=True`` so recall denominators stay
  meaningful.
- Every status transition triggers a parent-set recomputation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_set import AnnotationSegment, TimeRangeAnnotation
from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.models.note import Note
from echoroo.models.taxon import Taxon
from echoroo.repositories.annotation_set import (
    AnnotationSegmentRepository,
    TimeRangeAnnotationRepository,
)
from echoroo.schemas.annotation_set import (
    AnnotationNoteCreate,
    AnnotationNoteResponse,
    AnnotationSegmentDetailResponse,
    AnnotationSegmentStatusUpdate,
    TimeRangeAnnotationCreate,
    TimeRangeAnnotationResponse,
)
from echoroo.services.annotation_set import AnnotationSetService

logger = logging.getLogger(__name__)


class AnnotationSegmentService:
    """Business logic for segment detail, transitions, annotations and notes."""

    def __init__(
        self,
        segment_repo: AnnotationSegmentRepository,
        annotation_repo: TimeRangeAnnotationRepository,
        set_service: AnnotationSetService,
    ) -> None:
        self.segment_repo = segment_repo
        self.annotation_repo = annotation_repo
        self.set_service = set_service

    @property
    def _db(self) -> AsyncSession:
        return self.segment_repo.db

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _require_segment(
        self, segment_id: UUID, *, with_children: bool = False,
    ) -> AnnotationSegment:
        if with_children:
            segment = await self.segment_repo.get_with_annotations_and_notes(segment_id)
        else:
            segment = await self.segment_repo.get_by_id(segment_id)
        if segment is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Annotation segment not found",
            )
        return segment

    async def _require_taxon(self, taxon_id: UUID) -> Taxon:
        result = await self._db.execute(select(Taxon).where(Taxon.id == taxon_id))
        taxon = result.scalar_one_or_none()
        if taxon is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Taxon not found: {taxon_id}",
            )
        return taxon

    async def _note_to_response(self, note: Note) -> AnnotationNoteResponse:
        return AnnotationNoteResponse(
            id=note.id,
            content=note.content,
            is_issue=note.is_issue,
            is_review=note.is_review,
            created_by_id=note.created_by_id,
            created_at=note.created_at,
        )

    async def _annotation_to_response(
        self, row: TimeRangeAnnotation,
    ) -> TimeRangeAnnotationResponse:
        taxon_result = await self._db.execute(
            select(Taxon).where(Taxon.id == row.taxon_id)
        )
        taxon = taxon_result.scalar_one_or_none()
        note_count = await self.annotation_repo.count_notes(row.id)
        return TimeRangeAnnotationResponse(
            id=row.id,
            segment_id=row.segment_id,
            start_time_sec=row.start_time_sec,
            end_time_sec=row.end_time_sec,
            species_id=row.taxon_id,
            species_scientific_name=taxon.scientific_name if taxon else None,
            species_common_name=None,
            confidence=row.confidence,
            created_by_id=row.created_by_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
            note_count=note_count,
        )

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------

    async def get_detail(self, segment_id: UUID) -> AnnotationSegmentDetailResponse:
        segment = await self._require_segment(segment_id, with_children=True)
        # Load recording filename + duration for display
        from echoroo.models.recording import Recording  # noqa: PLC0415

        rec_result = await self._db.execute(
            select(Recording.filename, Recording.duration, Recording.time_expansion)
            .where(Recording.id == segment.recording_id)
        )
        rec_row = rec_result.first()
        recording_filename = rec_row[0] if rec_row is not None else None
        recording_duration = (
            float(rec_row[1] or 0.0) * float(rec_row[2] or 1.0)
            if rec_row is not None
            else None
        )

        # Batch-load taxon names for the annotations.
        taxon_ids = {a.taxon_id for a in segment.annotations}
        name_map: dict[UUID, str] = {}
        if taxon_ids:
            taxon_stmt = select(Taxon.id, Taxon.scientific_name).where(
                Taxon.id.in_(taxon_ids)
            )
            for tid, sci in (await self._db.execute(taxon_stmt)).all():
                name_map[tid] = sci

        annotations = [
            TimeRangeAnnotationResponse(
                id=a.id,
                segment_id=a.segment_id,
                start_time_sec=a.start_time_sec,
                end_time_sec=a.end_time_sec,
                species_id=a.taxon_id,
                species_scientific_name=name_map.get(a.taxon_id),
                species_common_name=None,
                confidence=a.confidence,
                created_by_id=a.created_by_id,
                created_at=a.created_at,
                updated_at=a.updated_at,
                note_count=0,
            )
            for a in sorted(segment.annotations, key=lambda x: x.start_time_sec)
        ]

        notes = [await self._note_to_response(n) for n in segment.notes]

        return AnnotationSegmentDetailResponse(
            id=segment.id,
            annotation_set_id=segment.annotation_set_id,
            recording_id=segment.recording_id,
            recording_filename=recording_filename,
            recording_duration_sec=recording_duration,
            start_time_sec=segment.start_time_sec,
            end_time_sec=segment.end_time_sec,
            is_empty=segment.is_empty,
            status=segment.status.value,
            annotated_by_id=segment.annotated_by_id,
            annotated_at=segment.annotated_at,
            annotations=annotations,
            notes=notes,
            created_at=segment.created_at,
            updated_at=segment.updated_at,
        )

    # ------------------------------------------------------------------
    # Status / empty updates
    # ------------------------------------------------------------------

    async def update(
        self,
        segment_id: UUID,
        *,
        user_id: UUID,
        request: AnnotationSegmentStatusUpdate,
    ) -> AnnotationSegmentDetailResponse:
        segment = await self._require_segment(segment_id, with_children=True)

        # Guard: is_empty=True requires zero annotations.
        if request.is_empty is True and len(segment.annotations) > 0:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot mark segment as empty while TimeRangeAnnotations "
                    "exist. Delete them first."
                ),
            )

        if request.is_empty is not None:
            segment.is_empty = request.is_empty

        if request.status is not None:
            new_status = AnnotationSegmentStatus(request.status)
            # Guard: transitioning to ANNOTATED requires either an existing
            # annotation or an explicit is_empty marker.
            if new_status == AnnotationSegmentStatus.ANNOTATED:
                will_be_empty = (
                    request.is_empty if request.is_empty is not None else segment.is_empty
                )
                if not will_be_empty and len(segment.annotations) == 0:
                    raise HTTPException(
                        status_code=http_status.HTTP_409_CONFLICT,
                        detail=(
                            "Segment has no annotations; mark is_empty=true before "
                            "finalizing as annotated."
                        ),
                    )
                segment.annotated_at = datetime.now(UTC)
                segment.annotated_by_id = user_id
            elif new_status == AnnotationSegmentStatus.UNANNOTATED:
                segment.annotated_at = None
                segment.annotated_by_id = None
            segment.status = new_status

        await self._db.flush()
        await self._db.refresh(segment)

        # Recompute parent AnnotationSet status.
        await self.set_service.recompute_status(segment.annotation_set_id)

        return await self.get_detail(segment_id)

    # ------------------------------------------------------------------
    # Annotation creation
    # ------------------------------------------------------------------

    async def create_annotation(
        self,
        segment_id: UUID,
        *,
        user_id: UUID,
        request: TimeRangeAnnotationCreate,
    ) -> TimeRangeAnnotationResponse:
        segment = await self._require_segment(segment_id)

        # Validate time range against segment duration.
        segment_duration = float(segment.end_time_sec - segment.start_time_sec)
        if request.end_time_sec > segment_duration + 1e-6:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"end_time_sec ({request.end_time_sec}) exceeds segment "
                    f"duration ({segment_duration:.3f}s)."
                ),
            )

        await self._require_taxon(request.species_id)

        created = await self.annotation_repo.create(
            segment_id=segment_id,
            start_time_sec=request.start_time_sec,
            end_time_sec=request.end_time_sec,
            taxon_id=request.species_id,
            created_by_id=user_id,
            confidence=request.confidence,
        )

        # Invariant: creating an annotation flips is_empty to False.
        if segment.is_empty:
            segment.is_empty = False
            await self._db.flush()

        return await self._annotation_to_response(created)

    # ------------------------------------------------------------------
    # Note attachment
    # ------------------------------------------------------------------

    async def create_note(
        self,
        segment_id: UUID,
        *,
        user_id: UUID,
        request: AnnotationNoteCreate,
    ) -> AnnotationNoteResponse:
        await self._require_segment(segment_id)
        note = Note(
            created_by_id=user_id,
            content=request.content,
            is_issue=request.is_issue,
            is_review=False,
        )
        self._db.add(note)
        await self._db.flush()
        await self._db.refresh(note)
        await self.segment_repo.attach_note(segment_id, note.id)
        return await self._note_to_response(note)
