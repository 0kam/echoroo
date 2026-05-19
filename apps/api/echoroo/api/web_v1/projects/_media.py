"""Project media and export BFF adapters.

Spec/009 PR D0 keeps the browser-facing ``/web-api/v1`` routes thin: the
legacy ``/api/v1`` handlers own media streaming, Range semantics, and export
service orchestration. This module only adapts those handlers onto the
first-party session surface.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from echoroo.api.v1 import annotation_projects as legacy_annotation_projects
from echoroo.api.v1 import clips as legacy_clips
from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.api.v1 import recordings as legacy_recordings
from echoroo.core.actions import (
    ANNOTATION_PROJECT_EXPORT_ACTION,
    CLIP_GET_ACTION,
    CLIP_LIST_ACTION,
    DATASET_EXPORT_ACTION,
    RECORDING_LIST_ACTION,
    RECORDING_MEDIA_ACTION,
)
from echoroo.core.auth import DEFAULT_MEDIA_TTL, MediaTokenScope, issue_media_token
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.clip import ClipDetailResponse, ClipListResponse
from echoroo.schemas.recording import RecordingDetailResponse

router = APIRouter()


class MediaTokenRequest(BaseModel):
    """Request body for issuing a scoped recording media token."""

    scope: MediaTokenScope


class MediaTokenResponse(BaseModel):
    """Scoped media token response for native browser media/image elements."""

    token: str
    expires_in: int


@router.post(
    "/{project_id}/recordings/{recording_id}/media-token",
    response_model=MediaTokenResponse,
    summary="Issue a scoped recording media token",
    description="Issue a short-lived JWT scoped to one recording media resource.",
)
async def issue_recording_media_token(
    project_id: UUID,
    recording_id: UUID,
    payload: MediaTokenRequest,
    request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
) -> MediaTokenResponse:
    """Gate VIEW_MEDIA before issuing a scoped token for media GET URLs."""
    await gate_action(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    recording = await service.get_by_id_in_project(recording_id, project_id)
    if recording is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found",
        )

    token = issue_media_token(
        user_id=current_user.id,
        security_stamp=current_user.security_stamp,
        project_id=project_id,
        recording_id=recording_id,
        scope=payload.scope,
        ttl=DEFAULT_MEDIA_TTL,
    )
    return MediaTokenResponse(
        token=token,
        expires_in=int(DEFAULT_MEDIA_TTL.total_seconds()),
    )


@router.get(
    "/{project_id}/recordings/{recording_id}",
    response_model=RecordingDetailResponse,
    summary="Get recording details",
    description="BFF adapter for the legacy project recording detail endpoint.",
)
async def get_recording(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
) -> RecordingDetailResponse:
    """Delegate recording detail reads to the legacy handler."""
    await gate_action(
        action=RECORDING_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_recordings.get_recording(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/recordings/{recording_id}/clips",
    response_model=ClipListResponse,
    summary="List recording clips",
    description="BFF adapter for the legacy project recording clip list endpoint.",
)
async def list_clips(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_clips.ClipServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "start_time",
    sort_order: str = "asc",
) -> ClipListResponse:
    """Delegate clip list reads to the legacy handler."""
    await gate_action(
        action=CLIP_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_clips.list_clips(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get(
    "/{project_id}/recordings/{recording_id}/clips/{clip_id}",
    response_model=ClipDetailResponse,
    summary="Get recording clip",
    description="BFF adapter for the legacy project recording clip detail endpoint.",
)
async def get_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_clips.ClipServiceDep,
    db: DbSession,
) -> ClipDetailResponse:
    """Delegate clip detail reads to the legacy handler."""
    await gate_action(
        action=CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_clips.get_clip(
        project_id=project_id,
        recording_id=recording_id,
        clip_id=clip_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/recordings/{recording_id}/audio",
    summary="Stream audio with HTTP Range support",
    description="BFF adapter for the legacy project recording audio stream.",
)
async def stream_audio(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
    speed: float = 1.0,
    time_expansion: float | None = None,
    start: float | None = None,
    end: float | None = None,
    target_samplerate: int | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Delegate audio streaming to the legacy handler without changing Range behavior."""
    await gate_action(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_recordings.stream_audio(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        speed=speed,
        time_expansion=time_expansion,
        start=start,
        end=end,
        target_samplerate=target_samplerate,
        range=range,
    )


@router.get(
    "/{project_id}/recordings/{recording_id}/playback",
    summary="Get playback audio with Range support",
    description="BFF adapter for the legacy project recording playback stream.",
)
async def get_playback_audio(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
    speed: float = 1.0,
    start: float | None = None,
    end: float | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Delegate playback streaming to the legacy handler."""
    await gate_action(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_recordings.get_playback_audio(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        speed=speed,
        start=start,
        end=end,
        range=range,
    )


@router.get(
    "/{project_id}/recordings/{recording_id}/spectrogram",
    summary="Generate spectrogram",
    description="BFF adapter for the legacy project recording spectrogram endpoint.",
)
async def get_spectrogram(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
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
    """Delegate spectrogram generation to the legacy handler."""
    await gate_action(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_recordings.get_spectrogram(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
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


@router.get(
    "/{project_id}/annotation-projects/{annotation_project_id}/export",
    summary="Export annotations",
    description="BFF adapter for the legacy annotation project export endpoint.",
)
async def export_annotations(
    project_id: UUID,
    annotation_project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    format: str = Query("json", description="Export format: json, csv, or aoef"),
) -> Any:
    """Delegate annotation export to the legacy handler."""
    await gate_action(
        action=ANNOTATION_PROJECT_EXPORT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_projects.export_annotations(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=current_user,
        db=db,
        format=format,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}/export",
    summary="Export dataset",
    description="BFF adapter for the legacy dataset export endpoint.",
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
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    audio_service: legacy_datasets.AudioServiceDep,
    include_audio: bool = False,
) -> StreamingResponse:
    """Delegate dataset export to the legacy handler."""
    await gate_action(
        action=DATASET_EXPORT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_datasets.export_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        db=db,
        audio_service=audio_service,
        include_audio=include_audio,
    )
