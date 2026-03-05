"""Annotation repository for detection review database operations."""

from __future__ import annotations

from datetime import date
from typing import TypedDict
from uuid import UUID

from sqlalchemy import Integer, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.expression import cast

from echoroo.models.annotation import Annotation
from echoroo.models.enums import DetectionStatus
from echoroo.models.tag import Tag


class TemporalSummaryRow(TypedDict):
    """Typed row for temporal summary query results."""

    tag_id: UUID
    date: date
    hour: int
    count: int


class SpeciesSummaryRow(TypedDict):
    """Typed row for species summary query results."""

    tag_id: UUID
    tag_name: str
    scientific_name: str | None
    common_name: str | None
    total_count: int
    avg_confidence: float | None
    unreviewed_count: int
    confirmed_count: int
    rejected_count: int


class AnnotationRepository:
    """Repository for Annotation entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

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

    async def list_annotations(
        self,
        project_id: UUID,
        tag_id: UUID | None = None,
        status: DetectionStatus | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        dataset_id: UUID | None = None,
        recording_id: UUID | None = None,
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
    ) -> list[SpeciesSummaryRow]:
        """Get species detection summary grouped by tag.

        Returns count, average confidence, and status breakdown per species tag.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter

        Returns:
            List of dicts with tag info and aggregated statistics
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        query = (
            select(
                Annotation.tag_id,
                Tag.name.label("tag_name"),
                Tag.scientific_name,
                Tag.common_name,
                func.count(Annotation.id).label("total_count"),
                func.avg(Annotation.confidence).label("avg_confidence"),
                func.sum(
                    cast(
                        Annotation.status == DetectionStatus.UNREVIEWED,
                        Integer,
                    )
                ).label("unreviewed_count"),
                func.sum(
                    cast(
                        Annotation.status == DetectionStatus.CONFIRMED,
                        Integer,
                    )
                ).label("confirmed_count"),
                func.sum(
                    cast(
                        Annotation.status == DetectionStatus.REJECTED,
                        Integer,
                    )
                ).label("rejected_count"),
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
            )
            .order_by(func.count(Annotation.id).desc())
        )

        if dataset_id is not None:
            query = query.where(Recording.dataset_id == dataset_id)

        result = await self.db.execute(query)
        rows = result.all()

        return [
            {
                "tag_id": row.tag_id,
                "tag_name": row.tag_name,
                "scientific_name": row.scientific_name,
                "common_name": row.common_name,
                "total_count": row.total_count,
                "avg_confidence": float(row.avg_confidence) if row.avg_confidence is not None else None,
                "unreviewed_count": int(row.unreviewed_count or 0),
                "confirmed_count": int(row.confirmed_count or 0),
                "rejected_count": int(row.rejected_count or 0),
            }
            for row in rows
        ]

    async def temporal_summary(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
    ) -> list[TemporalSummaryRow]:
        """Get hourly detection counts grouped by tag, date, and hour.

        Only includes recordings with a non-null datetime field.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter

        Returns:
            List of dicts with tag_id, date, hour, and count fields
        """
        from echoroo.models.dataset import Dataset
        from echoroo.models.recording import Recording

        query = (
            select(
                Annotation.tag_id,
                func.date(Recording.datetime).label("detection_date"),
                func.extract("hour", Recording.datetime).label("detection_hour"),
                func.count(Annotation.id).label("detection_count"),
            )
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
            .where(Annotation.tag_id.isnot(None))
            .where(Recording.datetime.isnot(None))
            .group_by(
                Annotation.tag_id,
                func.date(Recording.datetime),
                func.extract("hour", Recording.datetime),
            )
            .order_by(
                Annotation.tag_id,
                func.date(Recording.datetime),
                func.extract("hour", Recording.datetime),
            )
        )

        if dataset_id is not None:
            query = query.where(Recording.dataset_id == dataset_id)

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

    async def delete(self, annotation_id: UUID) -> None:
        """Delete an annotation by ID.

        Args:
            annotation_id: Annotation's UUID
        """
        await self.db.execute(delete(Annotation).where(Annotation.id == annotation_id))
        await self.db.flush()

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
