"""AnnotationTask repository for database operations."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.clip_annotation import ClipAnnotation
from echoroo.models.enums import AnnotationTaskStatus
from echoroo.models.sound_event_annotation import SoundEventAnnotation
from echoroo.repositories.base import BaseRepository


class AnnotationTaskRepository(BaseRepository[AnnotationTask]):
    """Repository for AnnotationTask entity operations."""

    model = AnnotationTask

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
                # Eager-load the nested clip_annotation relationships that
                # ``_build_detail_response`` serializes (tags, sound_events +
                # their tags, notes). Without these, Pydantic serialization
                # triggers a lazy load inside the async context and raises
                # MissingGreenlet once a task actually has a clip_annotation.
                selectinload(AnnotationTask.clip_annotation).selectinload(
                    ClipAnnotation.tags
                ),
                selectinload(AnnotationTask.clip_annotation)
                .selectinload(ClipAnnotation.sound_events)
                .selectinload(SoundEventAnnotation.tags),
                selectinload(AnnotationTask.clip_annotation).selectinload(
                    ClipAnnotation.notes
                ),
                selectinload(AnnotationTask.annotation_project).selectinload(AnnotationProject.tags),
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
                selectinload(AnnotationTask.annotation_project).selectinload(AnnotationProject.tags),
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
                # Mirror get_by_id: get_next results are serialized via
                # ``_build_detail_response`` (TaskCompletionResponse.next_task /
                # GET next-task), so the nested clip_annotation relationships
                # must be eager-loaded to avoid MissingGreenlet.
                selectinload(AnnotationTask.clip_annotation).selectinload(
                    ClipAnnotation.tags
                ),
                selectinload(AnnotationTask.clip_annotation)
                .selectinload(ClipAnnotation.sound_events)
                .selectinload(SoundEventAnnotation.tags),
                selectinload(AnnotationTask.clip_annotation).selectinload(
                    ClipAnnotation.notes
                ),
                selectinload(AnnotationTask.annotation_project).selectinload(AnnotationProject.tags),
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

    async def count_by_status_batch(
        self, annotation_project_ids: list[UUID]
    ) -> dict[UUID, dict[str, int]]:
        """Count annotation tasks grouped by status for multiple projects in one query.

        Replaces the N+1 pattern of calling count_by_status() in a loop.

        Args:
            annotation_project_ids: List of AnnotationProject UUIDs

        Returns:
            Mapping of annotation_project_id -> {status_value: count}
        """
        if not annotation_project_ids:
            return {}

        result = await self.db.execute(
            select(
                AnnotationTask.annotation_project_id,
                AnnotationTask.status,
                func.count().label("cnt"),
            )
            .where(AnnotationTask.annotation_project_id.in_(annotation_project_ids))
            .group_by(AnnotationTask.annotation_project_id, AnnotationTask.status)
        )
        rows = result.all()

        # Build a mapping: project_id -> {status: count}, initialised with zeros
        zero_counts: dict[str, int] = {s.value: 0 for s in AnnotationTaskStatus}
        batch: dict[UUID, dict[str, int]] = {
            pid: dict(zero_counts) for pid in annotation_project_ids
        }
        for row in rows:
            batch[row.annotation_project_id][row.status.value] = row.cnt

        return batch
