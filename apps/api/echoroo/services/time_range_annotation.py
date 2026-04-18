"""Service layer for :class:`TimeRangeAnnotation` CRUD.

Create is handled through :class:`AnnotationSegmentService`. This module
covers update, delete, and note attachment with the same invariants
enforced around the parent segment (``is_empty`` flip-flops, parent-set
status recomputation).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_set import AnnotationSegment, TimeRangeAnnotation
from echoroo.models.note import Note
from echoroo.models.taxon import Taxon
from echoroo.repositories.annotation_set import (
    AnnotationSegmentRepository,
    TimeRangeAnnotationRepository,
)
from echoroo.schemas.annotation_set import (
    AnnotationNoteCreate,
    AnnotationNoteResponse,
    TimeRangeAnnotationResponse,
    TimeRangeAnnotationUpdate,
)
from echoroo.services.annotation_set import AnnotationSetService

logger = logging.getLogger(__name__)


class TimeRangeAnnotationService:
    """Business logic for ``TimeRangeAnnotation`` CRUD and notes."""

    def __init__(
        self,
        annotation_repo: TimeRangeAnnotationRepository,
        segment_repo: AnnotationSegmentRepository,
        set_service: AnnotationSetService,
    ) -> None:
        self.annotation_repo = annotation_repo
        self.segment_repo = segment_repo
        self.set_service = set_service

    @property
    def _db(self) -> AsyncSession:
        return self.annotation_repo.db

    async def _require_annotation(
        self, annotation_id: UUID,
    ) -> TimeRangeAnnotation:
        row = await self.annotation_repo.get_by_id(annotation_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="TimeRangeAnnotation not found",
            )
        return row

    async def _require_segment(self, segment_id: UUID) -> AnnotationSegment:
        segment = await self.segment_repo.get_by_id(segment_id)
        if segment is None:
            # Internal consistency error — orphaned FK should never happen.
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Orphaned TimeRangeAnnotation (segment not found).",
            )
        return segment

    async def _to_response(
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
    # Update
    # ------------------------------------------------------------------

    async def update(
        self,
        annotation_id: UUID,
        request: TimeRangeAnnotationUpdate,
    ) -> TimeRangeAnnotationResponse:
        row = await self._require_annotation(annotation_id)
        segment = await self._require_segment(row.segment_id)
        segment_duration = float(segment.end_time_sec - segment.start_time_sec)

        new_start = (
            request.start_time_sec
            if request.start_time_sec is not None
            else row.start_time_sec
        )
        new_end = (
            request.end_time_sec
            if request.end_time_sec is not None
            else row.end_time_sec
        )
        if new_end <= new_start:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="end_time_sec must be greater than start_time_sec.",
            )
        if new_end > segment_duration + 1e-6:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"end_time_sec ({new_end}) exceeds segment duration "
                    f"({segment_duration:.3f}s)."
                ),
            )

        if request.species_id is not None:
            # Validate taxon exists when changing species.
            taxon_result = await self._db.execute(
                select(Taxon.id).where(Taxon.id == request.species_id)
            )
            if taxon_result.scalar_one_or_none() is None:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND,
                    detail=f"Taxon not found: {request.species_id}",
                )

        updated = await self.annotation_repo.update_fields(
            annotation_id,
            start_time_sec=request.start_time_sec,
            end_time_sec=request.end_time_sec,
            taxon_id=request.species_id,
            confidence=request.confidence,
        )
        assert updated is not None  # just fetched
        return await self._to_response(updated)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, annotation_id: UUID) -> None:
        row = await self._require_annotation(annotation_id)
        segment_id = row.segment_id
        set_id: UUID | None = None
        segment = await self.segment_repo.get_by_id(segment_id)
        if segment is not None:
            set_id = segment.annotation_set_id

        await self.annotation_repo.delete(annotation_id)

        # If the parent segment has no annotations left and is not marked
        # empty, we DO NOT automatically flip it — the annotator must make an
        # explicit is_empty decision. But we still recompute the set status
        # in case the cascade affected completion.
        if set_id is not None:
            await self.set_service.recompute_status(set_id)

    # ------------------------------------------------------------------
    # Notes
    # ------------------------------------------------------------------

    async def create_note(
        self,
        annotation_id: UUID,
        *,
        user_id: UUID,
        request: AnnotationNoteCreate,
    ) -> AnnotationNoteResponse:
        await self._require_annotation(annotation_id)
        note = Note(
            created_by_id=user_id,
            content=request.content,
            is_issue=request.is_issue,
            is_review=False,
        )
        self._db.add(note)
        await self._db.flush()
        await self._db.refresh(note)
        await self.annotation_repo.attach_note(annotation_id, note.id)
        return AnnotationNoteResponse(
            id=note.id,
            content=note.content,
            is_issue=note.is_issue,
            is_review=note.is_review,
            created_by_id=note.created_by_id,
            created_at=note.created_at,
        )
