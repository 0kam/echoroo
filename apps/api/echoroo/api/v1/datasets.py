"""Datasets API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DatasetStatus, DatasetVisibility
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.site import SiteRepository
from echoroo.schemas.dataset import (
    DatasetCreate,
    DatasetDetailResponse,
    DatasetListResponse,
    DatasetResponse,
    DatasetStatisticsResponse,
    DatasetUpdate,
    DirectoryListResponse,
    ImportRequest,
    ImportStatusResponse,
)
from echoroo.services.audio import AudioService
from echoroo.services.dataset import DatasetService
from echoroo.services.export import ExportService

router = APIRouter(prefix="/projects/{project_id}/datasets", tags=["datasets"])

settings = get_settings()


def get_audio_service() -> AudioService:
    """Get AudioService instance.

    Returns:
        AudioService instance
    """
    return AudioService(settings.AUDIO_ROOT, settings.AUDIO_CACHE_DIR)


def get_dataset_service(
    db: DbSession, audio_service: AudioService = Depends(get_audio_service)
) -> DatasetService:
    """Get DatasetService instance.

    Args:
        db: Database session
        audio_service: Audio service instance

    Returns:
        DatasetService instance
    """
    return DatasetService(
        DatasetRepository(db),
        SiteRepository(db),
        ProjectRepository(db),
        RecordingRepository(db),
        audio_service,
    )


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]
DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]


# T044: CRUD endpoints
@router.get(
    "",
    response_model=DatasetListResponse,
    summary="List datasets",
    description="Get all datasets for a project with pagination and filters",
)
async def list_datasets(
    project_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    page: int = 1,
    page_size: int = 20,
    site_id: UUID | None = None,
    status_filter: DatasetStatus | None = None,
    visibility: DatasetVisibility | None = None,
    search: str | None = None,
) -> DatasetListResponse:
    """List datasets for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Dataset service instance
        page: Page number (default: 1)
        page_size: Items per page (default: 20, max: 100)
        site_id: Filter by site ID
        status_filter: Filter by status
        visibility: Filter by visibility
        search: Search in name and description

    Returns:
        Paginated list of datasets

    Raises:
        401: Not authenticated
        403: Access denied
    """
    datasets, total = await service.list_by_project(
        current_user.id,
        project_id,
        page,
        page_size,
        site_id,
        status_filter,
        visibility,
        search,
    )
    pages = (total + page_size - 1) // page_size

    return DatasetListResponse(
        items=[DatasetResponse.model_validate(d) for d in datasets],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.post(
    "",
    response_model=DatasetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create dataset",
    description="Create a new dataset in a project (admin only)",
)
async def create_dataset(
    project_id: UUID,
    request: DatasetCreate,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> DatasetDetailResponse:
    """Create a new dataset.

    Args:
        project_id: Project's UUID
        request: Dataset creation data
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Created dataset

    Raises:
        400: Invalid request data
        401: Not authenticated
        403: Not project admin
        404: Site not found
        409: Duplicate dataset name
    """
    dataset = await service.create(
        user_id=current_user.id,
        project_id=project_id,
        site_id=request.site_id,
        name=request.name,
        description=request.description,
        audio_dir=request.audio_dir,
        visibility=request.visibility,
        recorder_id=request.recorder_id,
        license_id=request.license_id,
        doi=request.doi,
        gain=request.gain,
        note=request.note,
        datetime_pattern=request.datetime_pattern,
        datetime_format=request.datetime_format,
    )
    await db.commit()

    # Build detail response
    response = DatasetDetailResponse.model_validate(dataset)

    # Add computed fields (empty for new dataset)
    response.recording_count = 0
    response.total_duration = 0.0
    response.start_date = None
    response.end_date = None

    return response


@router.get(
    "/{dataset_id}",
    response_model=DatasetDetailResponse,
    summary="Get dataset",
    description="Get dataset details with statistics",
)
async def get_dataset(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> DatasetDetailResponse:
    """Get dataset by ID.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Dataset details with statistics

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    dataset = await service.get_by_id(current_user.id, project_id, dataset_id)

    # Build detail response
    response = DatasetDetailResponse.model_validate(dataset)

    # Get statistics
    stats = await service.get_statistics(db, dataset_id)

    response.recording_count = stats["recording_count"]
    response.total_duration = stats["total_duration"]
    response.start_date = stats["date_range"]["start"] if stats["date_range"] else None
    response.end_date = stats["date_range"]["end"] if stats["date_range"] else None

    return response


