"""Annotation repository for detection review database operations."""

from __future__ import annotations

from datetime import date
from typing import TypedDict
from uuid import UUID

from sqlalchemy import Integer, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.expression import cast

from echoroo.models.annotation import Annotation
from echoroo.models.enums import DetectionStatus
from echoroo.models.tag import Tag
from echoroo.repositories.base import BaseRepository


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
    """Repository for Annotation entity operations."""

    model = Annotation

    async def get_by_id(self, annotation_id: UUID) -> Annotation | None:
        """Get annotation by ID with all relationships loaded.

        Args:
            annotation_id: Annotation's UUID

        Returns:
            Annotation instance or None if not found
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
        """Get annotation by ID, restricted to the given project.

        Verifies the integrity chain
        ``Annotation.recording_id -> Recording.dataset_id -> Dataset.project_id``
        so that an annotation UUID belonging to a different project returns
        ``None`` instead of leaking the row (BOLA / IDOR guard, FR-008 /
        FR-008a / FR-037).

        Args:
            annotation_id: Annotation's UUID.
            project_id: Project UUID the annotation must belong to.

        Returns:
            Annotation instance with relationships loaded, or ``None`` when the
            annotation does not exist or does not belong to ``project_id``.
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

    async def exists_in_project(
        self, annotation_id: UUID, project_id: UUID
    ) -> bool:
        """Return ``True`` when an annotation belongs to ``project_id``.

        Lighter-weight existence probe used by API handlers that only need
        to enforce the BOLA / IDOR guard before delegating to a service
        method that issues its own SELECT.

        Args:
            annotation_id: Annotation's UUID.
            project_id: Project UUID the annotation must belong to.

        Returns:
            ``True`` when the annotation exists in the given project,
            ``False`` otherwise.
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        result = await self.db.execute(
            select(Annotation.id)
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Annotation.id == annotation_id)
            .where(Dataset.project_id == project_id)
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
        """List annotations for a project with optional filters and pagination.

        Args:
            project_id: Project's UUID (filters via recording -> dataset -> project)
            tag_id: Optional tag filter
            status: Optional review status filter
            confidence_min: Optional minimum confidence score filter
            confidence_max: Optional maximum confidence score filter
            dataset_id: Optional dataset filter (via recording -> dataset)
            recording_id: Optional specific recording filter
            detection_run_id: Optional detection run filter
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of annotations, total count)
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        # Build join conditions to filter by project_id
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

        # Apply optional filters
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

        # Get total count
        count_result = await self.db.execute(count_query)
        total: int = count_result.scalar_one()

        # Get paginated results
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
        """Get species detection summary grouped by tag.

        Returns count, average confidence, and status breakdown per species tag.

        When filtering by a specific detection_run_id, annotations without a
        tag_id (e.g. custom_svm source) are included and grouped by source/model.
        When no detection_run_id filter is applied, only tagged annotations are
        returned, grouped by tag_id across all detection runs.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter
            detection_run_id: Optional detection run filter

        Returns:
            List of dicts with tag info and aggregated statistics
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
            # When filtering by a specific run, include tag-less annotations and
            # group by tag_id + source + model_name so custom_svm entries appear.
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

        # No detection_run_id filter: group by tag only, exclude tag-less annotations
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
        """Get hourly detection counts grouped by tag, date, and hour.

        Only includes recordings with a non-null datetime field.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter
            detection_run_id: Optional detection run filter

        Returns:
            List of dicts with tag_id, date, hour, and count fields
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        # Convert each recording's datetime to its dataset's timezone before
        # extracting date and hour. PostgreSQL's ``AT TIME ZONE`` converts a
        # ``timestamptz`` to a ``timestamp`` in the given zone, so EXTRACT
        # will return the local hour. Falls back to UTC if the dataset has
        # no timezone configured.
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
        """Create a new annotation.

        Args:
            annotation: Annotation instance to create

        Returns:
            Created annotation instance
        """
        self.db.add(annotation)
        await self.db.flush()
        await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotation

    async def create_batch(self, annotations: list[Annotation]) -> list[Annotation]:
        """Create multiple annotations in a single flush.

        Args:
            annotations: List of Annotation instances to create

        Returns:
            List of created annotation instances
        """
        for annotation in annotations:
            self.db.add(annotation)
        await self.db.flush()
        for annotation in annotations:
            await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotations

    async def update(self, annotation: Annotation) -> Annotation:
        """Update an existing annotation.

        Args:
            annotation: Annotation instance with updated fields

        Returns:
            Updated annotation instance
        """
        await self.db.flush()
        await self.db.refresh(annotation, ["recording", "tag", "detection_run", "reviewed_by"])
        return annotation


    async def delete_by_detection_run(self, detection_run_id: UUID) -> int:
        """Delete all annotations belonging to a detection run.

        Args:
            detection_run_id: DetectionRun's UUID

        Returns:
            Number of deleted annotations
        """
        cursor: CursorResult[tuple[()]] = await self.db.execute(  # type: ignore[assignment]
            delete(Annotation).where(Annotation.detection_run_id == detection_run_id)
        )
        await self.db.flush()
        return cursor.rowcount
