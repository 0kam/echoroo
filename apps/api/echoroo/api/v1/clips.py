"""Clips API endpoints."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from echoroo.core.actions import (
    CLIP_AUDIO_ACTION,
    CLIP_CREATE_ACTION,
    CLIP_DELETE_ACTION,
    CLIP_DOWNLOAD_ACTION,
    CLIP_GENERATE_ACTION,
    CLIP_GET_ACTION,
    CLIP_LIST_ACTION,
    CLIP_SPECTROGRAM_ACTION,
    CLIP_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.clip import (
    ClipCreate,
    ClipDetailResponse,
    ClipGenerateRequest,
    ClipGenerateResponse,
    ClipListResponse,
    ClipResponse,
    ClipUpdate,
    RecordingSummary,
)
from echoroo.services.audio import AudioService
from echoroo.services.clip import ClipService

router = APIRouter(prefix="/projects/{project_id}/recordings/{recording_id}/clips", tags=["clips"])

settings = get_settings()


def get_audio_service() -> AudioService:
    """Get AudioService instance.

    Returns:
        AudioService instance
    """
    return AudioService(
        settings.AUDIO_ROOT,
        settings.AUDIO_CACHE_DIR,
        s3_audio_cache_dir=settings.S3_AUDIO_CACHE_DIR,
    )


def get_clip_service(
    db: DbSession, audio_service: AudioService = Depends(get_audio_service)
) -> ClipService:
    """Get ClipService instance.

    Args:
        db: Database session
        audio_service: Audio service instance

    Returns:
        ClipService instance
    """
    return ClipService(db, audio_service)


AudioServiceDep = Annotated[AudioService, Depends(get_audio_service)]
ClipServiceDep = Annotated[ClipService, Depends(get_clip_service)]


# T076: CRUD endpoints
#
# W2-3 PR-13 (2026-07-02): the 6 browser-superseded clip CRUD/generate routes
# (list/create/get/update/delete/generate) were unmounted from ``/api/v1`` in
# favour of the project-scoped ``/web-api/v1`` BFF surface
# (``web_v1/projects/_media.py`` for the two GETs, ``_clips.py`` for the four
# mutations). The handler bodies stay as importable helpers that the BFF
# adapters delegate to (function-as-helper); only their ``@router`` decorators
# were removed. The audio / spectrogram / download media routes below KEEP
# their decorators — they are not yet migrated.
async def list_clips(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "start_time",
    sort_order: str = "asc",
) -> ClipListResponse:
    """List clips for a recording.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        current_user: Current authenticated user
        service: Clip service instance
        page: Page number (default: 1)
        page_size: Items per page (default: 50)
        sort_by: Sort column (default: start_time)
        sort_order: Sort order (asc/desc, default: asc)

    Returns:
        Paginated list of clips

    Raises:
        401: Not authenticated
    """
    await gate_action(
        action=CLIP_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    clips, total = await service.list_by_recording(
        recording_id, page, page_size, sort_by, sort_order
    )
    pages = (total + page_size - 1) // page_size
    return ClipListResponse(
        items=[ClipResponse.model_validate(c) for c in clips],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


async def create_clip(
    project_id: UUID,
    recording_id: UUID,
    request: ClipCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    db: DbSession,
) -> ClipDetailResponse:
    """Create a new clip.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: Clip creation data
        current_user: Current authenticated user
        service: Clip service instance

    Returns:
        Created clip with details

    Raises:
        400: Validation error
        401: Not authenticated
    """
    await gate_action(
        action=CLIP_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    try:
        clip = await service.create(
            recording_id=recording_id,
            start_time=request.start_time,
            end_time=request.end_time,
            note=request.note,
        )
        return ClipDetailResponse(
            **ClipResponse.model_validate(clip).model_dump(),
            duration=service.get_duration(clip),
            recording=None,  # Not loading recording to keep response light
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def get_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    db: DbSession,
) -> ClipDetailResponse:
    """Get clip by ID.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        clip_id: Clip's UUID
        current_user: Current authenticated user
        service: Clip service instance

    Returns:
        Clip details with recording information

    Raises:
        401: Not authenticated
        404: Clip not found
    """
    await gate_action(
        action=CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    clip = await service.get_by_id(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    recording_summary = None
    if clip.recording:
        recording_summary = RecordingSummary(
            id=clip.recording.id,
            filename=clip.recording.filename,
            duration=clip.recording.duration,
            samplerate=clip.recording.samplerate,
            time_expansion=clip.recording.time_expansion,
        )

    return ClipDetailResponse(
        **ClipResponse.model_validate(clip).model_dump(),
        duration=service.get_duration(clip),
        recording=recording_summary,
    )


async def update_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: ClipUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    db: DbSession,
) -> ClipDetailResponse:
    """Update clip.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        clip_id: Clip's UUID
        request: Update data
        current_user: Current authenticated user
        service: Clip service instance

    Returns:
        Updated clip details

    Raises:
        400: Validation error
        401: Not authenticated
        404: Clip not found
    """
    await gate_action(
        action=CLIP_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    try:
        clip = await service.update(
            clip_id,
            start_time=request.start_time,
            end_time=request.end_time,
            note=request.note,
        )
        if not clip:
            raise HTTPException(status_code=404, detail="Clip not found")
        return ClipDetailResponse(
            **ClipResponse.model_validate(clip).model_dump(),
            duration=service.get_duration(clip),
            recording=None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


async def delete_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    db: DbSession,
) -> None:
    """Delete clip.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        clip_id: Clip's UUID
        current_user: Current authenticated user
        service: Clip service instance
        db: Database session

    Raises:
        401: Not authenticated
        404: Clip not found
    """
    await gate_action(
        action=CLIP_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    if not await service.delete(clip_id):
        raise HTTPException(status_code=404, detail="Clip not found")
    await db.commit()


# T077: Generate endpoint
async def generate_clips(
    project_id: UUID,
    recording_id: UUID,
    request: ClipGenerateRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    db: DbSession,
) -> ClipGenerateResponse:
    """Auto-generate clips from recording.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: Generation parameters
        current_user: Current authenticated user
        service: Clip service instance

    Returns:
        Generated clips

    Raises:
        400: Validation error
        401: Not authenticated
    """
    await gate_action(
        action=CLIP_GENERATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    try:
        clips = await service.generate_clips(
            recording_id=recording_id,
            clip_length=request.clip_length,
            overlap=request.overlap or 0.0,
            start_time=request.start_time or 0.0,
            end_time=request.end_time,
        )
        return ClipGenerateResponse(
            clips_created=len(clips),
            clips=[ClipResponse.model_validate(c) for c in clips],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# T078: Audio/spectrogram/download endpoints
#
# W2-4 PR-A (2026-07-04): the three browser-superseded clip media routes
# (audio / spectrogram / download) were unmounted from ``/api/v1`` in favour of
# the ``/web-api/v1`` BFF media-token surface. The handler bodies stay as
# importable helpers: ``download_clip`` is delegated to by
# ``echoroo.api.web_v1.projects._media.download_clip``; ``get_clip_audio`` and
# ``get_clip_spectrogram`` have no BFF twin (clip audio/spectrogram ride the
# recording-level playback / spectrogram BFF with clip start/end bounds) and are
# retained only for reference / any residual internal callers. This file now has
# ZERO route decorators, so its ``include_router`` was removed from
# ``echoroo.api.v1.__init__``.
async def get_clip_audio(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    audio_service: AudioServiceDep,
    db: DbSession,
    speed: float = 1.0,
) -> Response:
    """Get clip audio (resampled for browser playback).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        clip_id: Clip's UUID
        current_user: Current authenticated user
        service: Clip service instance
        audio_service: Audio service instance
        speed: Playback speed multiplier (default: 1.0)

    Returns:
        WAV audio file

    Raises:
        400: Audio processing error
        401: Not authenticated
        404: Clip or recording not found
    """
    await gate_action(
        action=CLIP_AUDIO_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    clip = await service.get_by_id(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    recording = await service.recording_repo.get_by_id(clip.recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    try:
        audio_svc = audio_service
        await asyncio.to_thread(audio_svc.ensure_file_local, recording.path)
        data, samplerate = await asyncio.to_thread(
            lambda: audio_svc.resample_for_playback(
                recording.path,
                target_samplerate=48000,
                speed=speed,
                start=clip.start_time,
                end=clip.end_time,
            )
        )

        wav_bytes = audio_service.audio_to_wav_bytes(data, samplerate)
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": f'inline; filename="clip_{clip_id}.wav"'},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Audio file not found") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Audio processing error: {str(e)}") from e


async def get_clip_spectrogram(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    audio_service: AudioServiceDep,
    db: DbSession,
    n_fft: int = 2048,
    hop_length: int = 512,
    freq_min: int = 0,
    freq_max: int | None = None,
    colormap: str = "viridis",
    pcen: bool = False,
    channel: int = 0,
    width: int = 800,
    height: int = 300,
) -> Response:
    """Generate spectrogram for clip.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        clip_id: Clip's UUID
        current_user: Current authenticated user
        service: Clip service instance
        audio_service: Audio service instance
        n_fft: FFT window size (default: 2048)
        hop_length: Hop length between windows (default: 512)
        freq_min: Minimum frequency in Hz (default: 0)
        freq_max: Maximum frequency in Hz (default: Nyquist)
        colormap: Matplotlib colormap name (default: viridis)
        pcen: Apply PCEN normalization (default: False)
        channel: Audio channel to use (default: 0)
        width: Output image width (default: 800)
        height: Output image height (default: 300)

    Returns:
        PNG spectrogram image

    Raises:
        400: Spectrogram generation error
        401: Not authenticated
        404: Clip or recording not found
    """
    await gate_action(
        action=CLIP_SPECTROGRAM_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    clip = await service.get_by_id(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    recording = await service.recording_repo.get_by_id(clip.recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    try:
        audio_svc = audio_service
        await asyncio.to_thread(audio_svc.ensure_file_local, recording.path)
        png_bytes = await asyncio.to_thread(
            lambda: audio_svc.generate_spectrogram(
                recording.path,
                start=clip.start_time,
                end=clip.end_time,
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
        )
        return Response(content=png_bytes, media_type="image/png")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Audio file not found") from e
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Spectrogram generation error: {str(e)}"
        ) from e


async def download_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ClipServiceDep,
    audio_service: AudioServiceDep,
    db: DbSession,
) -> Response:
    """Download clip as WAV file.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        clip_id: Clip's UUID
        current_user: Current authenticated user
        service: Clip service instance
        audio_service: Audio service instance

    Returns:
        WAV audio file for download

    Raises:
        400: Audio processing error
        401: Not authenticated
        404: Clip or recording not found
    """
    await gate_action(
        action=CLIP_DOWNLOAD_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    clip = await service.get_by_id(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    recording = await service.recording_repo.get_by_id(clip.recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")

    try:
        audio_svc = audio_service
        await asyncio.to_thread(audio_svc.ensure_file_local, recording.path)
        data, samplerate = await asyncio.to_thread(
            lambda: audio_svc.read_audio(
                recording.path,
                start=clip.start_time,
                end=clip.end_time,
            )
        )

        wav_bytes = audio_service.audio_to_wav_bytes(data, samplerate)
        filename = (
            f"{recording.filename.rsplit('.', 1)[0]}_{clip.start_time:.2f}-{clip.end_time:.2f}.wav"
        )

        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="Audio file not found") from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Audio processing error: {str(e)}") from e
