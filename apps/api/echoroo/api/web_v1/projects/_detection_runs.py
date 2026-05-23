"""Project detection-run BFF adapters used by dataset status panels.

Spec/009 PR 2 keeps the browser-facing detection-run lifecycle endpoints
(``create`` / ``retry`` / ``cancel``) as thin adapters: the legacy
``/api/v1`` handlers own schema validation, service orchestration, and
Celery task dispatch. This module only exposes the same behaviour on the
first-party session surface.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import detection_runs as legacy_detection_runs
from echoroo.core.actions import (
    DETECTION_RUN_CANCEL_ACTION,
    DETECTION_RUN_CREATE_ACTION,
    DETECTION_RUN_LIST_ACTION,
    DETECTION_RUN_RETRY_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser

router = APIRouter()


@router.get(
    "/{project_id}/detection-runs",
    response_model=legacy_detection_runs.DetectionRunListResponse,
    summary="List detection runs",
    description="BFF adapter for the legacy project detection-run list endpoint.",
)
async def list_detection_runs(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_detection_runs.DetectionRunServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 50,
    dataset_id: UUID | None = None,
) -> legacy_detection_runs.DetectionRunListResponse:
    """Delegate detection-run listing to the legacy handler."""
    await gate_action(
        action=DETECTION_RUN_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detection_runs.list_detection_runs(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        page=page,
        page_size=page_size,
        dataset_id=dataset_id,
    )


@router.post(
    "/{project_id}/detection-runs",
    response_model=legacy_detection_runs.DetectionRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create detection run",
    description="BFF adapter for the legacy project detection-run create endpoint.",
)
async def create_detection_run(
    project_id: UUID,
    request: legacy_detection_runs.DetectionRunCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_detection_runs.DetectionRunServiceDep,
    db: DbSession,
) -> legacy_detection_runs.DetectionRunResponse:
    """Delegate detection-run creation to the legacy handler."""
    await gate_action(
        action=DETECTION_RUN_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_detection_runs.create_detection_run(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/detection-runs/{run_id}/retry",
    response_model=legacy_detection_runs.DetectionRunResponse,
    summary="Retry detection run",
    description="BFF adapter for the legacy project detection-run retry endpoint.",
)
async def retry_detection_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_detection_runs.DetectionRunServiceDep,
    db: DbSession,
) -> legacy_detection_runs.DetectionRunResponse:
    """Delegate detection-run retry to the legacy handler."""
    await gate_action(
        action=DETECTION_RUN_RETRY_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detection_runs.retry_detection_run(
        project_id=project_id,
        run_id=run_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/detection-runs/{run_id}/cancel",
    response_model=legacy_detection_runs.DetectionRunResponse,
    summary="Cancel detection run",
    description="BFF adapter for the legacy project detection-run cancel endpoint.",
)
async def cancel_detection_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_detection_runs.DetectionRunServiceDep,
    db: DbSession,
) -> legacy_detection_runs.DetectionRunResponse:
    """Delegate detection-run cancellation to the legacy handler."""
    await gate_action(
        action=DETECTION_RUN_CANCEL_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detection_runs.cancel_detection_run(
        project_id=project_id,
        run_id=run_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
