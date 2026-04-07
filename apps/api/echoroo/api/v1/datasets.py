"""Datasets API endpoints."""

import re as _re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import DatasetStatus, DatasetVisibility, UploadSessionStatus
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.site import SiteRepository
from echoroo.repositories.upload import UploadSessionRepository
from echoroo.schemas.dataset import (
    DatasetCreate,
    DatasetDetailResponse,
    DatasetListResponse,
    DatasetResponse,
    DatasetStatisticsResponse,
    DatasetUpdate,
    DatetimeApplyRequest,
    DatetimeApplyResponse,
    DatetimeAutoDetectResponse,
    DatetimeConfigResponse,
    DatetimeParseSummary,
    DatetimeTestRequest,
    DatetimeTestResult,
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


def get_dataset_service(db: DbSession) -> DatasetService:
    """Get DatasetService instance.

    Args:
        db: Database session

    Returns:
        DatasetService instance
    """
    return DatasetService(
        DatasetRepository(db),
        SiteRepository(db),
        ProjectRepository(db),
        RecordingRepository(db),
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
        visibility=request.visibility,
        recorder_id=request.recorder_id,
        license_id=request.license_id,
        doi=request.doi,
        gain=request.gain,
        note=request.note,
        datetime_pattern=request.datetime_pattern,
        datetime_format=request.datetime_format,
        datetime_timezone=request.datetime_timezone,
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
        datetime_timezone=request.datetime_timezone,
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
    description="Start importing recordings from a validated upload session",
)
async def start_import(
    project_id: UUID,
    dataset_id: UUID,
    request: ImportRequest,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> ImportStatusResponse:
    """Start dataset import from a validated upload session.

    The source field must be an 'upload-session://<session_id>' URI.
    Dispatches an async Celery task to perform the import.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        request: Import request with upload-session source and optional datetime patterns
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Import status

    Raises:
        400: Invalid source URI or upload session ID
        401: Not authenticated
        403: Access denied
        404: Dataset or upload session not found
        409: Upload session not in validated state
    """
    # Verify dataset access
    await service.get_by_id(current_user.id, project_id, dataset_id)

    # Admin check
    project_repo = ProjectRepository(db)
    is_admin = await project_repo.is_project_admin(project_id, current_user.id)
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project admins can import from upload sessions",
        )

    upload_session_repo = UploadSessionRepository(db)
    source = request.source

    if source:
        # Explicit source provided
        if not source.startswith("upload-session://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source must be an 'upload-session://<session_id>' URI",
            )

        session_id_str = source.removeprefix("upload-session://")
        try:
            session_uuid = UUID(session_id_str)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid upload session ID") from exc

        upload_session = await upload_session_repo.get_by_id(session_uuid)
        if not upload_session or upload_session.dataset_id != dataset_id:
            raise HTTPException(status_code=404, detail="Upload session not found")
        if upload_session.created_by_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this upload session",
            )
    else:
        # No source: auto-find the latest validated upload session for this dataset
        upload_session = await upload_session_repo.get_active_by_dataset(dataset_id)
        if not upload_session:
            raise HTTPException(
                status_code=404,
                detail="No upload session found for this dataset. Please upload files first.",
            )
        if upload_session.created_by_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this upload session",
            )

    if upload_session.status != UploadSessionStatus.VALIDATED:
        raise HTTPException(
            status_code=409,
            detail=f"Upload session is in '{upload_session.status.value}' state, must be 'validated'",
        )

    # Dispatch async import task
    from echoroo.workers.upload_tasks import import_from_upload_session

    import_from_upload_session.delay(
        str(upload_session.id),
        request.datetime_pattern,
        request.datetime_format,
        request.datetime_timezone,
    )

    return ImportStatusResponse(
        status=DatasetStatus.PROCESSING,
        total_files=upload_session.total_files,
        processed_files=0,
        progress_percent=0.0,
        error=None,
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

        project_repo = ProjectRepository(db)
        has_access = await project_repo.has_project_access(project_id, current_user.id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to project",
            )

        # Generate safe filename (strip characters that break Content-Disposition header)
        safe_name = _re.sub(r'[^a-zA-Z0-9_\-]', '_', dataset.name)
        filename = f"{safe_name}_export.zip"

        return StreamingResponse(
            export_service.export_dataset_zip(dataset_id, include_audio),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# Datetime configuration endpoints


@router.get(
    "/{dataset_id}/datetime-config",
    response_model=DatetimeConfigResponse,
    summary="Get datetime config",
    description="Get datetime parsing configuration and parse status summary for a dataset",
)
async def get_datetime_config(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
) -> DatetimeConfigResponse:
    """Get datetime parsing configuration and status for a dataset.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance

    Returns:
        Datetime config with sample filenames and parse summary

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    # Verify access
    await service.get_by_id(current_user.id, project_id, dataset_id)

    config = await service.get_datetime_config(dataset_id)
    summary_data = config["parse_summary"]
    assert isinstance(summary_data, dict)
    sample_filenames = config["sample_filenames"]
    assert isinstance(sample_filenames, list)

    return DatetimeConfigResponse(
        datetime_pattern=config["datetime_pattern"] if isinstance(config["datetime_pattern"], str) else None,
        datetime_format=config["datetime_format"] if isinstance(config["datetime_format"], str) else None,
        datetime_timezone=config["datetime_timezone"] if isinstance(config["datetime_timezone"], str) else None,
        sample_filenames=sample_filenames,
        parse_summary=DatetimeParseSummary(**summary_data),
    )


@router.post(
    "/{dataset_id}/datetime-config/auto-detect",
    response_model=DatetimeAutoDetectResponse,
    summary="Auto-detect datetime pattern",
    description="Auto-detect datetime pattern from sample filenames in the dataset",
)
async def auto_detect_datetime(
    project_id: UUID,
    dataset_id: UUID,
    current_user: CurrentUser,
    service: DatasetServiceDep,
) -> DatetimeAutoDetectResponse:
    """Auto-detect datetime pattern from sample filenames.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        current_user: Current authenticated user
        service: Dataset service instance

    Returns:
        Auto-detection result with pattern, format, and test results

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    # Verify access
    await service.get_by_id(current_user.id, project_id, dataset_id)

    result = await service.auto_detect_datetime_pattern(dataset_id)
    raw_results = result.get("results", [])
    assert isinstance(raw_results, list)
    pattern_val = result.get("pattern")
    format_str_val = result.get("format_str")
    preset_name_val = result.get("preset_name")

    return DatetimeAutoDetectResponse(
        detected=bool(result["detected"]),
        pattern=pattern_val if isinstance(pattern_val, str) else None,
        format_str=format_str_val if isinstance(format_str_val, str) else None,
        preset_name=preset_name_val if isinstance(preset_name_val, str) else None,
        results=[DatetimeTestResult(**r) for r in raw_results],
    )


@router.post(
    "/{dataset_id}/datetime-config/test",
    response_model=list[DatetimeTestResult],
    summary="Test datetime pattern",
    description="Test a datetime pattern against sample filenames from the dataset",
)
async def test_datetime_pattern(
    project_id: UUID,
    dataset_id: UUID,
    body: DatetimeTestRequest,
    current_user: CurrentUser,
    service: DatasetServiceDep,
) -> list[DatetimeTestResult]:
    """Test a datetime pattern against sample filenames.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        body: Pattern and format string to test
        current_user: Current authenticated user
        service: Dataset service instance

    Returns:
        List of test results per sample filename

    Raises:
        401: Not authenticated
        403: Access denied
        404: Dataset not found
    """
    # Verify access
    await service.get_by_id(current_user.id, project_id, dataset_id)

    sample_filenames = await service.recording_repo.get_sample_filenames(dataset_id)
    results = await service.test_datetime_pattern_bulk(sample_filenames, body.pattern, body.format_str, body.timezone)

    return [DatetimeTestResult(**r) for r in results]


@router.post(
    "/{dataset_id}/datetime-config/apply",
    response_model=DatetimeApplyResponse,
    summary="Apply datetime pattern",
    description="Apply a datetime pattern to all recordings in the dataset (admin only)",
)
async def apply_datetime_pattern(
    project_id: UUID,
    dataset_id: UUID,
    body: DatetimeApplyRequest,
    current_user: CurrentUser,
    service: DatasetServiceDep,
    db: DbSession,
) -> DatetimeApplyResponse:
    """Apply a datetime pattern to all recordings in the dataset.

    Saves the pattern to the dataset and dispatches a Celery task to
    re-parse datetimes for all recordings.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        body: Pattern and format string to apply
        current_user: Current authenticated user
        service: Dataset service instance
        db: Database session

    Returns:
        Task ID and total recording count

    Raises:
        401: Not authenticated
        403: Not project admin
        404: Dataset not found
    """
    # Verify dataset access (also checks project membership)
    await service.get_by_id(current_user.id, project_id, dataset_id)

    # Admin check
    project_repo = ProjectRepository(db)
    is_admin = await project_repo.is_project_admin(project_id, current_user.id)
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project admins can apply datetime patterns",
        )

    task_id, total_recordings = await service.apply_datetime_pattern(
        dataset_id, body.pattern, body.format_str, body.timezone
    )
    await db.commit()

    return DatetimeApplyResponse(task_id=task_id, total_recordings=total_recordings)
