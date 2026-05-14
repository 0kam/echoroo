"""Project detection read BFF adapters."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request

from echoroo.api.v1 import detections as legacy_detections
from echoroo.core.actions import DETECTION_LIST_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DetectionStatus

router = APIRouter()


@router.get(
    "/{project_id}/detections",
    response_model=legacy_detections.DetectionListResponse,
    summary="List detections",
    description="BFF adapter for the legacy project detection list endpoint.",
)
async def list_detections(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_detections.DetectionServiceDep,
    db: DbSession,
    tag_id: UUID | None = None,
    status: DetectionStatus | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    dataset_id: UUID | None = None,
    recording_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
    locale: str = Query("en", pattern="^(en|ja)$"),
) -> legacy_detections.DetectionListResponse:
    """Delegate detection listing to the legacy handler."""
    await gate_action(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.list_detections(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        tag_id=tag_id,
        status=status,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        dataset_id=dataset_id,
        recording_id=recording_id,
        detection_run_id=detection_run_id,
        page=page,
        page_size=page_size,
        locale=locale,
    )


@router.get(
    "/{project_id}/detections/species-summary",
    response_model=legacy_detections.SpeciesSummaryResponse,
    summary="Get species detection summary",
    description="BFF adapter for the legacy species detection summary endpoint.",
)
async def get_species_summary(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_detections.DetectionServiceDep,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    locale: str = Query("en", pattern="^(en|ja)$"),
) -> legacy_detections.SpeciesSummaryResponse:
    """Delegate species-summary reads to the legacy handler."""
    await gate_action(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.get_species_summary(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )


@router.get(
    "/{project_id}/detections/temporal-data",
    response_model=legacy_detections.DetectionTemporalDataResponse,
    summary="Get detection temporal data",
    description="BFF adapter for the legacy detection temporal-data endpoint.",
)
async def get_temporal_data(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_detections.DetectionServiceDep,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    locale: str = Query("en", pattern="^(en|ja)$"),
) -> legacy_detections.DetectionTemporalDataResponse:
    """Delegate temporal detection reads to the legacy handler."""
    await gate_action(
        action=DETECTION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.get_temporal_data(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )
