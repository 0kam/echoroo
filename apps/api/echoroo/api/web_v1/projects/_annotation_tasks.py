"""Project annotation-task BFF adapters."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from echoroo.api.v1 import annotation_tasks as legacy_annotation_tasks
from echoroo.core.actions import (
    ANNOTATION_TASK_COMPLETE_ACTION,
    ANNOTATION_TASK_GET_ACTION,
    ANNOTATION_TASK_LIST_ACTION,
    ANNOTATION_TASK_NEXT_ACTION,
    ANNOTATION_TASK_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import AnnotationTaskStatus

router = APIRouter()


@router.get(
    "/{project_id}/annotation-projects/{annotation_project_id}/tasks",
    response_model=legacy_annotation_tasks.AnnotationTaskListResponse,
    summary="List annotation tasks",
    description="BFF adapter for the legacy annotation-task list endpoint.",
)
async def list_tasks(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_tasks.AnnotationTaskServiceDep,
    db: DbSession,
    task_status: AnnotationTaskStatus | None = Query(None, alias="status"),
    assigned_to_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "created_at",
    sort_order: str = "asc",
) -> legacy_annotation_tasks.AnnotationTaskListResponse:
    """Delegate annotation-task listing to the legacy handler."""
    await gate_action(
        action=ANNOTATION_TASK_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_tasks.list_tasks(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        task_status=task_status,
        assigned_to_id=assigned_to_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{project_id}/annotation-projects/{annotation_project_id}/tasks/next",
    summary="Get next annotation task",
    description="BFF adapter for the legacy next-task endpoint.",
)
async def get_next_task(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_tasks.AnnotationTaskServiceDep,
    response: Response,
    db: DbSession,
) -> legacy_annotation_tasks.AnnotationTaskDetailResponse | None:
    """Delegate next-task selection to the legacy handler."""
    await gate_action(
        action=ANNOTATION_TASK_NEXT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_tasks.get_next_task(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=current_user,
        service=service,
        response=response,
        db=db,
    )


@router.get(
    "/{project_id}/annotation-projects/{annotation_project_id}/tasks/{task_id}",
    response_model=legacy_annotation_tasks.AnnotationTaskDetailResponse,
    summary="Get annotation task",
    description="BFF adapter for the legacy annotation-task detail endpoint.",
)
async def get_task(
    project_id: UUID,
    annotation_project_id: UUID,
    task_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_tasks.AnnotationTaskServiceDep,
    db: DbSession,
) -> legacy_annotation_tasks.AnnotationTaskDetailResponse:
    """Delegate annotation-task detail reads to the legacy handler."""
    await gate_action(
        action=ANNOTATION_TASK_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_tasks.get_task(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        task_id=task_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.patch(
    "/{project_id}/annotation-projects/{annotation_project_id}/tasks/{task_id}",
    response_model=legacy_annotation_tasks.AnnotationTaskDetailResponse,
    summary="Update annotation task",
    description="BFF adapter for the legacy annotation-task update endpoint.",
)
async def update_task(
    project_id: UUID,
    annotation_project_id: UUID,
    task_id: UUID,
    request: legacy_annotation_tasks.AnnotationTaskUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_tasks.AnnotationTaskServiceDep,
    db: DbSession,
) -> legacy_annotation_tasks.AnnotationTaskDetailResponse:
    """Delegate annotation-task updates to the legacy handler."""
    await gate_action(
        action=ANNOTATION_TASK_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_tasks.update_task(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        task_id=task_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/annotation-projects/{annotation_project_id}/tasks/{task_id}/complete",
    response_model=legacy_annotation_tasks.TaskCompletionResponse,
    summary="Complete annotation task",
    description="BFF adapter for the legacy annotation-task completion endpoint.",
)
async def complete_task(
    project_id: UUID,
    annotation_project_id: UUID,
    task_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_tasks.AnnotationTaskServiceDep,
    db: DbSession,
) -> legacy_annotation_tasks.TaskCompletionResponse:
    """Delegate annotation-task completion to the legacy handler."""
    await gate_action(
        action=ANNOTATION_TASK_COMPLETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_tasks.complete_task(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        task_id=task_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
