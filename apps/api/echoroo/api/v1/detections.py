"""Detection annotation management API endpoints."""

from __future__ import annotations

import io
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DetectionStatus
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.detection import (
    ChangeSpeciesRequest,
    ConfirmRequest,
    DetectionCreate,
    DetectionListResponse,
    DetectionResponse,
    DetectionTemporalDataResponse,
    RejectRequest,
    SpeciesSummaryResponse,
)
from echoroo.services.detection import DetectionService
from echoroo.services.detection_export import DetectionExportService

router = APIRouter(prefix="/projects/{project_id}/detections", tags=["detections"])


def get_detection_service(db: DbSession) -> DetectionService:
    """Get DetectionService instance.

    Args:
        db: Database session

    Returns:
        DetectionService instance
    """
    return DetectionService(
        annotation_repo=AnnotationRepository(db),
        confirmed_region_repo=ConfirmedRegionRepository(db),
    )


DetectionServiceDep = Annotated[DetectionService, Depends(get_detection_service)]


@router.get(
    "",
    response_model=DetectionListResponse,
    summary="List detections",
    description="List detection annotations for a project with optional filters",
)
async def list_detections(
    project_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    tag_id: UUID | None = None,
    status: DetectionStatus | None = None,
    confidence_min: float | None = None,
    confidence_max: float | None = None,
    dataset_id: UUID | None = None,
    recording_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> DetectionListResponse:
    """List detection annotations for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Detection service instance
        tag_id: Optional tag filter
        status: Optional review status filter
        confidence_min: Optional minimum confidence filter
        confidence_max: Optional maximum confidence filter
        dataset_id: Optional dataset filter
        recording_id: Optional recording filter
        detection_run_id: Optional detection run filter
        page: Page number (default: 1)
        page_size: Items per page (default: 50)

    Returns:
        Paginated list of detections

    Raises:
        401: Not authenticated
    """
    return await service.list_detections(
        project_id=project_id,
        tag_id=tag_id,
        status=status,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        dataset_id=dataset_id,
        recording_id=recording_id,
        detection_run_id=detection_run_id,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/species-summary",
    response_model=SpeciesSummaryResponse,
    summary="Species detection summary",
    description="Get detection counts and statistics grouped by species tag",
)
async def get_species_summary(
    project_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    locale: str = "en",
) -> SpeciesSummaryResponse:
    """Get species detection summary.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Detection service instance
        dataset_id: Optional dataset filter
        detection_run_id: Optional detection run filter
        locale: Locale code for common name resolution (default: "en")

    Returns:
        Species summary with per-species detection statistics

    Raises:
        401: Not authenticated
    """
    return await service.get_species_summary(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )


@router.get(
    "/export/csv",
    summary="Export detections as CSV",
    description="Export detection annotations as CSV with optional filters",
)
async def export_csv(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    status: DetectionStatus | None = None,
    tag_id: UUID | None = None,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
) -> StreamingResponse:
    """Export detections as a CSV file.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        db: Database session
        status: Optional detection status filter
        tag_id: Optional tag UUID filter
        dataset_id: Optional dataset UUID filter
        detection_run_id: Optional detection run UUID filter

    Returns:
        StreamingResponse with CSV content (text/csv)

    Raises:
        401: Not authenticated
    """
    service = DetectionExportService(db)
    csv_content = await service.export_csv(
        project_id=project_id,
        status=status,
        tag_id=tag_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )
    return StreamingResponse(
        io.BytesIO(csv_content.encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detections.csv"},
    )


@router.get(
    "/export/ml-dataset",
    summary="Export ML training dataset",
    description="Export confirmed detections as a ZIP-archived ML training dataset",
)
async def export_ml_dataset(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
) -> StreamingResponse:
    """Export confirmed detections as a ZIP ML training dataset.

    The archive contains annotations.csv, metadata.json, and README.txt.
    Positive entries are confirmed annotations; negative entries are confirmed
    regions with no overlapping confirmed annotation.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        db: Database session
        dataset_id: Optional dataset UUID filter
        detection_run_id: Optional detection run UUID filter

    Returns:
        StreamingResponse with ZIP content (application/zip)

    Raises:
        401: Not authenticated
    """
    service = DetectionExportService(db)
    zip_content = await service.export_ml_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
    )
    return StreamingResponse(
        io.BytesIO(zip_content),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ml-dataset.zip"},
    )


@router.get(
    "/temporal-data",
    response_model=DetectionTemporalDataResponse,
    summary="Detection temporal data",
    description="Get hourly detection counts grouped by species, date, and hour for visualization",
)
async def get_temporal_data(
    project_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    dataset_id: UUID | None = None,
    detection_run_id: UUID | None = None,
    locale: str = "en",
) -> DetectionTemporalDataResponse:
    """Get temporal detection data for visualization.

    Returns hourly detection counts per species, suitable for heatmap or
    time-series visualizations.

    NOTE: This route must appear before /{detection_id} to avoid routing conflicts.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Detection service instance
        dataset_id: Optional dataset filter
        detection_run_id: Optional detection run filter
        locale: Locale code for common name resolution (default: "en")

    Returns:
        Temporal data response grouped by species with hourly counts

    Raises:
        401: Not authenticated
    """
    return await service.get_temporal_data(
        project_id=project_id,
        dataset_id=dataset_id,
        detection_run_id=detection_run_id,
        locale=locale,
    )


@router.get(
    "/{detection_id}",
    response_model=DetectionResponse,
    summary="Get detection",
    description="Get a detection annotation by ID",
)
async def get_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
) -> DetectionResponse:
    """Get detection by ID.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        current_user: Current authenticated user
        service: Detection service instance

    Returns:
        Detection annotation detail

    Raises:
        401: Not authenticated
        404: Detection not found
    """
    return await service.get(detection_id=detection_id)


@router.post(
    "",
    response_model=DetectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create detection",
    description="Create a new detection annotation",
)
async def create_detection(
    project_id: UUID,
    request: DetectionCreate,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> DetectionResponse:
    """Create a new detection annotation.

    Args:
        project_id: Project's UUID
        request: Detection creation data
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Created detection annotation

    Raises:
        401: Not authenticated
        422: Validation error
    """
    detection = await service.create(project_id=project_id, request=request)
    await db.commit()
    return detection


@router.post(
    "/{detection_id}/confirm",
    response_model=DetectionResponse,
    summary="Confirm detection",
    description="Confirm a detection annotation and create a confirmed region",
)
async def confirm_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    request: ConfirmRequest | None = None,
) -> DetectionResponse:
    """Confirm a detection annotation.

    Sets the status to confirmed, records the reviewer, and creates a
    ConfirmedRegion for the confirmed time range.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Confirm request with time range
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        404: Detection not found
    """
    detection = await service.confirm(
        detection_id=detection_id,
        user_id=current_user.id,
        request=request,
    )
    await db.commit()
    return detection


@router.post(
    "/{detection_id}/reject",
    response_model=DetectionResponse,
    summary="Reject detection",
    description="Reject a detection annotation",
)
async def reject_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
    request: RejectRequest | None = None,  # noqa: ARG001
) -> DetectionResponse:
    """Reject a detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Reject request (no additional fields required)
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        404: Detection not found
    """
    detection = await service.reject(
        detection_id=detection_id,
        user_id=current_user.id,
    )
    await db.commit()
    return detection


@router.post(
    "/{detection_id}/change-species",
    response_model=DetectionResponse,
    summary="Change species",
    description="Change the species tag of a detection annotation",
)
async def change_species(
    project_id: UUID,
    detection_id: UUID,
    request: ChangeSpeciesRequest,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> DetectionResponse:
    """Change the species tag of a detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        request: Change species request with new tag and optional time range
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Returns:
        Updated detection annotation

    Raises:
        401: Not authenticated
        404: Detection not found
    """
    detection = await service.change_species(
        detection_id=detection_id,
        request=request,
        user_id=current_user.id,
    )
    await db.commit()
    return detection


@router.delete(
    "/{detection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete detection",
    description="Delete a detection annotation by ID",
)
async def delete_detection(
    project_id: UUID,
    detection_id: UUID,
    current_user: CurrentUser,
    service: DetectionServiceDep,
    db: DbSession,
) -> None:
    """Delete detection annotation.

    Args:
        project_id: Project's UUID
        detection_id: Detection's UUID
        current_user: Current authenticated user
        service: Detection service instance
        db: Database session

    Raises:
        401: Not authenticated
        404: Detection not found
    """
    await service.delete(detection_id=detection_id)
    await db.commit()
