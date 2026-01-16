"""Recordings API endpoints."""

from collections.abc import Generator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.recording import (
    RecordingDetailResponse,
    RecordingListResponse,
    RecordingResponse,
    RecordingUpdate,
)
from echoroo.services.audio import AudioService
from echoroo.services.recording import RecordingService

router = APIRouter(prefix="/projects/{project_id}/recordings", tags=["recordings"])

settings = get_settings()


def get_audio_service() -> AudioService:
    """Get AudioService instance.

    Returns:
        AudioService instance
    """
    return AudioService(settings.AUDIO_ROOT, settings.AUDIO_CACHE_DIR)


def get_recording_service(
    db: DbSession, audio_service: AudioService = Depends(get_audio_service)
) -> RecordingService:
    """Get RecordingService instance.

    Args:
        db: Database session
        audio_service: Audio service instance

    Returns:
        RecordingService instance
    """
    return RecordingService(db, audio_service)


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]
RecordingServiceDep = Annotated[RecordingService, Depends(get_recording_service)]


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


# T060: List and search endpoints
@router.get(
    "",
    response_model=RecordingListResponse,
    summary="List and search recordings",
    description="List/search recordings across project datasets with pagination and filters",
)
async def list_recordings(
    project_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
    dataset_id: UUID | None = None,
    site_id: UUID | None = None,
    search: str | None = None,
    datetime_from: datetime | None = None,
    datetime_to: datetime | None = None,
    samplerate: int | None = None,
    sort_by: str = "datetime",
    sort_order: str = "desc",
) -> RecordingListResponse:
    """List/search recordings across project datasets.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Recording service instance
        page: Page number (default: 1)
        page_size: Items per page (default: 20)
        dataset_id: Filter by specific dataset ID
        site_id: Filter by site ID
        search: Search in filename
        datetime_from: Filter from datetime
        datetime_to: Filter to datetime
        samplerate: Filter by samplerate
        sort_by: Sort column (default: datetime)
        sort_order: Sort order (asc/desc, default: desc)

    Returns:
        Paginated list of recordings

    Raises:
        401: Not authenticated
        403: Access denied
    """
    # Check project access
    await check_project_access(project_id, current_user.id, db)

    if dataset_id:
        # List by specific dataset
        recordings, total = await service.list_by_dataset(
            dataset_id, page, page_size, search, datetime_from, datetime_to, samplerate, sort_by, sort_order
        )
    else:
        # Search across all datasets in project
        recordings, total = await service.search_by_project(
            project_id, page, page_size, search, site_id, dataset_id, datetime_from, datetime_to
        )

    pages = (total + page_size - 1) // page_size

    return RecordingListResponse(
        items=[RecordingResponse.model_validate(r) for r in recordings],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get(
    "/{recording_id}",
    response_model=RecordingDetailResponse,
    summary="Get recording details",
    description="Get recording by ID with details and relationships",
)
async def get_recording(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
) -> RecordingDetailResponse:
    """Get recording by ID with details.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Recording service instance

    Returns:
        Recording details with relationships

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording not found
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    # Build detail response
    clip_count = await service.clip_repo.count_by_recording(recording_id)

    # Build dataset summary
    dataset_summary = None
    if recording.dataset:
        dataset_summary = {
            "id": recording.dataset.id,
            "name": recording.dataset.name,
        }

    # Build site summary
    site_summary = None
    if recording.dataset and recording.dataset.site:
        site_summary = {
            "id": recording.dataset.site.id,
            "name": recording.dataset.site.name,
            "h3_index": recording.dataset.site.h3_index,
        }

    return RecordingDetailResponse(
        **RecordingResponse.model_validate(recording).model_dump(),
        dataset=dataset_summary,
        site=site_summary,
        clip_count=clip_count,
        effective_duration=service.get_effective_duration(recording),
        is_ultrasonic=service.is_ultrasonic(recording),
    )


@router.patch(
    "/{recording_id}",
    response_model=RecordingDetailResponse,
    summary="Update recording",
    description="Update recording fields (time_expansion, note)",
)
async def update_recording(
    project_id: UUID,
    recording_id: UUID,
    request: RecordingUpdate,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
) -> RecordingDetailResponse:
    """Update recording (time_expansion, note).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: Update data
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session

    Returns:
        Updated recording with details

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording not found
    """
    recording = await service.update(
        recording_id,
        time_expansion=request.time_expansion,
        note=request.note,
    )
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    await db.commit()

    # Build detail response
    clip_count = await service.clip_repo.count_by_recording(recording_id)

    # Build dataset summary
    dataset_summary = None
    if recording.dataset:
        dataset_summary = {
            "id": recording.dataset.id,
            "name": recording.dataset.name,
        }

    # Build site summary
    site_summary = None
    if recording.dataset and recording.dataset.site:
        site_summary = {
            "id": recording.dataset.site.id,
            "name": recording.dataset.site.name,
            "h3_index": recording.dataset.site.h3_index,
        }

    return RecordingDetailResponse(
        **RecordingResponse.model_validate(recording).model_dump(),
        dataset=dataset_summary,
        site=site_summary,
        clip_count=clip_count,
        effective_duration=service.get_effective_duration(recording),
        is_ultrasonic=service.is_ultrasonic(recording),
    )


@router.delete(
    "/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete recording",
    description="Delete recording and associated clips",
)
async def delete_recording(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
) -> None:
    """Delete recording.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording not found
    """
    if not await service.delete(recording_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    await db.commit()


# T061: Audio streaming with HTTP Range support
@router.get(
    "/{recording_id}/stream",
    summary="Stream audio file",
    description="Stream original audio file with HTTP Range support for seeking",
)
async def stream_audio(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
) -> StreamingResponse:
    """Stream original audio file with HTTP Range support.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Recording service instance

    Returns:
        Streaming response with audio file

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording or audio file not found
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio service not configured"
        )

    file_path = service.audio_service.get_absolute_path(recording.path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found")

    def iter_file() -> Generator[bytes, None, None]:
        """Iterate over file chunks."""
        with open(file_path, "rb") as f:
            yield from f

    # Get file size and mime type
    import mimetypes

    mime_type, _ = mimetypes.guess_type(str(file_path))
    file_size = file_path.stat().st_size

    return StreamingResponse(
        iter_file(),
        media_type=mime_type or "audio/wav",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )


# T062: Playback endpoint with resampling
@router.get(
    "/{recording_id}/playback",
    summary="Get playback audio",
    description="Get audio resampled for browser playback (48kHz WAV)",
)
async def get_playback_audio(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    speed: float = 1.0,
    start: float | None = None,
    end: float | None = None,
) -> Response:
    """Get audio resampled for browser playback (48kHz WAV).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Recording service instance
        speed: Playback speed multiplier (default: 1.0)
        start: Start time in seconds
        end: End time in seconds

    Returns:
        WAV audio file response

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording not found
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio service not configured"
        )

    # For ultrasonic recordings, adjust speed for audible playback
    effective_speed = speed
    if service.is_ultrasonic(recording):
        # Slow down ultrasonic to make audible (e.g., 10x slower for 192kHz)
        if speed == 1.0:
            effective_speed = recording.time_expansion if recording.time_expansion > 1 else 10.0

    data, samplerate = service.audio_service.resample_for_playback(
        recording.path,
        target_samplerate=48000,
        speed=effective_speed,
        start=start,
        end=end,
    )

    wav_bytes = service.audio_service.audio_to_wav_bytes(data, samplerate)

    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": f'inline; filename="{recording.filename}"'},
    )


# T063: Spectrogram generation endpoint
@router.get(
    "/{recording_id}/spectrogram",
    summary="Generate spectrogram",
    description="Generate spectrogram image for visualization",
)
async def get_spectrogram(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    start: float = 0,
    end: float | None = None,
    n_fft: int = 2048,
    hop_length: int = 512,
    freq_min: int = 0,
    freq_max: int | None = None,
    colormap: str = "viridis",
    pcen: bool = False,
    channel: int = 0,
    width: int = 1200,
    height: int = 400,
) -> Response:
    """Generate spectrogram image.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Recording service instance
        start: Start time in seconds (default: 0)
        end: End time in seconds
        n_fft: FFT window size (default: 2048)
        hop_length: Hop length between windows (default: 512)
        freq_min: Minimum frequency in Hz (default: 0)
        freq_max: Maximum frequency in Hz
        colormap: Color map name (default: viridis)
        pcen: Apply PCEN normalization (default: False)
        channel: Audio channel to visualize (default: 0)
        width: Output image width (default: 1200)
        height: Output image height (default: 400)

    Returns:
        PNG image response

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording not found
        400: Invalid spectrogram parameters
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio service not configured"
        )

    try:
        png_bytes = service.audio_service.generate_spectrogram(
            recording.path,
            start=start,
            end=end,
            n_fft=n_fft,
            hop_length=hop_length,
            freq_min=freq_min,
            freq_max=freq_max,
            colormap=colormap,
            pcen=pcen,
            channel=channel,
            width=width,
            height=height,
        )
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# T064: Download endpoint
@router.get(
    "/{recording_id}/download",
    summary="Download recording",
    description="Download original audio file",
)
async def download_recording(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
) -> StreamingResponse:
    """Download original audio file.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Recording service instance

    Returns:
        Streaming response with audio file

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording or audio file not found
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio service not configured"
        )

    file_path = service.audio_service.get_absolute_path(recording.path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found")

    def iter_file() -> Generator[bytes, None, None]:
        """Iterate over file chunks."""
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    # Get mime type
    import mimetypes

    mime_type, _ = mimetypes.guess_type(str(file_path))

    return StreamingResponse(
        iter_file(),
        media_type=mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{recording.filename}"',
            "Content-Length": str(file_path.stat().st_size),
        },
    )
