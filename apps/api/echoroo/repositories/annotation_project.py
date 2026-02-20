"""AnnotationProject repository for database operations."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.enums import AnnotationTaskStatus


class AnnotationProjectRepository:
    """Repository for AnnotationProject entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, annotation_project_id: UUID) -> AnnotationProject | None:
        """Get annotation project by ID with datasets and tags relationships loaded.

        Args:
            annotation_project_id: AnnotationProject's UUID

        Returns:
            AnnotationProject instance or None if not found
        """
        result = await self.db.execute(
            select(AnnotationProject)
            .where(AnnotationProject.id == annotation_project_id)
            .options(
                selectinload(AnnotationProject.datasets),
                selectinload(AnnotationProject.tags),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AnnotationProject], int]:
        """List annotation projects for a project with pagination.

        Args:
            project_id: Parent project's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of annotation projects, total count)
        """
        # Get total count
        count_result = await self.db.execute(
            select(func.count())
            .select_from(AnnotationProject)
            .where(AnnotationProject.project_id == project_id)
        )
        total: int = count_result.scalar_one()

        # Build paginated query
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(AnnotationProject)
            .where(AnnotationProject.project_id == project_id)
            .options(
                selectinload(AnnotationProject.datasets),
                selectinload(AnnotationProject.tags),
            )
            .order_by(AnnotationProject.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        annotation_projects = list(result.scalars().all())

        return annotation_projects, total

    async def create(self, annotation_project: AnnotationProject) -> AnnotationProject:
        """Create a new annotation project.

        Args:
            annotation_project: AnnotationProject instance to create

        Returns:
            Created annotation project instance
        """
        self.db.add(annotation_project)
        await self.db.flush()
        await self.db.refresh(annotation_project, ["datasets", "tags"])
        return annotation_project

    async def update(self, annotation_project: AnnotationProject) -> AnnotationProject:
        """Update an existing annotation project.

        Args:
            annotation_project: AnnotationProject instance to update

        Returns:
            Updated annotation project instance
        """
        await self.db.flush()
        await self.db.refresh(annotation_project, ["datasets", "tags"])
        return annotation_project

    async def delete(self, annotation_project_id: UUID) -> None:
        """Delete an annotation project by ID.

        Args:
            annotation_project_id: AnnotationProject's UUID
        """
        await self.db.execute(
            delete(AnnotationProject).where(AnnotationProject.id == annotation_project_id)
        )
        await self.db.flush()

    async def get_progress(self, annotation_project_id: UUID) -> dict[str, int]:
        """Get task progress statistics for an annotation project.

        Counts tasks grouped by status to provide a progress overview.

        Args:
            annotation_project_id: AnnotationProject's UUID

        Returns:
            Dictionary with keys: total_tasks, completed_tasks, in_progress_tasks,
            pending_tasks, review_pending_tasks
        """
        result = await self.db.execute(
            select(
                func.count().label("total_tasks"),
                func.count(
                    AnnotationTask.id
                )
                .filter(AnnotationTask.status == AnnotationTaskStatus.COMPLETED)
                .label("completed_tasks"),
                func.count(
                    AnnotationTask.id
                )
                .filter(AnnotationTask.status == AnnotationTaskStatus.IN_PROGRESS)
                .label("in_progress_tasks"),
                func.count(
                    AnnotationTask.id
                )
                .filter(AnnotationTask.status == AnnotationTaskStatus.PENDING)
                .label("pending_tasks"),
                func.count(
                    AnnotationTask.id
                )
                .filter(AnnotationTask.status == AnnotationTaskStatus.REVIEW_PENDING)
                .label("review_pending_tasks"),
            )
            .select_from(AnnotationTask)
            .where(AnnotationTask.annotation_project_id == annotation_project_id)
        )
        row = result.one()

        return {
            "total_tasks": row.total_tasks,
            "completed_tasks": row.completed_tasks,
            "in_progress_tasks": row.in_progress_tasks,
            "pending_tasks": row.pending_tasks,
            "review_pending_tasks": row.review_pending_tasks,
        }
