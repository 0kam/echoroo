"""Project detection-run read BFF adapters used by dataset status panels."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from echoroo.api.v1 import detection_runs as legacy_detection_runs
from echoroo.core.database import DbSession
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
