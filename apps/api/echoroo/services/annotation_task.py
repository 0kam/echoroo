"""AnnotationTask service for business logic."""

import math
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.enums import AnnotationTaskStatus
from echoroo.repositories.annotation_project import AnnotationProjectRepository
from echoroo.repositories.annotation_task import AnnotationTaskRepository
from echoroo.schemas.annotation_project import TagSummary
from echoroo.schemas.annotation_task import (
    AnnotationProjectSummary,
    AnnotationTaskDetailResponse,
    AnnotationTaskListResponse,
    AnnotationTaskResponse,
    AnnotationTaskUpdate,
    ClipDetailForTask,
    RecordingSummaryForTask,
    TaskCompletionResponse,
)


class AnnotationTaskService:
    """Service for annotation task management business logic."""

    def __init__(
        self,
        task_repo: AnnotationTaskRepository,
        annotation_project_repo: AnnotationProjectRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            task_repo: AnnotationTask repository instance
            annotation_project_repo: AnnotationProject repository instance
        """
        self.task_repo = task_repo
        self.annotation_project_repo = annotation_project_repo

    def _build_clip_detail(self, task: AnnotationTask) -> ClipDetailForTask | None:
        """Build ClipDetailForTask from a task's clip relationship.

        Args:
            task: AnnotationTask with clip relationship loaded

        Returns:
            ClipDetailForTask schema instance or None
        """
        clip = task.clip
        if clip is None:
            return None

        recording = None
        if clip.recording is not None:
            recording = RecordingSummaryForTask(
                id=clip.recording.id,
                filename=clip.recording.filename,
                samplerate=clip.recording.samplerate,
                duration=clip.recording.duration,
            )

        return ClipDetailForTask(
            id=clip.id,
            recording_id=clip.recording_id,
            start_time=clip.start_time,
            end_time=clip.end_time,
            recording=recording,
        )

    def _build_annotation_project_summary(
        self, task: AnnotationTask
    ) -> AnnotationProjectSummary | None:
        """Build AnnotationProjectSummary from a task's annotation_project relationship.

        Args:
            task: AnnotationTask with annotation_project relationship loaded

        Returns:
            AnnotationProjectSummary schema instance or None
        """
        ap = task.annotation_project
        if ap is None:
            return None

        tags = [TagSummary.model_validate(t) for t in (ap.tags or [])]

        return AnnotationProjectSummary(
            id=ap.id,
            name=ap.name,
            instructions=ap.instructions,
            tags=tags,
        )

    def _build_detail_response(self, task: AnnotationTask) -> AnnotationTaskDetailResponse:
        """Build AnnotationTaskDetailResponse from an AnnotationTask ORM instance.

        Args:
            task: AnnotationTask ORM instance with relationships loaded

        Returns:
            AnnotationTaskDetailResponse schema instance
        """
        clip_detail = self._build_clip_detail(task)
        ap_summary = self._build_annotation_project_summary(task)

        clip_annotation_dict: dict[str, object] | None = None
        if task.clip_annotation is not None:
            from echoroo.schemas.annotation import ClipAnnotationDetailResponse

            clip_annotation_dict = ClipAnnotationDetailResponse.model_validate(
                task.clip_annotation
            ).model_dump()

        return AnnotationTaskDetailResponse(
            id=task.id,
            annotation_project_id=task.annotation_project_id,
            clip_id=task.clip_id,
            assigned_to_id=task.assigned_to_id,
            status=task.status,
            priority=task.priority,
            created_at=task.created_at,
            updated_at=task.updated_at,
            clip=clip_detail,
            clip_annotation=clip_annotation_dict,
            annotation_project=ap_summary,
        )

    async def list_tasks(
        self,
        annotation_project_id: UUID,
        status: AnnotationTaskStatus | None = None,
        assigned_to_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "asc",
    ) -> AnnotationTaskListResponse:
        """List annotation tasks for a project with optional filtering and pagination.

        Args:
            annotation_project_id: AnnotationProject's UUID
            status: Optional status filter
            assigned_to_id: Optional user UUID filter for assigned tasks
            page: Page number (1-indexed)
            page_size: Items per page
            sort_by: Sort column name (priority, created_at, status)
            sort_order: Sort direction (asc/desc)

        Returns:
            Paginated AnnotationTaskListResponse
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 200:
            page_size = 50

        tasks, total = await self.task_repo.list_by_project(
            annotation_project_id=annotation_project_id,
            status=status,
            assigned_to_id=assigned_to_id,
            page=page,
            page_size=page_size,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        pages = math.ceil(total / page_size) if total > 0 else 0

        items = [AnnotationTaskResponse.model_validate(t) for t in tasks]

        return AnnotationTaskListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def get_detail(self, task_id: UUID) -> AnnotationTaskDetailResponse:
        """Get annotation task details with related data.

        Args:
            task_id: AnnotationTask's UUID

        Returns:
            Annotation task detail response with clip, clip_annotation, and annotation_project

        Raises:
            HTTPException: 404 if annotation task not found
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation task not found",
            )

        return self._build_detail_response(task)

    async def update(
        self,
        task_id: UUID,
        request: AnnotationTaskUpdate,
    ) -> AnnotationTaskDetailResponse:
        """Update an annotation task.

        Args:
            task_id: AnnotationTask's UUID
            request: Update data

        Returns:
            Updated annotation task detail response

        Raises:
            HTTPException: 404 if annotation task not found
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation task not found",
            )

        if request.assigned_to_id is not None:
            task.assigned_to_id = request.assigned_to_id
        if request.status is not None:
            task.status = request.status
        if request.priority is not None:
            task.priority = request.priority

        updated = await self.task_repo.update(task)

        return self._build_detail_response(updated)

    async def complete(
        self, task_id: UUID, user_id: UUID
    ) -> TaskCompletionResponse:
        """Mark an annotation task as completed and return the next available task.

        Args:
            task_id: AnnotationTask's UUID to complete
            user_id: User performing the completion

        Returns:
            TaskCompletionResponse with completed task ID and optional next task

        Raises:
            HTTPException: 404 if annotation task not found
        """
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation task not found",
            )

        task.status = AnnotationTaskStatus.COMPLETED
        await self.task_repo.update(task)

        next_task = await self.task_repo.get_next(task.annotation_project_id, user_id)
        next_task_response: AnnotationTaskDetailResponse | None = None
        if next_task:
            next_task_response = self._build_detail_response(next_task)

        return TaskCompletionResponse(
            completed_task_id=task_id,
            next_task=next_task_response,
        )

    async def get_next(
        self, annotation_project_id: UUID, user_id: UUID
    ) -> AnnotationTaskDetailResponse | None:
        """Get the next pending or in-progress task for a user.

        Args:
            annotation_project_id: AnnotationProject's UUID
            user_id: User's UUID

        Returns:
            AnnotationTaskDetailResponse or None if no eligible tasks exist
        """
        task = await self.task_repo.get_next(annotation_project_id, user_id)
        if not task:
            return None

        return self._build_detail_response(task)
