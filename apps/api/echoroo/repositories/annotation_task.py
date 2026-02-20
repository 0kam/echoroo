"""AnnotationTask repository for database operations."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.enums import AnnotationTaskStatus


class AnnotationTaskRepository:
    """Repository for AnnotationTask entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, task_id: UUID) -> AnnotationTask | None:
        """Get annotation task by ID with clip, clip_annotation, and annotation_project loaded.

        Args:
            task_id: AnnotationTask's UUID

        Returns:
            AnnotationTask instance or None if not found
        """
        result = await self.db.execute(
            select(AnnotationTask)
            .where(AnnotationTask.id == task_id)
            .options(
                selectinload(AnnotationTask.clip),
                selectinload(AnnotationTask.clip_annotation),
                selectinload(AnnotationTask.annotation_project),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        annotation_project_id: UUID,
        status: AnnotationTaskStatus | None = None,
        assigned_to_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "asc",
    ) -> tuple[list[AnnotationTask], int]:
        """List annotation tasks for a project with optional filtering, sorting, and pagination.

        Args:
            annotation_project_id: AnnotationProject's UUID
            status: Optional status filter
            assigned_to_id: Optional user UUID filter for assigned tasks
            page: Page number (1-indexed)
            page_size: Items per page
            sort_by: Sort column name (priority, created_at, status)
            sort_order: Sort direction (asc/desc)

        Returns:
            Tuple of (list of annotation tasks, total count)
        """
        # Build base filter conditions
        conditions = [AnnotationTask.annotation_project_id == annotation_project_id]
        if status is not None:
            conditions.append(AnnotationTask.status == status)
        if assigned_to_id is not None:
            conditions.append(AnnotationTask.assigned_to_id == assigned_to_id)

        # Get total count
        count_result = await self.db.execute(
            select(func.count()).select_from(AnnotationTask).where(*conditions)
        )
        total: int = count_result.scalar_one()

        # Determine sort column
        sort_column_map = {
            "priority": AnnotationTask.priority,
            "created_at": AnnotationTask.created_at,
            "status": AnnotationTask.status,
        }
        sort_column = sort_column_map.get(sort_by, AnnotationTask.created_at)

        # Build paginated query
        offset = (page - 1) * page_size
        query = (
            select(AnnotationTask)
            .where(*conditions)
            .options(
                selectinload(AnnotationTask.clip),
                selectinload(AnnotationTask.clip_annotation),
                selectinload(AnnotationTask.annotation_project),
            )
        )

        if sort_order == "desc":
            query = query.order_by(sort_column.desc())
        else:
            query = query.order_by(sort_column.asc())

        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        tasks = list(result.scalars().all())

        return tasks, total

    async def get_next(
        self, annotation_project_id: UUID, user_id: UUID
    ) -> AnnotationTask | None:
        """Get the next pending or in-progress task for a user.

        Prefers tasks assigned to the user, then unassigned tasks.
        Tasks are ordered by priority descending, then created_at ascending.

        Args:
            annotation_project_id: AnnotationProject's UUID
            user_id: User's UUID

        Returns:
            AnnotationTask instance or None if no eligible tasks exist
        """
        eligible_statuses = [AnnotationTaskStatus.PENDING, AnnotationTaskStatus.IN_PROGRESS]

        result = await self.db.execute(
            select(AnnotationTask)
            .where(
                AnnotationTask.annotation_project_id == annotation_project_id,
                AnnotationTask.status.in_(eligible_statuses),
                or_(
                    AnnotationTask.assigned_to_id == user_id,
                    AnnotationTask.assigned_to_id.is_(None),
                ),
            )
            .options(
                selectinload(AnnotationTask.clip),
                selectinload(AnnotationTask.clip_annotation),
                selectinload(AnnotationTask.annotation_project),
            )
            # Prefer tasks assigned to the user (assigned_to_id = user_id sorts before NULL)
            .order_by(
                # NULL assigned_to_id sorts last (unassigned tasks come after user-assigned)
                AnnotationTask.assigned_to_id.is_(None).asc(),
                AnnotationTask.priority.desc(),
                AnnotationTask.created_at.asc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_batch(self, tasks: list[AnnotationTask]) -> list[AnnotationTask]:
        """Create multiple annotation tasks in bulk.

        Args:
            tasks: List of AnnotationTask instances to create

        Returns:
            List of created annotation task instances
        """
        self.db.add_all(tasks)
        await self.db.flush()
        return tasks

    async def update(self, task: AnnotationTask) -> AnnotationTask:
        """Update an existing annotation task.

        Args:
            task: AnnotationTask instance to update

        Returns:
            Updated annotation task instance
        """
        await self.db.flush()
        await self.db.refresh(task, ["clip", "clip_annotation", "annotation_project"])
        return task

    async def count_by_status(self, annotation_project_id: UUID) -> dict[str, int]:
        """Count annotation tasks grouped by status for a project.

        Args:
            annotation_project_id: AnnotationProject's UUID

        Returns:
            Dictionary mapping status values to counts
        """
        result = await self.db.execute(
            select(AnnotationTask.status, func.count().label("cnt"))
            .where(AnnotationTask.annotation_project_id == annotation_project_id)
            .group_by(AnnotationTask.status)
        )
        rows = result.all()

        # Initialize all statuses with zero counts
        counts: dict[str, int] = {status.value: 0 for status in AnnotationTaskStatus}
        for row in rows:
            counts[row.status.value] = row.cnt

        return counts
