"""Recordings API endpoints.

Phase 3 (T127, FR-008 / FR-008a / FR-011 / FR-016): read endpoints (list /
detail) route through the central :func:`is_allowed` gate using
:data:`RECORDING_LIST_ACTION` (:data:`Permission.VIEW_DETECTION`). Media
endpoints (``/audio``, ``/stream``, ``/playback``, ``/spectrogram``,
``/download``) route through :data:`RECORDING_MEDIA_ACTION`
(:data:`Permission.VIEW_MEDIA`) so Restricted projects can independently
gate raw audio access via ``restricted_config.allow_media``.

Mutating endpoints (``PATCH``, ``DELETE``) keep the legacy
:func:`check_project_access` membership check until a dedicated
``recording.update`` / ``recording.delete`` Action lands. Stage-2 response
filtering (FR-011 H3 generalisation, FR-016 sensitive species masking) is
deferred to T130-T134.
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select as sa_select

from echoroo.core.actions import RECORDING_LIST_ACTION, RECORDING_MEDIA_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import Action, check_project_access, is_allowed
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import API_TOKEN_PREFIX, CurrentUser
from echoroo.models.project import Project
from echoroo.models.user import User
from echoroo.schemas.recording import (
    RecordingDetailResponse,
    RecordingListResponse,
    RecordingResponse,
    RecordingUpdate,
)
from echoroo.services.audio import AudioService
from echoroo.services.auth import AuthService
from echoroo.services.recording import RecordingService
from echoroo.services.token import TokenService

router = APIRouter(prefix="/projects/{project_id}/recordings", tags=["recordings"])

settings = get_settings()

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_flexible(
    request: Request,
    db: DbSession,
    token: Annotated[str | None, Query(description="JWT access token (for audio/img src URLs)")] = None,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
) -> User:
    """Authenticate via Authorization header or ?token query parameter.

    This dependency is used exclusively for audio streaming and spectrogram
    endpoints so that the browser can set ``<audio src=url>`` and
    ``<img src=url>`` directly without custom fetch logic. Standard endpoints
    must continue to use the header-only ``CurrentUser`` dependency.

    Priority:
        1. Query parameter ``?token=<jwt>``  (allows native browser media elements)
        2. ``Authorization: Bearer <jwt>`` header  (standard behaviour)

    Security note:
        The token will appear in server access logs when passed as a query
        parameter. This is acceptable for scoped media streaming URLs.

    Args:
        request: Incoming HTTP request (unused directly, kept for tracing).
        db: Database session.
        token: Optional JWT access token supplied as a query parameter.
        credentials: Optional HTTP Bearer credentials from the Authorization header.

    Returns:
        Authenticated User instance.

    Raises:
        HTTPException 401: No valid credentials supplied.
        HTTPException 401: Token is invalid or expired.
        HTTPException 403: User account is disabled.
    """
    # Resolve the raw token string from either source
    raw_token: str | None = None
    if token is not None:
        raw_token = token
    elif credentials is not None:
        raw_token = credentials.credentials

    if raw_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Dispatch to the appropriate authentication back-end
    if raw_token.startswith(API_TOKEN_PREFIX):
        token_service = TokenService(db)
        user = await token_service.authenticate_by_token(raw_token)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    auth_service = AuthService(db)
    return await auth_service.get_current_user(raw_token)


# Annotated type alias for the flexible auth dependency (media endpoints only)
FlexibleCurrentUser = Annotated[User, Depends(get_current_user_flexible)]


def get_audio_service() -> AudioService:
    """Get AudioService instance.

    Returns:
        AudioService instance configured with S3 audio cache support.
    """
    return AudioService(
        settings.AUDIO_ROOT,
        settings.AUDIO_CACHE_DIR,
        s3_audio_cache_dir="/data/s3_audio_cache",
    )


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


# ---------------------------------------------------------------------------
# Internal helpers (Phase 3 permission gate — mirrors v1/detections.py)
# ---------------------------------------------------------------------------


async def _load_project(db: DbSession, project_id: UUID) -> Project:
    """Load the Project ORM row needed by :func:`is_allowed`.

    The gate reads ``visibility`` / ``restricted_config`` / ``status`` /
    ``owner_id`` from the row, so a regular ORM load is sufficient.
    """
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


async def _gate(
    *,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    db: DbSession,
) -> Project:
    """Run the Stage-1 :func:`is_allowed` gate for ``action`` on ``project_id``.

    Returns the loaded :class:`Project` row so callers can pass it through to
    the service layer (e.g. for response filtering / restricted_config reads)
    without issuing a second SELECT.
    """
    project = await _load_project(db, project_id)
    allowed, _ = is_allowed(
        action=action,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="action denied")
    return project


# T060: List and search endpoints
@router.get(
    "",
    response_model=RecordingListResponse,
    summary="List and search recordings",
    description="List/search recordings across project datasets with pagination and filters",
)
async def list_recordings(
    project_id: UUID,
    request: Request,
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

    Guarded by :data:`RECORDING_LIST_ACTION`
    (:data:`Permission.VIEW_DETECTION`). Public / Restricted projects allow
    Guest reads via the canonical matrix; the gate enforces it.

    Args:
        project_id: Project's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session
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
        403: Permission denied
    """
    await _gate(
        action=RECORDING_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # TODO(T130-T134, FR-011/016): apply Stage-2 response filter
    # (H3 generalisation / sensitive species masking) using the
    # ``effective_permissions`` + ``normalized_role`` stashed on
    # ``request.state`` by ``is_allowed``. Pending the bulk taxon
    # sensitivity preload utility.
    if dataset_id:
        # BOLA / IDOR guard (FR-008): the dataset must belong to the
        # gated project — a dataset UUID from another project must not
        # leak its recording list.
        from echoroo.repositories.dataset import DatasetRepository

        dataset_repo = DatasetRepository(db)
        dataset_in_project = await dataset_repo.get_by_id_in_project(
            dataset_id, project_id
        )
        if dataset_in_project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

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
    request: Request,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
) -> RecordingDetailResponse:
    """Get recording by ID with details.

    Guarded by :data:`RECORDING_LIST_ACTION`
    (:data:`Permission.VIEW_DETECTION`). The detail surface is a list-shaped
    read of a single recording, so it shares the LIST permission. A dedicated
    ``recording.get`` Action can be introduced later if the detail view ever
    exposes fields not present in the list response.

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session

    Returns:
        Recording details with relationships

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Recording not found
    """
    await _gate(
        action=RECORDING_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    recording = await service.get_by_id_in_project(recording_id, project_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    # TODO(T130-T134, FR-011/016): apply Stage-2 response filter once the
    # bulk taxon-sensitivity preloader is wired up.

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

    Mutating endpoint — Phase 3 will introduce a dedicated
    ``RECORDING_UPDATE_ACTION``; until then we keep the legacy membership
    check so contract tests still pass.

    TODO(Phase 3 follow-up, FR-008a): register ``recording.update`` in
    ``core/actions.py`` and switch to ``_gate(...)`` here.

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
    await check_project_access(project_id, current_user.id, db)

    # BOLA / IDOR guard (FR-008a): verify the recording belongs to the
    # gated project before mutating it. Without this check a member of
    # project A could PATCH a recording UUID belonging to project B.
    existing = await service.get_by_id_in_project(recording_id, project_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

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

    Mutating endpoint — Phase 3 will introduce a dedicated
    ``RECORDING_DELETE_ACTION``; until then we keep the legacy membership
    check so contract tests still pass.

    TODO(Phase 3 follow-up, FR-008a): register ``recording.delete`` in
    ``core/actions.py`` and switch to ``_gate(...)`` here.

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
    await check_project_access(project_id, current_user.id, db)

    # BOLA / IDOR guard (FR-008a): verify the recording belongs to the
    # gated project before deleting. Without this check a member of
    # project A could DELETE a recording belonging to project B.
    existing = await service.get_by_id_in_project(recording_id, project_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

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
        "(zero-cost, no resampling). Supports clip trimming via start/end params. "
        "Accepts auth via Authorization header or ?token query parameter."
    ),
)
async def stream_audio(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: FlexibleCurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
    speed: float = 1.0,
    time_expansion: float | None = None,
    start: float | None = None,
    end: float | None = None,
    target_samplerate: int | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream audio file with HTTP Range support for seeking.

    Guarded by :data:`RECORDING_MEDIA_ACTION` (:data:`Permission.VIEW_MEDIA`).
    Restricted projects gate raw audio access independently from detection
    metadata via ``restricted_config.allow_media`` (FR-016).

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
        403: Permission denied.
        404: Recording or audio file not found.
    """
    await _gate(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    recording = await service.get_by_id_in_project(recording_id, project_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Audio service not configured",
        )
    assert service.audio_service is not None  # narrowing for Pyright

    try:
        local_file_path = service.audio_service.ensure_file_local(recording.path)
    except FileNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found") from err

    # Use the recording's stored time_expansion when the caller does not override it
    effective_time_expansion = (
        time_expansion if time_expansion is not None else recording.time_expansion
    )

    # Determine whether we can stream the raw file bytes without decoding
    is_passthrough = (
        speed == 1.0
        and effective_time_expansion == 1.0
        and start is None
        and end is None
        and target_samplerate is None
    )

    # For passthrough mode, serve the compressed OGG version to reduce transfer size
    # (83 MB WAV -> ~3-5 MB OGG over SSH). The compressed file is created on first
    # access and cached on disk for subsequent requests.
    if is_passthrough:
        import logging

        _logger = logging.getLogger(__name__)
        try:
            compressed_path = service.audio_service.get_compressed_for_playback(recording.path)
        except Exception as exc:
            _logger.warning(
                "OGG compression failed for %s, falling back to raw WAV: %s",
                recording.path,
                exc,
            )
            compressed_path = None

        if compressed_path is not None:
            ogg_size = compressed_path.stat().st_size

            if range is None:
                # No Range header: stream the full compressed file
                def _iter_ogg() -> Generator[bytes, None, None]:
                    with open(compressed_path, "rb") as f:
                        while chunk := f.read(65536):
                            yield chunk

                return StreamingResponse(
                    _iter_ogg(),
                    status_code=status.HTTP_200_OK,
                    media_type="audio/ogg",
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(ogg_size),
                    },
                )

            # Range request: serve the requested byte slice of the OGG file
            range_value = range.replace("bytes=", "")
            parts = range_value.split("-")
            req_start = int(parts[0]) if parts[0] else 0
            req_end = int(parts[1]) if len(parts) > 1 and parts[1] else ogg_size - 1

            req_start = max(0, min(req_start, ogg_size - 1))
            req_end = max(req_start, min(req_end, ogg_size - 1))
            chunk_size = req_end - req_start + 1

            with open(compressed_path, "rb") as f:
                f.seek(req_start)
                chunk = f.read(chunk_size)

            return Response(
                content=chunk,
                status_code=status.HTTP_206_PARTIAL_CONTENT,
                media_type="audio/ogg",
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(chunk_size),
                    "Content-Range": f"bytes {req_start}-{req_end}/{ogg_size}",
                },
            )

        # Fallback: serve raw WAV when compression is unavailable
        file_size = local_file_path.stat().st_size

        if range is None:
            def _iter_file() -> Generator[bytes, None, None]:
                with open(local_file_path, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk

            return StreamingResponse(
                _iter_file(),
                status_code=status.HTTP_200_OK,
                media_type="audio/wav",
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(file_size),
                },
            )

        range_value = range.replace("bytes=", "")
        parts = range_value.split("-")
        req_start = int(parts[0]) if parts[0] else 0
        req_end = int(parts[1]) if len(parts) > 1 and parts[1] else file_size - 1

        req_start = max(0, min(req_start, file_size - 1))
        req_end = max(req_start, min(req_end, file_size - 1))
        chunk_size = req_end - req_start + 1

        with open(local_file_path, "rb") as f:
            f.seek(req_start)
            chunk = f.read(chunk_size)

        return Response(
            content=chunk,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type="audio/wav",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(chunk_size),
                "Content-Range": f"bytes {req_start}-{req_end}/{file_size}",
            },
        )

    # Non-passthrough path (speed change, trimming, resampling):
    # load_clip_bytes() decodes and re-encodes as needed.
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

    range_end = actual_end - 1
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(audio_bytes)),
        "Content-Range": f"bytes {actual_start}-{range_end}/{total_size}",
    }

    # Always return 206 Partial Content so the browser knows the total file
    # size and can issue subsequent Range requests for the remaining data.
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
    request: Request,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
    speed: float = 1.0,
    time_expansion: float | None = None,
    start: float | None = None,
    end: float | None = None,
    target_samplerate: int | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Legacy streaming endpoint — delegates to stream_audio.

    Guarded transitively by :data:`RECORDING_MEDIA_ACTION` via the underlying
    :func:`stream_audio` handler.
    """
    return await stream_audio(
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


# T062: Playback endpoint with resampling and HTTP Range support
@router.get(
    "/{recording_id}/playback",
    summary="Get playback audio with Range support",
    description=(
        "Stream audio for browser playback with HTTP Range support. "
        "Ultrasonic recordings are automatically slowed down for audible playback "
        "by adjusting the WAV header sample rate (zero-cost, no resampling). "
        "Delegates to the /audio endpoint internally. "
        "Accepts auth via Authorization header or ?token query parameter."
    ),
)
async def get_playback_audio(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: FlexibleCurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
    speed: float = 1.0,
    start: float | None = None,
    end: float | None = None,
    range: Annotated[str | None, Header()] = None,
) -> Response:
    """Stream audio for browser playback with HTTP Range support.

    Guarded by :data:`RECORDING_MEDIA_ACTION` (:data:`Permission.VIEW_MEDIA`)
    via the underlying :func:`stream_audio` handler. Restricted projects gate
    raw audio access via ``restricted_config.allow_media`` (FR-016).

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
    recording = await service.get_by_id_in_project(recording_id, project_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    # For ultrasonic recordings adjust speed so audio is audible in a browser.
    # This is handled transparently by encoding a reduced samplerate in the WAV
    # header — no actual resampling is performed.
    #
    # The header samplerate formula in load_clip_bytes is:
    #   header_sr = output_sr * speed * time_expansion
    #
    # For ultrasonic playback we want a low header rate (e.g. ~48 kHz) so the
    # browser plays the high-samplerate PCM slowly, making the audio audible.
    # We achieve this by setting speed to 1/time_expansion (which cancels out
    # the time_expansion multiplication), effectively giving header_sr ≈ output_sr.
    # For full-spectrum recordings (time_expansion=1), we target ~48 kHz.
    effective_speed = speed
    effective_te = recording.time_expansion
    if service.is_ultrasonic(recording) and speed == 1.0:
        # Target a browser-friendly samplerate for the WAV header
        target_browser_rate = 48000
        # header_sr = samplerate * effective_speed * effective_te = target_browser_rate
        # => effective_speed = target_browser_rate / (samplerate * effective_te)
        effective_speed = target_browser_rate / (recording.samplerate * effective_te)

    return await stream_audio(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        speed=effective_speed,
        time_expansion=effective_te,
        start=start,
        end=end,
        target_samplerate=None,
        range=range,
    )


# T063: Spectrogram generation endpoint
@router.get(
    "/{recording_id}/spectrogram",
    summary="Generate spectrogram",
    description=(
        "Generate spectrogram image for visualization. "
        "Accepts auth via Authorization header or ?token query parameter."
    ),
)
async def get_spectrogram(
    project_id: UUID,
    recording_id: UUID,
    request: Request,
    current_user: FlexibleCurrentUser,
    service: RecordingServiceDep,
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
    """Generate spectrogram image.

    Guarded by :data:`RECORDING_MEDIA_ACTION` (:data:`Permission.VIEW_MEDIA`).
    Restricted projects gate spectrogram access independently from detection
    metadata via ``restricted_config.allow_media`` (FR-016).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session
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
        403: Permission denied
        404: Recording not found
        400: Invalid spectrogram parameters
    """
    await _gate(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    recording = await service.get_by_id_in_project(recording_id, project_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio service not configured"
        )
    assert service.audio_service is not None  # narrowing for Pyright

    try:
        await asyncio.to_thread(service.audio_service.ensure_file_local, recording.path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found") from exc

    audio_svc = service.audio_service
    try:
        png_bytes = await asyncio.to_thread(
            lambda: audio_svc.generate_spectrogram(
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
    request: Request,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
) -> StreamingResponse:
    """Download original audio file.

    Guarded by :data:`RECORDING_MEDIA_ACTION` (:data:`Permission.VIEW_MEDIA`).
    Downloading raw audio is the most permissive media operation, so it goes
    through the same media gate as ``/audio`` and ``/spectrogram``. Restricted
    projects can independently disable downloads via
    ``restricted_config.allow_media`` (FR-016).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session

    Returns:
        Streaming response with audio file

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Recording or audio file not found
    """
    await _gate(
        action=RECORDING_MEDIA_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    recording = await service.get_by_id_in_project(recording_id, project_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")

    if not service.audio_service:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Audio service not configured"
        )

    try:
        file_path = service.audio_service.ensure_file_local(recording.path)
    except FileNotFoundError as err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio file not found") from err

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
