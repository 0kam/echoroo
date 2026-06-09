"""Repositories for the ground-truth annotation feature (spec 003-annotation).

Three repositories are provided:

- ``AnnotationSetRepository``: CRUD for ``annotation_sets`` plus palette
  management (add/remove taxa, list).
- ``AnnotationSegmentRepository``: CRUD for ``annotation_segments`` including
  bulk insert (used by the sampling Celery task) and note attachment.
- ``TimeRangeAnnotationRepository``: CRUD for ``time_range_annotations``
  including note attachment.

These are thin persistence wrappers. Cross-entity invariants (e.g. flipping
``is_empty`` when a TimeRangeAnnotation is created, or recomputing the parent
AnnotationSet ``status``) are intentionally NOT enforced here — they belong
in the service layer implemented in the next phase (A2/A3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, select
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_set import (
    AnnotationSegment,
    AnnotationSet,
    TimeRangeAnnotation,
    annotation_segment_notes,
    annotation_set_species_palette,
    time_range_annotation_notes,
)
from echoroo.models.enums import AnnotationSegmentStatus, AnnotationSetStatus
from echoroo.models.note import Note
from echoroo.models.taxon import Taxon
from echoroo.repositories.base import BaseRepository

# ---------------------------------------------------------------------------
# AnnotationSet
# ---------------------------------------------------------------------------


class AnnotationSetRepository(BaseRepository[AnnotationSet]):
    """Repository for ``AnnotationSet`` and its species palette."""

    model = AnnotationSet

    async def create(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        created_by_id: UUID,
        name: str,
        num_segments: int,
        segment_mode: str = "fixed",
        segment_length_sec: int | None = None,
        filter_date_range: dict[str, Any] | None = None,
        filter_time_of_day_range: dict[str, Any] | None = None,
    ) -> AnnotationSet:
        """Create a new AnnotationSet with status ``sampling``.

        Args:
            project_id: Owning project ID.
            dataset_id: Source dataset ID.
            created_by_id: Creator user ID.
            name: Display name (unique within project).
            num_segments: Target segment count (>= 1). In ``whole_recording``
                mode this is the maximum number of recordings to sample.
            segment_mode: ``'fixed'`` (default) or ``'whole_recording'``.
            segment_length_sec: Length of each sampled segment (>= 10).
                Required for ``fixed`` mode; ``None`` for ``whole_recording``.
            filter_date_range: Optional JSONB date filter payload.
            filter_time_of_day_range: Optional JSONB time-of-day filter payload.

        Returns:
            The newly created ``AnnotationSet`` with ``status = sampling``.
        """
        set_ = AnnotationSet(
            project_id=project_id,
            dataset_id=dataset_id,
            created_by_id=created_by_id,
            name=name,
            segment_mode=segment_mode,
            segment_length_sec=segment_length_sec,
            num_segments=num_segments,
            filter_date_range=filter_date_range,
            filter_time_of_day_range=filter_time_of_day_range,
            status=AnnotationSetStatus.SAMPLING,
        )
        self.db.add(set_)
        await self.db.flush()
        await self.db.refresh(set_)
        return set_

    async def get_by_id(self, set_id: UUID) -> AnnotationSet | None:
        """Fetch an AnnotationSet by primary key (no relationships loaded)."""
        result = await self.db.execute(
            select(AnnotationSet).where(AnnotationSet.id == set_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        *,
        dataset_id: UUID | None = None,
        status: AnnotationSetStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AnnotationSet], int]:
        """List annotation sets for a project (newest first) with a total count.

        Args:
            project_id: Owning project ID.
            limit: Maximum items to return.
            offset: Number of items to skip.

        Returns:
            Tuple of ``(items, total)``.
        """
        conditions = [AnnotationSet.project_id == project_id]
        if dataset_id is not None:
            conditions.append(AnnotationSet.dataset_id == dataset_id)
        if status is not None:
            conditions.append(AnnotationSet.status == status)

        total_stmt = (
            select(func.count())
            .select_from(AnnotationSet)
            .where(*conditions)
        )
        total = (await self.db.execute(total_stmt)).scalar_one()

        stmt = (
            select(AnnotationSet)
            .where(*conditions)
            .order_by(AnnotationSet.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, int(total)

    async def list_palette_with_taxa(
        self, set_id: UUID
    ) -> list[tuple[Taxon, int]]:
        """Return palette entries joined against :class:`Taxon` for response
        payload construction.

        Returns:
            List of ``(Taxon, position)`` tuples ordered by ``position`` asc.
        """
        stmt = (
            select(Taxon, annotation_set_species_palette.c.position)
            .join(
                annotation_set_species_palette,
                annotation_set_species_palette.c.taxon_id == Taxon.id,
            )
            .where(
                annotation_set_species_palette.c.annotation_set_id == set_id,
            )
            .order_by(
                annotation_set_species_palette.c.position.asc(),
                Taxon.scientific_name.asc(),
            )
        )
        result = await self.db.execute(stmt)
        return [(row[0], int(row[1])) for row in result.all()]

    async def update_fields(
        self,
        set_id: UUID,
        *,
        name: str | None = None,
        status: AnnotationSetStatus | None = None,
        sampling_warning: str | None = None,
    ) -> AnnotationSet | None:
        """Partially update an AnnotationSet row.

        Args:
            set_id: AnnotationSet ID.
            name: New display name (optional).
            status: New lifecycle status (optional).
            sampling_warning: New sampling warning text (optional; pass empty
                string to clear).

        Returns:
            The updated row, or None if not found.
        """
        set_ = await self.get_by_id(set_id)
        if set_ is None:
            return None

        if name is not None:
            set_.name = name
        if status is not None:
            set_.status = status
        if sampling_warning is not None:
            set_.sampling_warning = sampling_warning or None

        await self.db.flush()
        await self.db.refresh(set_)
        return set_

    # ------------------------------------------------------------------
    # Palette management
    # ------------------------------------------------------------------

    async def add_palette_entry(
        self,
        set_id: UUID,
        taxon_id: UUID,
        position: int = 0,
    ) -> None:
        """Add a taxon to the set's species palette.

        Idempotent on the (set_id, taxon_id) primary key — re-insertion is a
        no-op after catching the uniqueness error in the service layer.

        Args:
            set_id: AnnotationSet ID.
            taxon_id: Taxon ID to add.
            position: Ordering hint for palette display.
        """
        stmt = insert(annotation_set_species_palette).values(
            annotation_set_id=set_id,
            taxon_id=taxon_id,
            position=position,
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def remove_palette_entry(self, set_id: UUID, taxon_id: UUID) -> None:
        """Remove a taxon from the set's species palette.

        Does NOT cascade to existing ``TimeRangeAnnotation`` rows that already
        reference the taxon; the palette is a UI filter only.
        """
        stmt = delete(annotation_set_species_palette).where(
            and_(
                annotation_set_species_palette.c.annotation_set_id == set_id,
                annotation_set_species_palette.c.taxon_id == taxon_id,
            )
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def list_palette(self, set_id: UUID) -> list[tuple[UUID, int]]:
        """List palette entries for a set as ``(taxon_id, position)`` tuples."""
        stmt = (
            select(
                annotation_set_species_palette.c.taxon_id,
                annotation_set_species_palette.c.position,
            )
            .where(annotation_set_species_palette.c.annotation_set_id == set_id)
            .order_by(
                annotation_set_species_palette.c.position.asc(),
                annotation_set_species_palette.c.taxon_id.asc(),
            )
        )
        result = await self.db.execute(stmt)
        return [(row.taxon_id, row.position) for row in result]


# ---------------------------------------------------------------------------
# AnnotationSegment
# ---------------------------------------------------------------------------


class AnnotationSegmentRepository(BaseRepository[AnnotationSegment]):
    """Repository for ``AnnotationSegment`` CRUD and note attachment."""

    model = AnnotationSegment

    async def bulk_create(
        self,
        annotation_set_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[AnnotationSegment]:
        """Bulk-insert AnnotationSegment rows for a sampling job.

        Each row dict must contain:
            - ``recording_id`` (UUID)
            - ``start_time_sec`` (float)
            - ``end_time_sec`` (float)

        ``is_empty`` defaults to False and ``status`` defaults to
        ``unannotated``.

        Args:
            annotation_set_id: Owning AnnotationSet.
            rows: List of segment-attribute dicts.

        Returns:
            The created ``AnnotationSegment`` instances in input order.
        """
        instances = [
            AnnotationSegment(
                annotation_set_id=annotation_set_id,
                recording_id=row["recording_id"],
                start_time_sec=float(row["start_time_sec"]),
                end_time_sec=float(row["end_time_sec"]),
            )
            for row in rows
        ]
        self.db.add_all(instances)
        await self.db.flush()
        return instances

    async def get_by_id(self, segment_id: UUID) -> AnnotationSegment | None:
        """Fetch a segment by primary key (no relationships loaded)."""
        result = await self.db.execute(
            select(AnnotationSegment).where(AnnotationSegment.id == segment_id)
        )
        return result.scalar_one_or_none()

    async def get_with_annotations(
        self, segment_id: UUID
    ) -> AnnotationSegment | None:
        """Fetch a segment with its child ``TimeRangeAnnotation`` rows loaded."""
        stmt = (
            select(AnnotationSegment)
            .where(AnnotationSegment.id == segment_id)
            .options(selectinload(AnnotationSegment.annotations))
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_with_annotations_and_notes(
        self, segment_id: UUID
    ) -> AnnotationSegment | None:
        """Fetch a segment with annotations and attached notes eagerly loaded."""
        stmt = (
            select(AnnotationSegment)
            .where(AnnotationSegment.id == segment_id)
            .options(
                selectinload(AnnotationSegment.annotations),
                selectinload(AnnotationSegment.notes),
            )
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_by_set(
        self,
        annotation_set_id: UUID,
        *,
        status: AnnotationSegmentStatus | None = None,
        is_empty: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[AnnotationSegment], int]:
        """List segments for a set, optionally filtered by status.

        Args:
            annotation_set_id: Owning set.
            status: Optional status filter.
            limit: Max items.
            offset: Items to skip.

        Returns:
            Tuple of ``(items, total)``.
        """
        base = select(AnnotationSegment).where(
            AnnotationSegment.annotation_set_id == annotation_set_id,
        )
        if status is not None:
            base = base.where(AnnotationSegment.status == status)
        if is_empty is not None:
            base = base.where(AnnotationSegment.is_empty == is_empty)

        total_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.db.execute(total_stmt)).scalar_one()

        stmt = (
            base.order_by(AnnotationSegment.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, int(total)

    async def count_by_status(
        self, annotation_set_id: UUID
    ) -> dict[AnnotationSegmentStatus, int]:
        """Return a per-status segment count for the given set.

        Useful for recomputing the parent AnnotationSet's lifecycle status.

        Args:
            annotation_set_id: Owning set.

        Returns:
            Dict keyed by :class:`AnnotationSegmentStatus` with zero-filled counts
            for statuses that are absent.
        """
        stmt = (
            select(AnnotationSegment.status, func.count())
            .where(AnnotationSegment.annotation_set_id == annotation_set_id)
            .group_by(AnnotationSegment.status)
        )
        result = await self.db.execute(stmt)
        counts: dict[AnnotationSegmentStatus, int] = dict.fromkeys(AnnotationSegmentStatus, 0)
        for status, count in result:
            counts[status] = int(count)
        return counts

    async def update_status(
        self,
        segment_id: UUID,
        *,
        status: AnnotationSegmentStatus | None = None,
        is_empty: bool | None = None,
        annotated_by_id: UUID | None = None,
        clear_annotated_by: bool = False,
    ) -> AnnotationSegment | None:
        """Update the lifecycle fields of a segment.

        Args:
            segment_id: Segment ID.
            status: New status (optional).
            is_empty: New empty flag (optional).
            annotated_by_id: User finalizing the segment; when supplied
                alongside ``status=annotated`` the service layer should also
                set ``annotated_at = now()``.
            clear_annotated_by: When True, resets both ``annotated_by_id`` and
                ``annotated_at`` to None (used when a segment transitions back
                from ``annotated`` to ``unannotated``).

        Returns:
            The updated segment, or None if not found.
        """
        segment = await self.get_by_id(segment_id)
        if segment is None:
            return None

        if status is not None:
            segment.status = status
            if status == AnnotationSegmentStatus.ANNOTATED:
                segment.annotated_at = datetime.now(UTC)
                if annotated_by_id is not None:
                    segment.annotated_by_id = annotated_by_id

        if is_empty is not None:
            segment.is_empty = is_empty

        if clear_annotated_by:
            segment.annotated_by_id = None
            segment.annotated_at = None

        await self.db.flush()
        await self.db.refresh(segment)
        return segment

    # ------------------------------------------------------------------
    # Note attachment
    # ------------------------------------------------------------------

    async def attach_note(self, segment_id: UUID, note_id: UUID) -> None:
        """Link an existing Note to a segment via ``annotation_segment_notes``."""
        stmt = insert(annotation_segment_notes).values(
            segment_id=segment_id,
            note_id=note_id,
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def list_notes(self, segment_id: UUID) -> list[Note]:
        """Return all notes attached to a segment, oldest first."""
        stmt = (
            select(Note)
            .join(
                annotation_segment_notes,
                annotation_segment_notes.c.note_id == Note.id,
            )
            .where(annotation_segment_notes.c.segment_id == segment_id)
            .order_by(Note.created_at.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# TimeRangeAnnotation
# ---------------------------------------------------------------------------


class TimeRangeAnnotationRepository(BaseRepository[TimeRangeAnnotation]):
    """Repository for ``TimeRangeAnnotation`` CRUD and note attachment."""

    model = TimeRangeAnnotation

    async def create(
        self,
        *,
        segment_id: UUID,
        start_time_sec: float,
        end_time_sec: float,
        taxon_id: UUID,
        created_by_id: UUID,
        confidence: float | None = None,
    ) -> TimeRangeAnnotation:
        """Create a new TimeRangeAnnotation row.

        The caller (service layer) is responsible for flipping the parent
        segment's ``is_empty`` flag to False.
        """
        row = TimeRangeAnnotation(
            segment_id=segment_id,
            start_time_sec=start_time_sec,
            end_time_sec=end_time_sec,
            taxon_id=taxon_id,
            created_by_id=created_by_id,
            confidence=confidence,
        )
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def get_by_id(
        self, annotation_id: UUID
    ) -> TimeRangeAnnotation | None:
        """Fetch a TimeRangeAnnotation by primary key."""
        result = await self.db.execute(
            select(TimeRangeAnnotation).where(
                TimeRangeAnnotation.id == annotation_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_segment(
        self, segment_id: UUID
    ) -> list[TimeRangeAnnotation]:
        """Return all TimeRangeAnnotations for a segment, ordered by start."""
        stmt = (
            select(TimeRangeAnnotation)
            .where(TimeRangeAnnotation.segment_id == segment_id)
            .order_by(TimeRangeAnnotation.start_time_sec.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def update_fields(
        self,
        annotation_id: UUID,
        *,
        start_time_sec: float | None = None,
        end_time_sec: float | None = None,
        taxon_id: UUID | None = None,
        confidence: float | None = None,
    ) -> TimeRangeAnnotation | None:
        """Partially update a TimeRangeAnnotation.

        ``confidence`` cannot be cleared via this method; use a dedicated
        service-level method if that becomes a product requirement.
        """
        row = await self.get_by_id(annotation_id)
        if row is None:
            return None

        if start_time_sec is not None:
            row.start_time_sec = start_time_sec
        if end_time_sec is not None:
            row.end_time_sec = end_time_sec
        if taxon_id is not None:
            row.taxon_id = taxon_id
        if confidence is not None:
            row.confidence = confidence

        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def count_by_segment(self, segment_id: UUID) -> int:
        """Return the number of TimeRangeAnnotations attached to a segment."""
        stmt = select(func.count()).select_from(TimeRangeAnnotation).where(
            TimeRangeAnnotation.segment_id == segment_id
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def count_notes(self, annotation_id: UUID) -> int:
        """Return the number of notes attached to a single TimeRangeAnnotation."""
        stmt = (
            select(func.count())
            .select_from(time_range_annotation_notes)
            .where(time_range_annotation_notes.c.annotation_id == annotation_id)
        )
        return int((await self.db.execute(stmt)).scalar_one())

    # ------------------------------------------------------------------
    # Note attachment
    # ------------------------------------------------------------------

    async def attach_note(self, annotation_id: UUID, note_id: UUID) -> None:
        """Link an existing Note to an annotation via the secondary table."""
        stmt = insert(time_range_annotation_notes).values(
            annotation_id=annotation_id,
            note_id=note_id,
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def list_notes(self, annotation_id: UUID) -> list[Note]:
        """Return all notes attached to a TimeRangeAnnotation, oldest first."""
        stmt = (
            select(Note)
            .join(
                time_range_annotation_notes,
                time_range_annotation_notes.c.note_id == Note.id,
            )
            .where(time_range_annotation_notes.c.annotation_id == annotation_id)
            .order_by(Note.created_at.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())


__all__ = [
    "AnnotationSetRepository",
    "AnnotationSegmentRepository",
    "TimeRangeAnnotationRepository",
]
