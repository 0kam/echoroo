"""Annotation Tasks API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import AnnotationTaskStatus
from echoroo.repositories.annotation_project import AnnotationProjectRepository
from echoroo.repositories.annotation_task import AnnotationTaskRepository
from echoroo.schemas.annotation_task import (
    AnnotationTaskDetailResponse,
    AnnotationTaskListResponse,
    AnnotationTaskUpdate,
    TaskCompletionResponse,
)
from echoroo.services.annotation_task import AnnotationTaskService

router = APIRouter(
    prefix="/projects/{project_id}/annotation-projects/{annotation_project_id}/tasks",
    tags=["annotation-tasks"],
)


def get_annotation_task_service(db: DbSession) -> AnnotationTaskService:
    """Get AnnotationTaskService instance.

    Args:
        db: Database session

    Returns:
        AnnotationTaskService instance
    """
    return AnnotationTaskService(
        task_repo=AnnotationTaskRepository(db),
        annotation_project_repo=AnnotationProjectRepository(db),
    )


AnnotationTaskServiceDep = Annotated[
    AnnotationTaskService, Depends(get_annotation_task_service)
]


@router.get(
    "",
    response_model=AnnotationTaskListResponse,
    summary="List annotation tasks",
    description="List annotation tasks for an annotation project with optional filtering and pagination",
)
async def list_tasks(
    project_id: UUID,
    annotation_project_id: UUID,
    current_user: CurrentUser,
    service: AnnotationTaskServiceDep,
    task_status: AnnotationTaskStatus | None = None,
    assigned_to_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "created_at",
    sort_order: str = "asc",
) -> AnnotationTaskListResponse:
    """List annotation tasks for an annotation project.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        current_user: Current authenticated user
        service: Annotation task service instance
        task_status: Optional status filter
        assigned_to_id: Optional user UUID filter for assigned tasks
        page: Page number (default: 1)
        page_size: Items per page (default: 50)
        sort_by: Sort column (default: created_at)
        sort_order: Sort direction (default: asc)

    Returns:
        Paginated list of annotation tasks

    Raises:
        401: Not authenticated
    """
    return await service.list_tasks(
        annotation_project_id=annotation_project_id,
        status=task_status,
        assigned_to_id=assigned_to_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/next",
    summary="Get next annotation task",
    description="Get the next pending or in-progress annotation task for the current user. Returns 204 if no tasks are available.",
)
async def get_next_task(
    project_id: UUID,
    annotation_project_id: UUID,
    current_user: CurrentUser,
    service: AnnotationTaskServiceDep,
    response: Response,
) -> AnnotationTaskDetailResponse | None:
    """Get the next available annotation task for the current user.

    Prefers tasks assigned to the user, then unassigned tasks.
    Returns 204 No Content if no eligible tasks exist.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        current_user: Current authenticated user
        service: Annotation task service instance
        response: FastAPI response object for setting status code

    Returns:
        Next annotation task detail or None (with 204 status)

    Raises:
        401: Not authenticated
    """
    task = await service.get_next(annotation_project_id, current_user.id)
    if task is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return task


@router.get(
    "/{task_id}",
    response_model=AnnotationTaskDetailResponse,
    summary="Get annotation task",
    description="Get annotation task detail by ID with clip and annotation project information",
)
async def get_task(
    project_id: UUID,
    annotation_project_id: UUID,
    task_id: UUID,
    current_user: CurrentUser,
    service: AnnotationTaskServiceDep,
) -> AnnotationTaskDetailResponse:
    """Get annotation task detail.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        task_id: AnnotationTask's UUID
        current_user: Current authenticated user
        service: Annotation task service instance

    Returns:
        Annotation task detail with clip and annotation project info

    Raises:
        401: Not authenticated
        404: Annotation task not found
    """
    return await service.get_detail(task_id)


@router.patch(
    "/{task_id}",
    response_model=AnnotationTaskDetailResponse,
    summary="Update annotation task",
    description="Update annotation task fields such as status, priority, or assignment",
)
async def update_task(
    project_id: UUID,
    annotation_project_id: UUID,
    task_id: UUID,
    request: AnnotationTaskUpdate,
    current_user: CurrentUser,
    service: AnnotationTaskServiceDep,
) -> AnnotationTaskDetailResponse:
    """Update an annotation task.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        task_id: AnnotationTask's UUID
        request: Update data
        current_user: Current authenticated user
        service: Annotation task service instance

    Returns:
        Updated annotation task detail response

    Raises:
        401: Not authenticated
        404: Annotation task not found
    """
    return await service.update(task_id, request)


@router.post(
    "/{task_id}/complete",
    response_model=TaskCompletionResponse,
    summary="Complete annotation task",
    description="Mark an annotation task as completed and retrieve the next available task",
)
async def complete_task(
    project_id: UUID,
    annotation_project_id: UUID,
    task_id: UUID,
    current_user: CurrentUser,
    service: AnnotationTaskServiceDep,
) -> TaskCompletionResponse:
    """Complete an annotation task.

    Marks the task as completed and returns the next available task for the annotator.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        task_id: AnnotationTask's UUID to complete
        current_user: Current authenticated user
        service: Annotation task service instance

    Returns:
        TaskCompletionResponse with completed task ID and optional next task

    Raises:
        401: Not authenticated
        404: Annotation task not found
    """
    return await service.complete(task_id, current_user.id)
