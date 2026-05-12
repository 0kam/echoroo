"""Annotation Projects API endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import Response as FastAPIResponse

from echoroo.core.actions import (
    ANNOTATION_PROJECT_CREATE_ACTION,
    ANNOTATION_PROJECT_DELETE_ACTION,
    ANNOTATION_PROJECT_EXPORT_ACTION,
    ANNOTATION_PROJECT_GENERATE_TASKS_ACTION,
    ANNOTATION_PROJECT_GET_ACTION,
    ANNOTATION_PROJECT_LIST_ACTION,
    ANNOTATION_PROJECT_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.annotation_project import AnnotationProjectRepository
from echoroo.repositories.annotation_task import AnnotationTaskRepository
from echoroo.schemas.annotation_project import (
    AnnotationProjectCreate,
    AnnotationProjectDetailResponse,
    AnnotationProjectListResponse,
    AnnotationProjectUpdate,
    TaskGenerationResponse,
)
from echoroo.services.annotation_export import AnnotationExportService
from echoroo.services.annotation_project import AnnotationProjectService

router = APIRouter(
    prefix="/projects/{project_id}/annotation-projects",
    tags=["annotation-projects"],
)


def get_annotation_project_service(db: DbSession) -> AnnotationProjectService:
    """Get AnnotationProjectService instance.

    Args:
        db: Database session

    Returns:
        AnnotationProjectService instance
    """
    return AnnotationProjectService(
        annotation_project_repo=AnnotationProjectRepository(db),
        annotation_task_repo=AnnotationTaskRepository(db),
    )


AnnotationProjectServiceDep = Annotated[
    AnnotationProjectService, Depends(get_annotation_project_service)
]


@router.get(
    "",
    response_model=AnnotationProjectListResponse,
    summary="List annotation projects",
    description="List annotation projects for a project with pagination",
)
async def list_annotation_projects(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: AnnotationProjectServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> AnnotationProjectListResponse:
    """List annotation projects for a project.

    Args:
        project_id: Parent project's UUID
        current_user: Current authenticated user
        service: Annotation project service instance
        page: Page number (default: 1)
        page_size: Items per page (default: 20)

    Returns:
        Paginated list of annotation projects

    Raises:
        401: Not authenticated
    """
    await gate_action(
        action=ANNOTATION_PROJECT_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.list_projects(project_id, page, page_size)


@router.post(
    "",
    response_model=AnnotationProjectDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation project",
    description="Create a new annotation project under a project",
)
async def create_annotation_project(
    project_id: UUID,
    request: AnnotationProjectCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: AnnotationProjectServiceDep,
    db: DbSession,
) -> AnnotationProjectDetailResponse:
    """Create a new annotation project.

    Args:
        project_id: Parent project's UUID
        request: Annotation project creation data
        current_user: Current authenticated user
        service: Annotation project service instance

    Returns:
        Created annotation project with detail response

    Raises:
        401: Not authenticated
    """
    await gate_action(
        action=ANNOTATION_PROJECT_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await service.create(project_id, current_user.id, request)


@router.get(
    "/{annotation_project_id}",
    response_model=AnnotationProjectDetailResponse,
    summary="Get annotation project",
    description="Get annotation project by ID with progress statistics",
)
async def get_annotation_project(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: AnnotationProjectServiceDep,
    db: DbSession,
) -> AnnotationProjectDetailResponse:
    """Get annotation project detail.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        current_user: Current authenticated user
        service: Annotation project service instance

    Returns:
        Annotation project detail with datasets, tags, and progress

    Raises:
        401: Not authenticated
        404: Annotation project not found
    """
    await gate_action(
        action=ANNOTATION_PROJECT_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_detail(annotation_project_id)


@router.patch(
    "/{annotation_project_id}",
    response_model=AnnotationProjectDetailResponse,
    summary="Update annotation project",
    description="Update annotation project fields",
)
async def update_annotation_project(
    project_id: UUID,
    annotation_project_id: UUID,
    request: AnnotationProjectUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: AnnotationProjectServiceDep,
    db: DbSession,
) -> AnnotationProjectDetailResponse:
    """Update an annotation project.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        request: Update data
        current_user: Current authenticated user
        service: Annotation project service instance

    Returns:
        Updated annotation project detail response

    Raises:
        401: Not authenticated
        404: Annotation project not found
    """
    await gate_action(
        action=ANNOTATION_PROJECT_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await service.update(annotation_project_id, request)


@router.delete(
    "/{annotation_project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete annotation project",
    description="Delete an annotation project by ID",
)
async def delete_annotation_project(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: AnnotationProjectServiceDep,
    db: DbSession,
) -> None:
    """Delete an annotation project.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        current_user: Current authenticated user
        service: Annotation project service instance

    Raises:
        401: Not authenticated
        404: Annotation project not found
    """
    await gate_action(
        action=ANNOTATION_PROJECT_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.delete(annotation_project_id)


@router.get(
    "/{annotation_project_id}/export",
    summary="Export annotations",
    description="Export annotation data in JSON, CSV (Raven-compatible), or AOEF format",
)
async def export_annotations(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    format: str = Query("json", description="Export format: json, csv, or aoef"),
) -> Any:
    """Export annotations for an annotation project.

    Supports three output formats:
    - json: Structured JSON with project metadata and annotations array
    - csv: Raven Selection Table-compatible CSV (one row per sound event)
    - aoef: Audio Object Event Format JSON for soundevent library compatibility

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        current_user: Current authenticated user
        db: Database session
        format: Export format (json, csv, or aoef)

    Returns:
        Export data in the requested format

    Raises:
        401: Not authenticated
        404: Annotation project not found
        422: Unsupported export format
    """
    await gate_action(
        action=ANNOTATION_PROJECT_EXPORT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    export_service = AnnotationExportService(db)
    result = await export_service.export_annotations(annotation_project_id, format)

    if format == "csv":
        return FastAPIResponse(
            content=result,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=annotations_{annotation_project_id}.csv"
            },
        )
    return result


@router.post(
    "/{annotation_project_id}/generate-tasks",
    response_model=TaskGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate annotation tasks",
    description=(
        "Generate annotation tasks for all clips in datasets associated with the project. "
        "Skips clips that already have a task for this annotation project."
    ),
)
async def generate_tasks(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: AnnotationProjectServiceDep,
    db: DbSession,
) -> TaskGenerationResponse:
    """Generate annotation tasks from clips in associated datasets.

    For each clip belonging to a dataset linked to the annotation project,
    an AnnotationTask is created if one does not already exist. Returns the
    count of newly created tasks.

    Args:
        project_id: Parent project's UUID
        annotation_project_id: AnnotationProject's UUID
        current_user: Current authenticated user
        service: Annotation project service instance

    Returns:
        TaskGenerationResponse with task ID and count of tasks created

    Raises:
        401: Not authenticated
        404: Annotation project not found
    """
    await gate_action(
        action=ANNOTATION_PROJECT_GENERATE_TASKS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.generate_tasks(annotation_project_id)
