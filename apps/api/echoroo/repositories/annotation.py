"""Annotation repository for detection review database operations.

Phase 13 P1.5 R2 (Codex follow-up — Fatal): the legacy rich-shape methods
(``list_annotations`` / ``species_summary`` / ``temporal_summary`` / ``create``
/ ``create_batch`` / ``update`` / ``delete_by_detection_run``) operate on the
Phase 14+ deferred :class:`RecordingAnnotation` ORM whose ``__tablename__`` is
``recording_annotations_DEFERRED`` and does not exist in the database. They
are kept compilable so legacy services / workers (search-session, evaluation,
detection-export, ML workers) continue to typecheck while their tables come
back online in Phase 14+; runtime calls will fail with PostgreSQL ``relation
does not exist`` — by design.

The two methods that survive into Phase 13 production traffic
(:meth:`exists_in_project` and :meth:`get_by_id_in_project`) are rewritten on
top of the DB-truth minimal :class:`Annotation` shape — they reach the
project via the parent ``Detection`` row instead of the legacy
``Annotation.recording_id -> Recording.dataset_id -> Dataset.project_id``
chain that no longer compiles. See :class:`echoroo.models.annotation.Annotation`
module docstring for the bridging strategy.
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
from echoroo.models.recording_annotation import (
    RecordingAnnotation as Annotation,  # Phase 14+ deferred (was rich-shape)
)
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


class AnnotationRepository(BaseRepository[Annotation]):
    """Repository for Annotation entity operations.

    Phase 13 P1.5 R2: bound to :class:`RecordingAnnotation` for legacy
    rich-shape methods (Phase 14+ deferred). The two methods used by the
    Phase 13 vote API path are rewritten on the DB-truth minimal shape.
    """

    model = Annotation

    async def get_by_id(self, annotation_id: UUID) -> Annotation | None:
        """Phase 14+ deferred — was: get rich-shape annotation with rels.

        Production callers should use :meth:`get_by_id_in_project` instead.
        """
        result = await self.db.execute(
            select(Annotation)
            .where(Annotation.id == annotation_id)
            .options(
                selectinload(Annotation.recording),
                selectinload(Annotation.tag),
                selectinload(Annotation.detection_run),
                selectinload(Annotation.reviewed_by),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_in_project(
        self, annotation_id: UUID, project_id: UUID
    ) -> Annotation | None:
        """Phase 14+ deferred — see ``exists_in_project`` for the
        production-safe BOLA / IDOR guard built on the DB-truth minimal
        :class:`Annotation` shape.

        This rich-shape variant continues to point at
        :class:`RecordingAnnotation` so legacy services that load eager
        relationships (``recording`` / ``tag`` / ``detection_run`` /
        ``reviewed_by``) keep compiling. It will raise at runtime because
        the deferred table does not exist.
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        result = await self.db.execute(
            select(Annotation)
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Annotation.id == annotation_id)
            .where(Dataset.project_id == project_id)
            .options(
                selectinload(Annotation.recording),
                selectinload(Annotation.tag),
                selectinload(Annotation.detection_run),
                selectinload(Annotation.reviewed_by),
            )
        )
        return result.scalar_one_or_none()

    async def exists(self, annotation_id: UUID) -> bool:
        """Lightweight existence probe on the DB-truth minimal shape.

        Phase 13 P1.5 R2: replaces the legacy ``get_by_id`` truthiness check
        that some service-layer callers used for "annotation exists" gating
        without reading any rich-shape columns. The legacy ``get_by_id``
        still routes to :class:`RecordingAnnotation` (Phase 14+ deferred);
        callers that only need existence should use this method.

        Args:
            annotation_id: Annotation's UUID.

        Returns:
            ``True`` when the annotation row exists in the DB-truth
            minimal ``annotations`` table.
        """
        result = await self.db.execute(
            select(MinimalAnnotation.id).where(MinimalAnnotation.id == annotation_id)
        )
        return result.first() is not None

    async def exists_in_project(
        self, annotation_id: UUID, project_id: UUID
    ) -> bool:
        """Return ``True`` when an annotation belongs to ``project_id``.

        Phase 13 P1.5 R2 (Codex follow-up — Fatal): rewritten on the
        DB-truth minimal :class:`Annotation` shape. The integrity chain
        is now ``Annotation.detection_id -> Detection.project_id`` (FR-005);
        ``Detection`` is the canonical recording- and project-scoped row
        (the rich-shape ``Annotation.recording_id`` chain that the legacy
        repository used does not exist in production DB).

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
    ) -> tuple[list[Annotation], int]:
        """Phase 14+ deferred — list annotations using rich-shape filters.

        Routes to :class:`RecordingAnnotation`. Will raise at runtime because
        the ``recording_annotations_DEFERRED`` table does not exist; the
        Phase 6 detections list endpoint should migrate to a
        :class:`Detection`-based listing in Phase 14+.
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        base_query = (
            select(Annotation)
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
        )

        count_query = (
            select(func.count())
            .select_from(Annotation)
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
        )

        if tag_id is not None:
            base_query = base_query.where(Annotation.tag_id == tag_id)
            count_query = count_query.where(Annotation.tag_id == tag_id)

        if status is not None:
            base_query = base_query.where(Annotation.status == status)
            count_query = count_query.where(Annotation.status == status)

        if confidence_min is not None:
            base_query = base_query.where(Annotation.confidence >= confidence_min)
            count_query = count_query.where(Annotation.confidence >= confidence_min)

        if confidence_max is not None:
            base_query = base_query.where(Annotation.confidence <= confidence_max)
            count_query = count_query.where(Annotation.confidence <= confidence_max)

        if dataset_id is not None:
            base_query = base_query.where(Recording.dataset_id == dataset_id)
            count_query = count_query.where(Recording.dataset_id == dataset_id)

        if recording_id is not None:
            base_query = base_query.where(Annotation.recording_id == recording_id)
            count_query = count_query.where(Annotation.recording_id == recording_id)

        if detection_run_id is not None:
            base_query = base_query.where(Annotation.detection_run_id == detection_run_id)
            count_query = count_query.where(Annotation.detection_run_id == detection_run_id)

        count_result = await self.db.execute(count_query)
        total: int = count_result.scalar_one()

        offset = (page - 1) * page_size
        result = await self.db.execute(
            base_query
            .options(
                selectinload(Annotation.recording),
                selectinload(Annotation.tag),
                selectinload(Annotation.detection_run),
                selectinload(Annotation.reviewed_by),
            )
            .order_by(Annotation.created_at.desc())
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
        """Phase 14+ deferred — species rollup keyed by tag.

        Routes to :class:`RecordingAnnotation`. Will raise at runtime
        because the deferred table does not exist.
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.detection_run import DetectionRun
        from echoroo.models.recording import Recording

        def _agg_columns() -> list[object]:
            return [
                func.count(Annotation.id).label("total_count"),
                func.avg(Annotation.confidence).label("avg_confidence"),
                func.sum(
                    cast(Annotation.status == DetectionStatus.UNREVIEWED, Integer)
                ).label("unreviewed_count"),
                func.sum(
                    cast(Annotation.status == DetectionStatus.CONFIRMED, Integer)
                ).label("confirmed_count"),
                func.sum(
                    cast(Annotation.status == DetectionStatus.REJECTED, Integer)
                ).label("rejected_count"),
            ]

        if detection_run_id is not None:
            query = (
                select(
                    Annotation.tag_id,
                    Tag.name.label("tag_name"),
                    Tag.scientific_name,
                    Tag.common_name,
                    Tag.taxon_id,
                    Annotation.source.label("annotation_source"),
                    DetectionRun.model_name.label("detection_run_model_name"),
                    *_agg_columns(),
                )
                .join(Recording, Annotation.recording_id == Recording.id)
                .join(Dataset, Recording.dataset_id == Dataset.id)
                .outerjoin(Tag, Annotation.tag_id == Tag.id)
                .outerjoin(DetectionRun, Annotation.detection_run_id == DetectionRun.id)
                .where(Dataset.project_id == project_id)
                .where(Annotation.detection_run_id == detection_run_id)
                .group_by(
                    Annotation.tag_id,
                    Tag.name,
                    Tag.scientific_name,
                    Tag.common_name,
                    Tag.taxon_id,
                    Annotation.source,
                    DetectionRun.model_name,
                )
                .order_by(func.count(Annotation.id).desc())
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
                Annotation.tag_id,
                Tag.name.label("tag_name"),
                Tag.scientific_name,
                Tag.common_name,
                Tag.taxon_id,
                *_agg_columns(),
            )
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .outerjoin(Tag, Annotation.tag_id == Tag.id)
            .where(Dataset.project_id == project_id)
            .where(Annotation.tag_id.isnot(None))
            .group_by(
                Annotation.tag_id,
                Tag.name,
                Tag.scientific_name,
                Tag.common_name,
                Tag.taxon_id,
            )
            .order_by(func.count(Annotation.id).desc())
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
        """Phase 14+ deferred — hourly detection counts grouped by tag.

        Routes to :class:`RecordingAnnotation`. Will raise at runtime
        because the deferred table does not exist.
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        tz_expr = func.coalesce(Dataset.datetime_timezone, "UTC")
        local_datetime = Recording.datetime.op("AT TIME ZONE")(tz_expr)
        date_expr = func.date(local_datetime).label("detection_date")
        hour_expr = func.extract("hour", local_datetime).label("detection_hour")

        query = (
            select(
                Annotation.tag_id,
                date_expr,
                hour_expr,
                func.count(Annotation.id).label("detection_count"),
            )
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
            .where(Annotation.tag_id.isnot(None))
            .where(Recording.datetime.isnot(None))
            .group_by(
                Annotation.tag_id,
                func.date(local_datetime),
                func.extract("hour", local_datetime),
            )
            .order_by(
                Annotation.tag_id,
                func.date(local_datetime),
                func.extract("hour", local_datetime),
            )
        )

        if dataset_id is not None:
            query = query.where(Recording.dataset_id == dataset_id)

        if detection_run_id is not None:
            query = query.where(Annotation.detection_run_id == detection_run_id)

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

    async def create(self, annotation: Annotation) -> Annotation:
        """Phase 14+ deferred — create a rich-shape annotation."""
        self.db.add(annotation)
        await self.db.flush()
        await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotation

    async def create_batch(self, annotations: list[Annotation]) -> list[Annotation]:
        """Phase 14+ deferred — batch-create rich-shape annotations."""
        for annotation in annotations:
            self.db.add(annotation)
        await self.db.flush()
        for annotation in annotations:
            await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotations

    async def update(self, annotation: Annotation) -> Annotation:
        """Phase 14+ deferred — update a rich-shape annotation."""
        await self.db.flush()
        await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotation

    async def delete_by_detection_run(self, detection_run_id: UUID) -> int:
        """Phase 14+ deferred — bulk-delete annotations by run."""
        cursor: CursorResult[tuple[()]] = await self.db.execute(  # type: ignore[assignment]
            delete(Annotation).where(Annotation.detection_run_id == detection_run_id)
        )
        await self.db.flush()
        return cursor.rowcount
