"""Annotation repository for detection review database operations.

The rich-shape methods (``list_annotations`` / ``species_summary`` /
``temporal_summary`` / ``create`` / ``create_batch`` / ``update`` /
``delete_by_detection_run``) operate on the :class:`RecordingAnnotation` ORM
whose ``__tablename__`` is ``recording_annotations_DEFERRED``. That table
**exists** and is live at runtime (created by migration
``0011_recording_annotations_placeholder`` and actively written/read by the ML
classifier, search-session, and detection grid). The ``_DEFERRED`` suffix is a
transitional placeholder name pending a future rename to
``recording_annotations``; it does not imply the table is absent.

The two methods used by the Phase 13 vote API path (:meth:`exists` and
:meth:`exists_in_project`) are built on the minimal
:class:`echoroo.models.annotation.Annotation` shape (imported here as
``MinimalAnnotation``): they reach the project via the parent ``Detection``
row (``Annotation.detection_id -> Detection.project_id``) and probe the
``annotations`` table. The two distinct ORM classes — ``RecordingAnnotation``
(rich shape, ``recording_annotations_DEFERRED``) and ``MinimalAnnotation``
(minimal shape, ``annotations``) — are kept visually separate so each query
clearly targets the right table.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, TypedDict
from uuid import UUID

from sqlalchemy import Integer, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.expression import cast

from echoroo.models.annotation import Annotation as MinimalAnnotation
from echoroo.models.detection import Detection
from echoroo.models.enums import DetectionStatus
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.tag import Tag
from echoroo.repositories.base import BaseRepository

if TYPE_CHECKING:
    pass


class TemporalSummaryRow(TypedDict):
    """Typed row for temporal summary query results."""

    tag_id: UUID
    date: date
    hour: int
    count: int


class SpeciesSummaryRow(TypedDict):
    """Typed row for species summary query results."""

    tag_id: UUID | None
    tag_name: str
    scientific_name: str | None
    common_name: str | None
    taxon_id: UUID | None
    total_count: int
    avg_confidence: float | None
    unreviewed_count: int
    confirmed_count: int
    rejected_count: int


class AnnotationRepository(BaseRepository[RecordingAnnotation]):
    """Repository for RecordingAnnotation entity operations.

    Bound to :class:`RecordingAnnotation` (the live ``recording_annotations_DEFERRED``
    table) for the rich-shape methods. The two methods used by the Phase 13
    vote API path (:meth:`exists` / :meth:`exists_in_project`) query the
    minimal :class:`MinimalAnnotation` shape instead.
    """

    model = RecordingAnnotation

    async def get_by_id(self, annotation_id: UUID) -> RecordingAnnotation | None:
        """Get a rich-shape recording annotation with eager relationships."""
        result = await self.db.execute(
            select(RecordingAnnotation)
            .where(RecordingAnnotation.id == annotation_id)
            .options(
                selectinload(RecordingAnnotation.recording),
                selectinload(RecordingAnnotation.tag),
                selectinload(RecordingAnnotation.detection_run),
                selectinload(RecordingAnnotation.reviewed_by),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_in_project(
        self, annotation_id: UUID, project_id: UUID
    ) -> RecordingAnnotation | None:
        """Get a rich-shape recording annotation scoped to a project.

        Loads eager relationships (``recording`` / ``tag`` / ``detection_run`` /
        ``reviewed_by``) on the :class:`RecordingAnnotation` shape, scoping via
        ``RecordingAnnotation.recording_id -> Recording.dataset_id ->
        Dataset.project_id``. For a lightweight project-scoped existence probe
        used by the vote API, see :meth:`exists_in_project`.
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        result = await self.db.execute(
            select(RecordingAnnotation)
            .join(Recording, RecordingAnnotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(RecordingAnnotation.id == annotation_id)
            .where(Dataset.project_id == project_id)
            .options(
                selectinload(RecordingAnnotation.recording),
                selectinload(RecordingAnnotation.tag),
                selectinload(RecordingAnnotation.detection_run),
                selectinload(RecordingAnnotation.reviewed_by),
            )
        )
        return result.scalar_one_or_none()

    async def exists(self, annotation_id: UUID) -> bool:
        """Lightweight existence probe on the minimal :class:`MinimalAnnotation` shape.

        Probes the ``annotations`` table for "annotation exists" gating
        without reading any rich-shape columns. Callers that need the rich
        recording-level shape use :meth:`get_by_id` (which queries the
        ``recording_annotations_DEFERRED`` table) instead.

        Args:
            annotation_id: Annotation's UUID.

        Returns:
            ``True`` when the annotation row exists in the minimal
            ``annotations`` table.
        """
        result = await self.db.execute(
            select(MinimalAnnotation.id).where(MinimalAnnotation.id == annotation_id)
        )
        return result.first() is not None

    async def exists_in_project(
        self, annotation_id: UUID, project_id: UUID
    ) -> bool:
        """Return ``True`` when an annotation belongs to ``project_id``.

        Built on the minimal :class:`MinimalAnnotation` shape. The integrity
        chain is ``Annotation.detection_id -> Detection.project_id`` (FR-005);
        ``Detection`` is the canonical recording- and project-scoped row.
        (The rich-shape :class:`RecordingAnnotation` reaches the project via
        ``recording_id -> Recording -> Dataset`` instead — see
        :meth:`get_by_id_in_project`.)

        Used as a BOLA / IDOR guard before the vote API delegates to
        :meth:`AnnotationVoteService.cast_vote` /
        :meth:`get_vote_summary` / :meth:`delete_vote`.

        Args:
            annotation_id: Annotation's UUID.
            project_id: Project UUID the annotation must belong to.

        Returns:
            ``True`` when the annotation exists in the given project,
            ``False`` otherwise (also for unknown annotations).
        """
        result = await self.db.execute(
            select(MinimalAnnotation.id)
            .join(Detection, MinimalAnnotation.detection_id == Detection.id)
            .where(MinimalAnnotation.id == annotation_id)
            .where(Detection.project_id == project_id)
        )
        return result.first() is not None

    async def list_annotations(
        self,
        project_id: UUID,
        tag_id: UUID | None = None,
        status: DetectionStatus | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        dataset_id: UUID | None = None,
        recording_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[RecordingAnnotation], int]:
        """List recording annotations using rich-shape filters.

        Queries the live :class:`RecordingAnnotation` table
        (``recording_annotations_DEFERRED``).
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        base_query = (
            select(RecordingAnnotation)
            .join(Recording, RecordingAnnotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
        )

        count_query = (
            select(func.count())
            .select_from(RecordingAnnotation)
            .join(Recording, RecordingAnnotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
        )

        if tag_id is not None:
            base_query = base_query.where(RecordingAnnotation.tag_id == tag_id)
            count_query = count_query.where(RecordingAnnotation.tag_id == tag_id)

        if status is not None:
            base_query = base_query.where(RecordingAnnotation.status == status)
            count_query = count_query.where(RecordingAnnotation.status == status)

        if confidence_min is not None:
            base_query = base_query.where(RecordingAnnotation.confidence >= confidence_min)
            count_query = count_query.where(RecordingAnnotation.confidence >= confidence_min)

        if confidence_max is not None:
            base_query = base_query.where(RecordingAnnotation.confidence <= confidence_max)
            count_query = count_query.where(RecordingAnnotation.confidence <= confidence_max)

        if dataset_id is not None:
            base_query = base_query.where(Recording.dataset_id == dataset_id)
            count_query = count_query.where(Recording.dataset_id == dataset_id)

        if recording_id is not None:
            base_query = base_query.where(RecordingAnnotation.recording_id == recording_id)
            count_query = count_query.where(RecordingAnnotation.recording_id == recording_id)

        if detection_run_id is not None:
            base_query = base_query.where(RecordingAnnotation.detection_run_id == detection_run_id)
            count_query = count_query.where(
                RecordingAnnotation.detection_run_id == detection_run_id
            )

        count_result = await self.db.execute(count_query)
        total: int = count_result.scalar_one()

        offset = (page - 1) * page_size
        result = await self.db.execute(
            base_query
            .options(
                selectinload(RecordingAnnotation.recording),
                selectinload(RecordingAnnotation.tag),
                selectinload(RecordingAnnotation.detection_run),
                selectinload(RecordingAnnotation.reviewed_by),
            )
            .order_by(RecordingAnnotation.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        annotations = list(result.scalars().all())

        return annotations, total

    async def species_summary(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
    ) -> list[SpeciesSummaryRow]:
        """Species rollup keyed by tag.

        Queries the live :class:`RecordingAnnotation` table
        (``recording_annotations_DEFERRED``).
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.detection_run import DetectionRun
        from echoroo.models.recording import Recording

        def _agg_columns() -> list[object]:
            return [
                func.count(RecordingAnnotation.id).label("total_count"),
                func.avg(RecordingAnnotation.confidence).label("avg_confidence"),
                func.sum(
                    cast(RecordingAnnotation.status == DetectionStatus.UNREVIEWED, Integer)
                ).label("unreviewed_count"),
                func.sum(
                    cast(RecordingAnnotation.status == DetectionStatus.CONFIRMED, Integer)
                ).label("confirmed_count"),
                func.sum(
                    cast(RecordingAnnotation.status == DetectionStatus.REJECTED, Integer)
                ).label("rejected_count"),
            ]

        if detection_run_id is not None:
            query = (
                select(
                    RecordingAnnotation.tag_id,
                    Tag.name.label("tag_name"),
                    Tag.scientific_name,
                    Tag.common_name,
                    Tag.taxon_id,
                    RecordingAnnotation.source.label("annotation_source"),
                    DetectionRun.model_name.label("detection_run_model_name"),
                    *_agg_columns(),
                )
                .join(Recording, RecordingAnnotation.recording_id == Recording.id)
                .join(Dataset, Recording.dataset_id == Dataset.id)
                .outerjoin(Tag, RecordingAnnotation.tag_id == Tag.id)
                .outerjoin(
                    DetectionRun, RecordingAnnotation.detection_run_id == DetectionRun.id
                )
                .where(Dataset.project_id == project_id)
                .where(RecordingAnnotation.detection_run_id == detection_run_id)
                .group_by(
                    RecordingAnnotation.tag_id,
                    Tag.name,
                    Tag.scientific_name,
                    Tag.common_name,
                    Tag.taxon_id,
                    RecordingAnnotation.source,
                    DetectionRun.model_name,
                )
                .order_by(func.count(RecordingAnnotation.id).desc())
            )
            if dataset_id is not None:
                query = query.where(Recording.dataset_id == dataset_id)

            result = await self.db.execute(query)
            rows = result.all()

            return [
                SpeciesSummaryRow(
                    tag_id=row.tag_id,
                    tag_name=(
                        row.tag_name
                        if row.tag_name is not None
                        else (row.detection_run_model_name or str(row.annotation_source))
                    ),
                    scientific_name=row.scientific_name,
                    common_name=row.common_name,
                    taxon_id=row.taxon_id,
                    total_count=row.total_count,
                    avg_confidence=float(row.avg_confidence) if row.avg_confidence is not None else None,
                    unreviewed_count=int(row.unreviewed_count or 0),
                    confirmed_count=int(row.confirmed_count or 0),
                    rejected_count=int(row.rejected_count or 0),
                )
                for row in rows
            ]

        query_no_run = (
            select(
                RecordingAnnotation.tag_id,
                Tag.name.label("tag_name"),
                Tag.scientific_name,
                Tag.common_name,
                Tag.taxon_id,
                *_agg_columns(),
            )
            .join(Recording, RecordingAnnotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .outerjoin(Tag, RecordingAnnotation.tag_id == Tag.id)
            .where(Dataset.project_id == project_id)
            .where(RecordingAnnotation.tag_id.isnot(None))
            .group_by(
                RecordingAnnotation.tag_id,
                Tag.name,
                Tag.scientific_name,
                Tag.common_name,
                Tag.taxon_id,
            )
            .order_by(func.count(RecordingAnnotation.id).desc())
        )
        if dataset_id is not None:
            query_no_run = query_no_run.where(Recording.dataset_id == dataset_id)

        result_no_run = await self.db.execute(query_no_run)
        rows_no_run = result_no_run.all()

        return [
            SpeciesSummaryRow(
                tag_id=row.tag_id,
                tag_name=row.tag_name,
                scientific_name=row.scientific_name,
                common_name=row.common_name,
                taxon_id=row.taxon_id,
                total_count=row.total_count,
                avg_confidence=float(row.avg_confidence) if row.avg_confidence is not None else None,
                unreviewed_count=int(row.unreviewed_count or 0),
                confirmed_count=int(row.confirmed_count or 0),
                rejected_count=int(row.rejected_count or 0),
            )
            for row in rows_no_run
        ]

    async def temporal_summary(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
    ) -> list[TemporalSummaryRow]:
        """Hourly detection counts grouped by tag.

        Queries the live :class:`RecordingAnnotation` table
        (``recording_annotations_DEFERRED``).
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        tz_expr = func.coalesce(Dataset.datetime_timezone, "UTC")
        local_datetime = Recording.datetime.op("AT TIME ZONE")(tz_expr)
        date_expr = func.date(local_datetime).label("detection_date")
        hour_expr = func.extract("hour", local_datetime).label("detection_hour")

        query = (
            select(
                RecordingAnnotation.tag_id,
                date_expr,
                hour_expr,
                func.count(RecordingAnnotation.id).label("detection_count"),
            )
            .join(Recording, RecordingAnnotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
            .where(RecordingAnnotation.tag_id.isnot(None))
            .where(Recording.datetime.isnot(None))
            .group_by(
                RecordingAnnotation.tag_id,
                func.date(local_datetime),
                func.extract("hour", local_datetime),
            )
            .order_by(
                RecordingAnnotation.tag_id,
                func.date(local_datetime),
                func.extract("hour", local_datetime),
            )
        )

        if dataset_id is not None:
            query = query.where(Recording.dataset_id == dataset_id)

        if detection_run_id is not None:
            query = query.where(RecordingAnnotation.detection_run_id == detection_run_id)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "tag_id": row.tag_id,
                "date": row.detection_date,
                "hour": int(row.detection_hour),
                "count": int(row.detection_count),
            }
            for row in rows
        ]

    async def create(self, annotation: RecordingAnnotation) -> RecordingAnnotation:
        """Create a rich-shape recording annotation."""
        self.db.add(annotation)
        await self.db.flush()
        await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotation

    async def create_batch(
        self, annotations: list[RecordingAnnotation]
    ) -> list[RecordingAnnotation]:
        """Batch-create rich-shape recording annotations."""
        for annotation in annotations:
            self.db.add(annotation)
        await self.db.flush()
        for annotation in annotations:
            await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotations

    async def update(self, annotation: RecordingAnnotation) -> RecordingAnnotation:
        """Update a rich-shape recording annotation."""
        await self.db.flush()
        await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotation

    async def delete_by_detection_run(self, detection_run_id: UUID) -> int:
        """Bulk-delete recording annotations by run."""
        cursor: CursorResult[tuple[()]] = await self.db.execute(  # type: ignore[assignment]
            delete(RecordingAnnotation).where(
                RecordingAnnotation.detection_run_id == detection_run_id
            )
        )
        await self.db.flush()
        return cursor.rowcount
