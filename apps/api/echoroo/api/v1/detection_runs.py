"""Detection run management API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.detection_run import (
    DetectionRunCreate,
    DetectionRunListResponse,
    DetectionRunResponse,
    DetectionRunUpdate,
)
from echoroo.services.detection_run import DetectionRunService

router = APIRouter(prefix="/projects/{project_id}/detection-runs", tags=["detection-runs"])


async def check_project_access(project_id: UUID, user_id: UUID, db: DbSession) -> None:
    """Check if user has access to project.

    Args:
        project_id: Project's UUID
        user_id: User's UUID
        db: Database session

    Raises:
        HTTPException: If user doesn't have access to project
    """
    project_repo = ProjectRepository(db)
    has_access = await project_repo.has_project_access(project_id, user_id)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to project",
        )


def get_detection_run_service(db: DbSession) -> DetectionRunService:
    """Get DetectionRunService instance.

    Args:
        db: Database session

    Returns:
        DetectionRunService instance
    """
    return DetectionRunService(
        detection_run_repo=DetectionRunRepository(db),
        annotation_repo=AnnotationRepository(db),
    )


DetectionRunServiceDep = Annotated[DetectionRunService, Depends(get_detection_run_service)]


@router.get(
    "",
    response_model=DetectionRunListResponse,
    summary="List detection runs",
    description="List detection runs for a project",
)
async def list_detection_runs(
    project_id: UUID,
    current_user: CurrentUser,
    service: DetectionRunServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 50,
    dataset_id: UUID | None = None,
) -> DetectionRunListResponse:
    """List detection runs for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Detection run service instance
        db: Database session
        page: Page number (default: 1)
        page_size: Items per page (default: 50)
        dataset_id: Optional filter by dataset ID

    Returns:
        Paginated list of detection runs

    Raises:
        401: Not authenticated
        403: Access denied
    """
    await check_project_access(project_id, current_user.id, db)
    return await service.list_by_project(
        project_id=project_id,
        page=page,
        page_size=page_size,
        dataset_id=dataset_id,
    )


@router.get(
    "/{run_id}",
    response_model=DetectionRunResponse,
    summary="Get detection run",
    description="Get a detection run by ID",
)
async def get_detection_run(
    project_id: UUID,
    run_id: UUID,
    current_user: CurrentUser,
    service: DetectionRunServiceDep,
    db: DbSession,
) -> DetectionRunResponse:
    """Get detection run by ID.

    Args:
        project_id: Project's UUID
        run_id: DetectionRun's UUID
        current_user: Current authenticated user
        service: Detection run service instance
        db: Database session

    Returns:
        Detection run detail

    Raises:
        401: Not authenticated
        403: Access denied
        404: Detection run not found
    """
    await check_project_access(project_id, current_user.id, db)
    return await service.get(run_id=run_id, project_id=project_id)


@router.post(
    "",
    response_model=DetectionRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create detection run",
    description="Create a new detection run for a project",
)
async def create_detection_run(
    project_id: UUID,
    request: DetectionRunCreate,
    current_user: CurrentUser,
    service: DetectionRunServiceDep,
    db: DbSession,
) -> DetectionRunResponse:
    """Create a new detection run.

    Args:
        project_id: Project's UUID
        request: Detection run creation data
        current_user: Current authenticated user
        service: Detection run service instance
        db: Database session

    Returns:
        Created detection run

    Raises:
        401: Not authenticated
        403: Access denied
        422: Validation error
    """
    await check_project_access(project_id, current_user.id, db)
    run = await service.create(project_id=project_id, request=request)
    await db.commit()
    return run


@router.patch(
    "/{run_id}",
    response_model=DetectionRunResponse,
    summary="Update detection run",
    description="Update detection run status and metadata",
)
async def update_detection_run(
    project_id: UUID,
    run_id: UUID,
    request: DetectionRunUpdate,
    current_user: CurrentUser,
    service: DetectionRunServiceDep,
    db: DbSession,
) -> DetectionRunResponse:
    """Update a detection run.

    Args:
        project_id: Project's UUID
        run_id: DetectionRun's UUID
        request: Update data (status, annotation_count, error_message)
        current_user: Current authenticated user
        service: Detection run service instance
        db: Database session

    Returns:
        Updated detection run

    Raises:
        401: Not authenticated
        403: Access denied
        404: Detection run not found
    """
    await check_project_access(project_id, current_user.id, db)
    run = await service.update(run_id=run_id, request=request, project_id=project_id)
    await db.commit()
    return run


@router.post(
    "/{run_id}/retry",
    response_model=DetectionRunResponse,
    summary="Retry detection run",
    description="Retry a completed or failed detection run. Deletes existing annotations and re-queues the detection task.",
)
async def retry_detection_run(
    project_id: UUID,
    run_id: UUID,
    current_user: CurrentUser,
    service: DetectionRunServiceDep,
    db: DbSession,
) -> DetectionRunResponse:
    """Retry a completed or failed detection run.

    Deletes all existing annotations for the run, resets the run to PENDING,
    and re-queues the Celery detection task.

    Args:
        project_id: Project's UUID
        run_id: DetectionRun's UUID
        current_user: Current authenticated user
        service: Detection run service instance
        db: Database session

    Returns:
        Updated detection run with PENDING status

    Raises:
        401: Not authenticated
        404: Detection run not found
        409: Detection run status does not allow retry (not COMPLETED or FAILED)
    """
    await check_project_access(project_id, current_user.id, db)
    run = await service.retry(project_id=project_id, run_id=run_id)
    await db.commit()
    return run


@router.post(
    "/{run_id}/cancel",
    response_model=DetectionRunResponse,
    summary="Cancel detection run",
    description="Cancel a pending or running detection run.",
)
async def cancel_detection_run(
    project_id: UUID,
    run_id: UUID,
    current_user: CurrentUser,
    service: DetectionRunServiceDep,
    db: DbSession,
) -> DetectionRunResponse:
    """Cancel a pending or running detection run.

    Sets the run status to FAILED with a cancellation message. The Celery
    worker will stop processing when it detects the cancellation.

    Args:
        project_id: Project's UUID
        run_id: DetectionRun's UUID
        current_user: Current authenticated user
        service: Detection run service instance
        db: Database session

    Returns:
        Updated detection run with FAILED status and cancellation message

    Raises:
        401: Not authenticated
        404: Detection run not found
        409: Detection run status does not allow cancellation (not PENDING or RUNNING)
    """
    await check_project_access(project_id, current_user.id, db)
    run = await service.cancel(project_id=project_id, run_id=run_id)
    await db.commit()
    return run
