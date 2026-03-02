"""Detection run management API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.schemas.detection_run import (
    DetectionRunCreate,
    DetectionRunListResponse,
    DetectionRunResponse,
    DetectionRunUpdate,
)
from echoroo.services.detection_run import DetectionRunService

router = APIRouter(prefix="/projects/{project_id}/detection-runs", tags=["detection-runs"])


def get_detection_run_service(db: DbSession) -> DetectionRunService:
    """Get DetectionRunService instance.

    Args:
        db: Database session

    Returns:
        DetectionRunService instance
    """
    return DetectionRunService(detection_run_repo=DetectionRunRepository(db))


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
    page: int = 1,
    page_size: int = 50,
) -> DetectionRunListResponse:
    """List detection runs for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Detection run service instance
        page: Page number (default: 1)
        page_size: Items per page (default: 50)

    Returns:
        Paginated list of detection runs

    Raises:
        401: Not authenticated
    """
    return await service.list_by_project(
        project_id=project_id,
        page=page,
        page_size=page_size,
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
) -> DetectionRunResponse:
    """Get detection run by ID.

    Args:
        project_id: Project's UUID
        run_id: DetectionRun's UUID
        current_user: Current authenticated user
        service: Detection run service instance

    Returns:
        Detection run detail

    Raises:
        401: Not authenticated
        404: Detection run not found
    """
    return await service.get(run_id=run_id)


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
        422: Validation error
    """
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
        404: Detection run not found
    """
    run = await service.update(run_id=run_id, request=request)
    await db.commit()
    return run
