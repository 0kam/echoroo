"""Detection run management API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from echoroo.core.actions import (
    DETECTION_RUN_CANCEL_ACTION,
    DETECTION_RUN_CREATE_ACTION,
    DETECTION_RUN_GET_ACTION,
    DETECTION_RUN_LIST_ACTION,
    DETECTION_RUN_RETRY_ACTION,
    DETECTION_RUN_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.schemas.detection_run import (
    AvailableModelsResponse,
    DetectionRunCreate,
    DetectionRunListResponse,
    DetectionRunResponse,
    DetectionRunUpdate,
)
from echoroo.services.detection_run import DetectionRunService

router = APIRouter(prefix="/projects/{project_id}/detection-runs", tags=["Programmatic API — Detection Runs"])

# Router for model discovery (no project_id prefix needed)
models_router = APIRouter(prefix="/detection-runs", tags=["Programmatic API — Detection Runs"])



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


# W2-3 PR-14: the browser-facing ``GET /projects/{project_id}/detection-runs``
# route was unmounted in favour of the ``/web-api/v1/.../detection-runs`` BFF
# (``echoroo.api.web_v1.projects._detection_runs.list_detection_runs``), which
# imports this handler directly. Only the ``@router`` decorator is removed here;
# the handler survives as an importable helper.
async def list_detection_runs(
    project_id: UUID,
    request: Request,
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
    await gate_action(
        action=DETECTION_RUN_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
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
    request: Request,
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
    await gate_action(
        action=DETECTION_RUN_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get(run_id=run_id, project_id=project_id)


# W2-3 PR-14: the browser-facing ``POST /projects/{project_id}/detection-runs``
# route was unmounted in favour of the ``/web-api/v1/.../detection-runs`` BFF
# (``echoroo.api.web_v1.projects._detection_runs.create_detection_run``). Only the
# ``@router`` decorator is removed here; the handler survives as an importable helper.
async def create_detection_run(
    project_id: UUID,
    request: DetectionRunCreate,
    http_request: Request,
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
    await gate_action(
        action=DETECTION_RUN_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    # Note: service.create() already commits before dispatching the Celery task
    # to avoid a race condition. Do NOT commit again here.
    run = await service.create(project_id=project_id, request=request)
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
    http_request: Request,
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
    await gate_action(
        action=DETECTION_RUN_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    run = await service.update(run_id=run_id, request=request, project_id=project_id)
    await db.commit()
    return run


# W2-3 PR-14: the browser-facing ``POST /projects/{project_id}/detection-runs/
# {run_id}/retry`` route was unmounted in favour of the ``/web-api/v1/.../retry``
# BFF (``echoroo.api.web_v1.projects._detection_runs.retry_detection_run``). Only
# the ``@router`` decorator is removed here; the handler survives as an importable
# helper.
async def retry_detection_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
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
    await gate_action(
        action=DETECTION_RUN_RETRY_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    run = await service.retry(project_id=project_id, run_id=run_id)
    await db.commit()
    return run


# W2-3 PR-14: the browser-facing ``POST /projects/{project_id}/detection-runs/
# {run_id}/cancel`` route was unmounted in favour of the ``/web-api/v1/.../cancel``
# BFF (``echoroo.api.web_v1.projects._detection_runs.cancel_detection_run``). Only
# the ``@router`` decorator is removed here; the handler survives as an importable
# helper.
async def cancel_detection_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
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
    await gate_action(
        action=DETECTION_RUN_CANCEL_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    run = await service.cancel(project_id=project_id, run_id=run_id)
    await db.commit()
    return run


# W2-3 PR-14: the browser-facing ``GET /detection-runs/available-models`` route
# was unmounted in favour of the ``/web-api/v1/detection-runs/available-models``
# BFF (``echoroo.api.web_v1.detection_runs.get_available_models``), which imports
# this handler directly. Only the ``@models_router`` decorator is removed here;
# ``models_router`` is now route-less but kept as an orphan for import stability.
async def list_available_models(
    current_user: CurrentUser,
) -> AvailableModelsResponse:
    """List all detection models available for use.

    Imports registered model modules to ensure all models are registered
    before querying the ModelRegistry.

    Args:
        current_user: Current authenticated user

    Returns:
        List of available model names

    Raises:
        401: Not authenticated
    """
    # Import model packages to trigger their __init__.py registration side-effects
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.ml.registry import ModelRegistry

    return AvailableModelsResponse(models=ModelRegistry.available_models())
