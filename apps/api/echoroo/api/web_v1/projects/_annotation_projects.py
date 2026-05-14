"""Project annotation-project BFF adapters.

Spec/009 PR D needs the annotation task screen to load before export and
batch-tag actions can be smoked in the browser. Keep these routes thin and
delegate schema validation, permissions, and service behavior to the legacy
project-scoped handlers.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import annotation_projects as legacy_annotation_projects
from echoroo.core.actions import (
    ANNOTATION_PROJECT_CREATE_ACTION,
    ANNOTATION_PROJECT_DELETE_ACTION,
    ANNOTATION_PROJECT_GENERATE_TASKS_ACTION,
    ANNOTATION_PROJECT_GET_ACTION,
    ANNOTATION_PROJECT_LIST_ACTION,
    ANNOTATION_PROJECT_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser

router = APIRouter()


@router.get(
    "/{project_id}/annotation-projects",
    response_model=legacy_annotation_projects.AnnotationProjectListResponse,
    summary="List annotation projects",
    description="BFF adapter for the legacy project annotation-project list.",
)
async def list_annotation_projects(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_projects.AnnotationProjectServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> legacy_annotation_projects.AnnotationProjectListResponse:
    """Delegate annotation-project listing to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_projects.list_annotation_projects(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{project_id}/annotation-projects",
    response_model=legacy_annotation_projects.AnnotationProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation project",
    description="BFF adapter for the legacy annotation-project create endpoint.",
)
async def create_annotation_project(
    project_id: UUID,
    request: legacy_annotation_projects.AnnotationProjectCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_projects.AnnotationProjectServiceDep,
    db: DbSession,
) -> legacy_annotation_projects.AnnotationProjectDetailResponse:
    """Delegate annotation-project creation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_projects.create_annotation_project(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/annotation-projects/{annotation_project_id}",
    response_model=legacy_annotation_projects.AnnotationProjectDetailResponse,
    summary="Get annotation project",
    description="BFF adapter for the legacy annotation-project detail endpoint.",
)
async def get_annotation_project(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_projects.AnnotationProjectServiceDep,
    db: DbSession,
) -> legacy_annotation_projects.AnnotationProjectDetailResponse:
    """Delegate annotation-project detail reads to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_projects.get_annotation_project(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.patch(
    "/{project_id}/annotation-projects/{annotation_project_id}",
    response_model=legacy_annotation_projects.AnnotationProjectDetailResponse,
    summary="Update annotation project",
    description="BFF adapter for the legacy annotation-project update endpoint.",
)
async def update_annotation_project(
    project_id: UUID,
    annotation_project_id: UUID,
    request: legacy_annotation_projects.AnnotationProjectUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_projects.AnnotationProjectServiceDep,
    db: DbSession,
) -> legacy_annotation_projects.AnnotationProjectDetailResponse:
    """Delegate annotation-project updates to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_projects.update_annotation_project(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/annotation-projects/{annotation_project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete annotation project",
    description="BFF adapter for the legacy annotation-project delete endpoint.",
)
async def delete_annotation_project(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_projects.AnnotationProjectServiceDep,
    db: DbSession,
) -> None:
    """Delegate annotation-project deletion to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_annotation_projects.delete_annotation_project(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/annotation-projects/{annotation_project_id}/generate-tasks",
    response_model=legacy_annotation_projects.TaskGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate annotation tasks",
    description="BFF adapter for the legacy annotation-task generation endpoint.",
)
async def generate_tasks(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_annotation_projects.AnnotationProjectServiceDep,
    db: DbSession,
) -> legacy_annotation_projects.TaskGenerationResponse:
    """Delegate task generation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_GENERATE_TASKS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_projects.generate_tasks(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
