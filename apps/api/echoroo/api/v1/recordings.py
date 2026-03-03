"""Recordings API endpoints."""

from collections.abc import Generator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
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
    "/{recording_id}/audio",
    summary="Stream audio with HTTP Range support",
    description=(
        "Stream audio for playback with full HTTP Range request support. "
        "Speed and time_expansion are applied via WAV header manipulation "
        "(zero-cost, no resampling). Supports clip trimming via start/end params."
    ),
)
async def stream_audio(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    speed: float = 1.0,
    time_expansion: float | None = None,
    start: float | None = None,
    end: float | None = None,
    target_samplerate: int | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream audio file with HTTP Range support for seeking.

    Supports efficient streaming of long PAM recordings by honouring the
    ``Range`` request header sent by the browser. On the first request
    (``Range: bytes=0-``) a WAV header is prepended so that the browser
    knows the total length and sample format. Subsequent range requests
    return raw PCM bytes at the requested offset.

    Speed and time_expansion adjustments are applied by writing a modified
    sample rate into the WAV header rather than resampling the audio. This
    is a zero-cost operation and results in correct pitch/tempo perception
    in the browser.

    When no processing is required (speed=1, time_expansion=1, no clipping,
    no resampling) the raw file bytes are passed through without decoding,
    which is optimal for large WAV files.

    Args:
        project_id: Project's UUID.
        recording_id: Recording's UUID.
        current_user: Current authenticated user.
        service: Recording service instance.
        speed: Playback speed multiplier (default 1.0). Applied via WAV header.
        time_expansion: Time expansion factor override. Defaults to the value
            stored on the recording.
        start: Clip start time in seconds (original recording domain).
        end: Clip end time in seconds (original recording domain).
        target_samplerate: Resample to this rate before streaming. If None,
            the file's native sample rate is used.
        range: HTTP ``Range`` header value (injected by FastAPI).

    Returns:
        206 Partial Content (or 200 OK when no Range header is present).

    Raises:
        401: Not authenticated.
        403: Access denied.
        404: Recording or audio file not found.
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Audio service not configured",
        )

    file_path = service.audio_service.get_absolute_path(recording.path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found")

    # Use the recording's stored time_expansion when the caller does not override it
    effective_time_expansion = (
        time_expansion if time_expansion is not None else recording.time_expansion
    )

    # Parse the HTTP Range header: "bytes=N-M" or "bytes=N-"
    byte_start = 0
    if range is not None:
        range_value = range.replace("bytes=", "")
        parts = range_value.split("-")
        byte_start = int(parts[0]) if parts[0] else 0

    audio_bytes, actual_start, actual_end, total_size = (
        service.audio_service.load_clip_bytes(
            relative_path=recording.path,
            byte_start=byte_start,
            speed=speed,
            time_expansion=effective_time_expansion,
            start_time=start,
            end_time=end,
            target_samplerate=target_samplerate,
        )
    )

    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(audio_bytes)),
    }

    if range is None:
        # No Range header: return 200 OK with the full first chunk
        return Response(
            content=audio_bytes,
            status_code=status.HTTP_200_OK,
            media_type="audio/wav",
            headers=common_headers,
        )

    # Range header present: return 206 Partial Content
    range_end = actual_end - 1
    common_headers["Content-Range"] = f"bytes {actual_start}-{range_end}/{total_size}"
    return Response(
        content=audio_bytes,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type="audio/wav",
        headers=common_headers,
    )


# Legacy stream endpoint: redirect semantics preserved via alias
@router.get(
    "/{recording_id}/stream",
    summary="Stream audio file (legacy alias)",
    description="Legacy alias for /{recording_id}/audio — prefer /audio for new clients.",
    include_in_schema=False,
)
async def stream_audio_legacy(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    speed: float = 1.0,
    time_expansion: float | None = None,
    start: float | None = None,
    end: float | None = None,
    target_samplerate: int | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Legacy streaming endpoint — delegates to stream_audio."""
    return await stream_audio(
        project_id=project_id,
        recording_id=recording_id,
        current_user=current_user,
        service=service,
        speed=speed,
        time_expansion=time_expansion,
        start=start,
        end=end,
        target_samplerate=target_samplerate,
        range=range,
    )


# T062: Playback endpoint with resampling and HTTP Range support
@router.get(
    "/{recording_id}/playback",
    summary="Get playback audio with Range support",
    description=(
        "Stream audio for browser playback with HTTP Range support. "
        "Ultrasonic recordings are automatically slowed down for audible playback "
        "by adjusting the WAV header sample rate (zero-cost, no resampling). "
        "Delegates to the /audio endpoint internally."
    ),
)
async def get_playback_audio(
    project_id: UUID,
    recording_id: UUID,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    speed: float = 1.0,
    start: float | None = None,
    end: float | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream audio for browser playback with HTTP Range support.

    For ultrasonic recordings (samplerate > 48 kHz), the playback speed is
    automatically adjusted so that the audio is audible in a standard browser
    without any resampling cost. The adjustment is encoded in the WAV header's
    sample rate field.

    Supports the HTTP ``Range`` header so the browser can seek within the
    audio without re-downloading the whole file.

    Args:
        project_id: Project's UUID.
        recording_id: Recording's UUID.
        current_user: Current authenticated user.
        service: Recording service instance.
        speed: Playback speed multiplier (default 1.0).
        start: Clip start time in seconds.
        end: Clip end time in seconds.
        range: HTTP ``Range`` header value (injected by FastAPI).

    Returns:
        206 Partial Content or 200 OK audio response.

    Raises:
        401: Not authenticated.
        403: Access denied.
        404: Recording not found.
    """
    recording = await service.get_by_id(recording_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    # For ultrasonic recordings adjust speed so audio is audible in a browser.
    # This is handled transparently by encoding a reduced samplerate in the WAV
    # header — no actual resampling is performed.
    effective_speed = speed
    if service.is_ultrasonic(recording) and speed == 1.0:
        effective_speed = recording.time_expansion if recording.time_expansion > 1 else 10.0

    return await stream_audio(
        project_id=project_id,
        recording_id=recording_id,
        current_user=current_user,
        service=service,
        speed=effective_speed,
        time_expansion=recording.time_expansion,
        start=start,
        end=end,
        target_samplerate=None,
        range=range,
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


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
