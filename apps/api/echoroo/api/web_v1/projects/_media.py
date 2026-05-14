"""Project media and export BFF adapters.

Spec/009 PR D0 keeps the browser-facing ``/web-api/v1`` routes thin: the
legacy ``/api/v1`` handlers own media streaming, Range semantics, and export
service orchestration. This module only adapts those handlers onto the
first-party session surface.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import Response, StreamingResponse

from echoroo.api.v1 import annotation_projects as legacy_annotation_projects
from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.api.v1 import recordings as legacy_recordings
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser

router = APIRouter()


@router.get(
    "/{project_id}/recordings/{recording_id}",
    response_model=legacy_recordings.RecordingDetailResponse,
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
) -> legacy_recordings.RecordingDetailResponse:
    """Delegate recording detail reads to the legacy handler."""
    return await legacy_recordings.get_recording(
        project_id=project_id,
        recording_id=recording_id,
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
    return await legacy_datasets.export_dataset(
        project_id=project_id,
        dataset_id=dataset_id,
        request=request,
        current_user=current_user,
        db=db,
        audio_service=audio_service,
        include_audio=include_audio,
    )