@router.patch(
    "/{dataset_id}",
    response_model=DatasetDetailResponse,
    summary="Update dataset",
    description="Update dataset settings (admin only)",
)
async def update_dataset(
    project_id: UUID,
    dataset_id: UUID,
    request: DatasetUpdate,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> DatasetDetailResponse:
    """Update dataset.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        request: Update data
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Updated dataset

    Raises:
        401: Not authenticated
        403: Not project admin
        404: Dataset not found
        409: Duplicate dataset name
    """
    dataset = await service.update(
        user_id=current_user.id,
        project_id=project_id,
        dataset_id=dataset_id,
        name=request.name,
        description=request.description,
        visibility=request.visibility,
        recorder_id=request.recorder_id,
        license_id=request.license_id,
        doi=request.doi,
        gain=request.gain,
        note=request.note,
        datetime_pattern=request.datetime_pattern,
        datetime_format=request.datetime_format,
    )
    await db.commit()

    # Build detail response
    response = DatasetDetailResponse.model_validate(dataset)

    # Get statistics
    stats = await service.get_statistics(db, dataset_id)

    response.recording_count = stats["recording_count"]
    response.total_duration = stats["total_duration"]
    response.start_date = stats["date_range"]["start"] if stats["date_range"] else None
    response.end_date = stats["date_range"]["end"] if stats["date_range"] else None

    return response


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete dataset",
    description="Delete dataset and all associated recordings (admin only)",
)
async def delete_dataset(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> None:
    """Delete dataset.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Not project admin
        404: Dataset not found
    """
    await service.delete(current_user.id, project_id, dataset_id)
    await db.commit()


# T045: Import endpoints
@router.post(
    "/{dataset_id}/import",
    response_model=ImportStatusResponse,
    summary="Start dataset import",
    description="Start importing recordings from audio directory",
)
async def start_import(
    project_id: UUID,
    dataset_id: UUID,
    request: ImportRequest,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> ImportStatusResponse:
    """Start dataset import.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        request: Import request with optional datetime patterns
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Import status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    # Get dataset to verify access
    dataset = await service.get_by_id(current_user.id, project_id, dataset_id)

    # Start import (synchronous for now, should be async with Celery in production)
    await service.start_import(
        db,
        dataset_id,
        request.datetime_pattern,
        request.datetime_format,
    )

    # Refresh dataset to get updated status
    await db.refresh(dataset)

    # Get import status
    status_dict = service.get_import_status(dataset)

    return ImportStatusResponse(
        status=status_dict["status"],
        total_files=status_dict["total_files"],
        processed_files=status_dict["processed_files"],
        progress_percent=status_dict["progress_percent"],
        error=status_dict["error"],
    )


@router.post(
    "/{dataset_id}/rescan",
    response_model=ImportStatusResponse,
    summary="Rescan dataset directory",
    description="Rescan directory for new audio files and add them to dataset",
)
async def rescan_dataset(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> ImportStatusResponse:
    """Rescan directory for new files.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Import status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    # Get dataset to verify access
    dataset = await service.get_by_id(current_user.id, project_id, dataset_id)

    # Start rescan
    await service.rescan(db, dataset_id)

    # Refresh dataset to get updated status
    await db.refresh(dataset)

    # Get import status
    status_dict = service.get_import_status(dataset)

    return ImportStatusResponse(
        status=status_dict["status"],
        total_files=status_dict["total_files"],
        processed_files=status_dict["processed_files"],
        progress_percent=status_dict["progress_percent"],
        error=status_dict["error"],
    )


@router.get(
    "/{dataset_id}/import-status",
    response_model=ImportStatusResponse,
    summary="Get import status",
    description="Get current import/processing status of dataset",
)
async def get_import_status(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
) -> ImportStatusResponse:
    """Get import status.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance

    Returns:
        Import status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    dataset = await service.get_by_id(current_user.id, project_id, dataset_id)

    status_dict = service.get_import_status(dataset)

    return ImportStatusResponse(
        status=status_dict["status"],
        total_files=status_dict["total_files"],
        processed_files=status_dict["processed_files"],
        progress_percent=status_dict["progress_percent"],
        error=status_dict["error"],
    )


# T046: Statistics endpoint
@router.get(
    "/{dataset_id}/statistics",
    response_model=DatasetStatisticsResponse,
    summary="Get dataset statistics",
    description="Get detailed statistics about dataset recordings",
)
async def get_dataset_statistics(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> DatasetStatisticsResponse:
    """Get dataset statistics.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Dataset statistics

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    # Verify access
    await service.get_by_id(current_user.id, project_id, dataset_id)

    # Get statistics
    stats = await service.get_statistics(db, dataset_id)

    return DatasetStatisticsResponse(
        recording_count=stats["recording_count"],
        total_duration=stats["total_duration"],
        date_range=stats["date_range"],
        samplerate_distribution=stats["samplerate_distribution"],
        format_distribution=stats["format_distribution"],
        recordings_by_date=stats["recordings_by_date"],
        recordings_by_hour=stats["recordings_by_hour"],
    )


# T047: Directory listing endpoint
@router.get(
    "/directories/list",
    response_model=DirectoryListResponse,
    summary="List audio directories",
    description="List available audio directories for import",
)
async def list_directories(
    project_id: UUID,
    current_user: CurrentUser,
    audio_service: AudioServiceDep,
    path: str = "",
) -> DirectoryListResponse:
    """List audio directories for import.

    Args:
        project_id: Project's UUID (for auth check)
        current_user: Current authenticated user
        audio_service: Audio service instance
        path: Relative path to list (default: root)

    Returns:
        Directory listing

    Raises:
        401: Not authenticated
        403: Access denied
    """
    # List directories
    directories = audio_service.list_directories(path)

    return DirectoryListResponse(path=path, directories=directories)


# T106: Export endpoint
@router.get(
    "/{dataset_id}/export",
    summary="Export dataset",
    description="Export dataset in CamtrapDP format as a ZIP file",
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP file containing dataset export",
        }
    },
)
async def export_dataset(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    audio_service: AudioServiceDep,
    include_audio: bool = False,
) -> StreamingResponse:
    """Export dataset in CamtrapDP format.

    Generates a ZIP file containing:
    - datapackage.json: Dataset metadata
    - deployments.csv: Deployment information
    - media.csv: Recording metadata
    - data/: Audio files (if include_audio=true)

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        db: Database session
        audio_service: Audio service instance
        include_audio: Whether to include audio files (default: False)

    Returns:
        Streaming ZIP file

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    export_service = ExportService(db, audio_service)

    try:
        # Get dataset name for filename
        dataset_repo = DatasetRepository(db)
        dataset = await dataset_repo.get_by_id(dataset_id)
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")

        # Check project access
        if dataset.project_id != project_id:
            raise HTTPException(status_code=404, detail="Dataset not found")

        # Generate safe filename
        safe_name = dataset.name.replace(" ", "_").replace("/", "_")
        filename = f"{safe_name}_export.zip"

        return StreamingResponse(
            export_service.export_dataset_zip(dataset_id, include_audio),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
