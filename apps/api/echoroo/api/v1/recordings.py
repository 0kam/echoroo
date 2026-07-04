"""Recordings API endpoints.

Phase 3 (T127, FR-008 / FR-008a / FR-011 / FR-016): read endpoints (list /
detail) route through the central :func:`is_allowed` gate using
:data:`RECORDING_LIST_ACTION` (:data:`Permission.VIEW_DETECTION`). Media
endpoints (``/audio``, ``/stream``, ``/playback``, ``/spectrogram``,
``/download``) route through :data:`RECORDING_MEDIA_ACTION`
(:data:`Permission.VIEW_MEDIA`) so Restricted projects can independently
gate raw audio access via ``restricted_config.allow_media``.

Mutating endpoints (``PATCH``, ``DELETE``) route through
``recording.update`` / ``recording.delete`` Actions. Stage-2 response filtering
(FR-011 H3 generalisation, FR-016 sensitive species masking) is deferred to
T130-T134.
"""

from __future__ import annotations

import asyncio
from collections.abc import (  # noqa: F401 — Generator kept for non-guarded paths
    AsyncIterator,
    Generator,
)
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from echoroo.core.actions import (
    RECORDING_DELETE_ACTION,
    RECORDING_LIST_ACTION,
    RECORDING_MEDIA_ACTION,
    RECORDING_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import Permission, gate_action
from echoroo.core.response_filter import apply_response_filter
from echoroo.core.settings import get_settings
from echoroo.core.stream_guard import (
    AUDIO_RECHECK_INTERVAL,
    PermissionRevokedMidStream,
    audit_stream_revoked,
    recheck_action_permission,
)
from echoroo.middleware.auth import API_TOKEN_PREFIX, CurrentUser, _stamp_superuser_status
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
) -> User | None:
    """Resolve the caller from header / ?token — Guest-aware.

    Phase 5 (T202, FR-016): media endpoints fall through to the central
    permission gate which decides Public-Guest visibility via the Canonical
    Matrix. We therefore allow the dependency to return ``None`` (Guest)
    rather than 401-ing the response. Authentication failures on otherwise
    valid Public projects are not user-visible — the gate will allow the
    Guest principal when the project is Public + Active (FR-016).

    Priority:
        1. Query parameter ``?token=<jwt>``  (browser ``<audio src>`` / ``<img src>``)
        2. ``Authorization: Bearer <jwt>`` header
        3. None — Guest fall-through, the gate decides.

    Security note:
        The token will appear in server access logs when passed as a query
        parameter. This is acceptable for scoped media streaming URLs and is
        unchanged from the pre-Phase-5 behaviour.

    Args:
        request: Incoming HTTP request (unused directly, kept for tracing).
        db: Database session.
        token: Optional JWT access token supplied as a query parameter.
        credentials: Optional HTTP Bearer credentials from the Authorization header.

    Returns:
        Authenticated User OR ``None`` for Guest. Bad tokens fall back to
        Guest (the gate is fail-closed for non-Public projects).
    """
    # Resolve the raw token string from either source
    raw_token: str | None = None
    if token is not None:
        raw_token = token
    elif credentials is not None:
        raw_token = credentials.credentials

    if not raw_token:
        return None

    # Dispatch to the appropriate authentication back-end
    #
    # Phase 12 R3 follow-up (Major #2): every auth dependency MUST stamp
    # ``user.is_superuser`` from the ``superusers`` source-of-truth before
    # returning so downstream gates (Step 0c superuser short-circuit in
    # :func:`echoroo.core.permissions.is_allowed`) can rely on a uniform
    # attribute. Without this stamp the legacy v1 media endpoints
    # (``/audio``, ``/stream``, ``/playback``, ``/spectrogram``,
    # ``/download``) would fail to grant superuser owner-equivalent access
    # because ``user.is_superuser`` would be ``False`` even for an active
    # superuser principal. Mirrors :func:`get_current_user` /
    # :func:`get_current_user_optional` from
    # :mod:`echoroo.middleware.auth`.
    user: User | None = None
    try:
        if raw_token.startswith(API_TOKEN_PREFIX):
            token_service = TokenService(db)
            user = await token_service.authenticate_by_token(raw_token)
        else:
            auth_service = AuthService(db)
            user = await auth_service.get_current_user(raw_token)
    except HTTPException:
        # Bad token on a Public route -> Guest fall-through. The permission
        # gate will still 403 / 404 the response when the project is not
        # Public-readable.
        return None

    await _stamp_superuser_status(db, user)
    return user


# Annotated type alias for the flexible auth dependency (media endpoints only)
FlexibleCurrentUser = Annotated[User | None, Depends(get_current_user_flexible)]


def get_audio_service() -> AudioService:
    """Get AudioService instance.

    Returns:
        AudioService instance configured with S3 audio cache support.

    Phase 5 polish round 3 (重要1): the S3 audio cache directory is now
    sourced from :class:`Settings` instead of a hard-coded ``/data/`` path.
    Tests and CI runners that cannot write to ``/data/`` may override
    ``S3_AUDIO_CACHE_DIR`` via the environment or via FastAPI's
    ``app.dependency_overrides`` against this function.
    """
    return AudioService(
        settings.AUDIO_ROOT,
        settings.AUDIO_CACHE_DIR,
        s3_audio_cache_dir=settings.S3_AUDIO_CACHE_DIR,
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


# T060: List and search endpoints
#
# W2-3 PR-16 (2026-07-02): the 6 browser-superseded recording routes
# (list/get/update/delete/playback/spectrogram) were unmounted from ``/api/v1``
# in favour of the project-scoped ``/web-api/v1`` BFF surface. The get /
# playback / spectrogram GETs and the update / delete mutations are served by
# ``web_v1/projects/_media.py`` + ``_recordings.py`` thin delegates that import
# these handler bodies as helpers (function-as-helper). The list route has an
# INDEPENDENT BFF reimplementation (``list_public_recordings`` in
# ``web_v1/projects/_core.py`` with a different ``PublicRecordingListResponse``
# shape), so ``list_recordings`` below is dead-but-importable — only its
# ``@router`` decorator was removed. The audio / stream / download media routes
# further down KEEP their decorators (deferred to the W2-4 media-token track).
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
    project = await gate_action(
        action=RECORDING_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

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
    items = [RecordingResponse.model_validate(r) for r in recordings]
    # Recording list shape carries no taxon (sensitivity is taxon-keyed) so
    # the bulk preloaders would have no input. The Stage-2 filter still
    # scrubs raw-coordinate fields and applies the non-member ceiling.
    for item in items:
        apply_response_filter(
            obj=item,
            effective_permissions=effective,
            normalized_role=role,
            project=project,
            resource=item,
            taxon_sensitivity_map={},
            override_map={},
        )

    return RecordingListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
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
    project = await gate_action(
        action=RECORDING_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    recording = await service.get_by_id_in_project(recording_id, project_id)
    if not recording:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

    # Build detail response
    clip_count = await service.clip_repo.count_by_recording(recording_id)

    # Build dataset summary
    dataset_summary = None
    if recording.dataset:
        dataset_summary = {
            "id": recording.dataset.id,
            "name": recording.dataset.name,
        }

    # Build site summary (Phase 13 P4 / T807: ``h3_index_member`` matches
    # ORM column + spec data-model §3.10 canonical name).
    site_summary = None
    if recording.dataset and recording.dataset.site:
        site_summary = {
            "id": recording.dataset.site.id,
            "name": recording.dataset.site.name,
            "h3_index_member": recording.dataset.site.h3_index_member,
        }

    response = RecordingDetailResponse(
        **RecordingResponse.model_validate(recording).model_dump(),
        dataset=dataset_summary,
        site=site_summary,
        clip_count=clip_count,
        effective_duration=service.get_effective_duration(recording),
        is_ultrasonic=service.is_ultrasonic(recording),
    )
    # Recording responses do not embed a taxon — sensitivity is taxon-keyed
    # (FR-029 / FR-032), so the bulk preloaders would have no input here.
    # The Stage-2 filter still scrubs forbidden raw-coordinate fields and
    # applies the project-level non-member ceiling, which is the entirety
    # of the recording-shape obscure logic.
    apply_response_filter(
        obj=response,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=response,
        taxon_sensitivity_map={},
        override_map={},
    )
    return response


async def update_recording(
    project_id: UUID,
    recording_id: UUID,
    request: RecordingUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
) -> RecordingDetailResponse:
    """Update recording (time_expansion, note).

    Guarded by :data:`RECORDING_UPDATE_ACTION`
    (:data:`Permission.MANAGE_DATASET`).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        request: Update data
        http_request: FastAPI :class:`Request` used by the gate to stash
            stage-1 state on ``request.state``. Named ``http_request`` to
            avoid colliding with the body parameter ``request``.
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
    project = await gate_action(
        action=RECORDING_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    state = http_request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")

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

    # Build site summary (Phase 13 P4 / T807: ``h3_index_member`` matches
    # ORM column + spec data-model §3.10 canonical name).
    site_summary = None
    if recording.dataset and recording.dataset.site:
        site_summary = {
            "id": recording.dataset.site.id,
            "name": recording.dataset.site.name,
            "h3_index_member": recording.dataset.site.h3_index_member,
        }

    response = RecordingDetailResponse(
        **RecordingResponse.model_validate(recording).model_dump(),
        dataset=dataset_summary,
        site=site_summary,
        clip_count=clip_count,
        effective_duration=service.get_effective_duration(recording),
        is_ultrasonic=service.is_ultrasonic(recording),
    )
    # Recording responses do not embed a taxon — sensitivity is taxon-keyed
    # (FR-029 / FR-032), so the bulk preloaders would have no input here.
    # The Stage-2 filter still scrubs forbidden raw-coordinate fields and
    # applies the project-level non-member ceiling, which is the entirety
    # of the recording-shape obscure logic.
    apply_response_filter(
        obj=response,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=response,
        taxon_sensitivity_map={},
        override_map={},
    )
    return response


async def delete_recording(
    project_id: UUID,
    recording_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: RecordingServiceDep,
    db: DbSession,
) -> None:
    """Delete recording.

    Guarded by :data:`RECORDING_DELETE_ACTION`
    (:data:`Permission.MANAGE_DATASET`).

    Args:
        project_id: Project's UUID
        recording_id: Recording's UUID
        http_request: FastAPI :class:`Request` used by the gate to stash
            stage-1 state on ``request.state``.
        current_user: Current authenticated user
        service: Recording service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Access denied
        404: Recording not found
    """
    await gate_action(
        action=RECORDING_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )

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

    **Phase 17 backlog A-5 — Hybrid Contract:** the full-file streaming
    paths (``_iter_ogg_guarded`` / ``_iter_file_guarded``) re-evaluate
    the gate every :data:`AUDIO_RECHECK_INTERVAL` 65 KiB chunks. A
    detected mid-stream revoke writes ``stream.permission_revoked_mid_stream``
    audit telemetry and terminates the stream WITHOUT yielding a
    sentinel (audio containers cannot tolerate arbitrary bytes). HTTP
    Range responses (single-shot ``Response``) are explicitly **pre-start
    only** — once the slice is computed the response is single-shot and
    cannot be retroactively truncated.

    **Phase 5 (T202, FR-016, security H-8) — species-name leak guarantee:**
    This endpoint streams the raw bytes through FastAPI; it does NOT generate
    a presigned S3 URL on the response. Even if a future maintainer wires the
    response to a presigned URL, ``recording.path`` is built upstream as
    ``recordings/{project_id}/{dataset_id}/{recording_id}{ext}`` (see
    :func:`echoroo.workers.upload_tasks.recording_object_key`) — a UUID-only
    object key with no species identifier. H-8 therefore holds by construction.

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
    await gate_action(
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
                # No Range header: stream the full compressed file.
                #
                # Phase 17 backlog A-5 (Hybrid Contract): the full-file
                # streaming path re-checks the permission gate every
                # ``AUDIO_RECHECK_INTERVAL`` 65 KiB chunks. On a detected
                # mid-stream revoke we audit + return WITHOUT yielding a
                # sentinel (binary audio cannot tolerate arbitrary
                # bytes). Range responses (below) are pre-start guarded
                # only — see endpoint docstring.
                async def _iter_ogg_guarded() -> AsyncIterator[bytes]:
                    chunk_count = 0
                    user_id = getattr(current_user, "id", None)
                    request_id = getattr(getattr(request, "state", None), "request_id", "") or ""
                    client_obj = getattr(request, "client", None)
                    ip = getattr(client_obj, "host", "") or ""
                    try:
                        user_agent = request.headers.get("user-agent", "") or ""
                    except Exception:  # noqa: BLE001
                        user_agent = ""
                    with open(compressed_path, "rb") as f:
                        while chunk := f.read(65536):
                            chunk_count += 1
                            if chunk_count > 1 and chunk_count % AUDIO_RECHECK_INTERVAL == 0:
                                try:
                                    await recheck_action_permission(
                                        db=db,
                                        action=RECORDING_MEDIA_ACTION,
                                        project_id=project_id,
                                        current_user=current_user,
                                        request=request,
                                    )
                                except PermissionRevokedMidStream as exc:
                                    await audit_stream_revoked(
                                        project_id=project_id,
                                        user_id=user_id,
                                        stream_type="audio_ogg",
                                        request_id=request_id,
                                        ip=ip,
                                        user_agent=user_agent,
                                        reason=str(exc),
                                    )
                                    return
                            yield chunk

                # Phase 17 backlog A-5 Round 2 R1-C1 fix: do NOT advertise
                # ``Content-Length`` for the guarded full-file stream. A
                # mid-stream revoke aborts the generator early — sending the
                # original file size as ``Content-Length`` would leave HTTP
                # clients/proxies waiting for bytes that will never arrive
                # (incomplete-body errors, partial-download retry loops).
                # Starlette emits ``Transfer-Encoding: chunked`` when the
                # header is absent, so a closed connection unambiguously
                # signals the end of the response. ``Accept-Ranges`` is also
                # dropped here because chunked transfer cannot honour byte
                # ranges; the Range path below is preserved (single-shot
                # ``Response`` with both headers, see HTTP 206 branch).
                return StreamingResponse(
                    _iter_ogg_guarded(),
                    status_code=status.HTTP_200_OK,
                    media_type="audio/ogg",
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
            # Phase 17 backlog A-5 (Hybrid Contract): full-file WAV
            # streaming path. Same per-chunk guard cadence as the OGG
            # path; binary container so no sentinel on revoke.
            async def _iter_file_guarded() -> AsyncIterator[bytes]:
                chunk_count = 0
                user_id = getattr(current_user, "id", None)
                request_id = getattr(getattr(request, "state", None), "request_id", "") or ""
                client_obj = getattr(request, "client", None)
                ip = getattr(client_obj, "host", "") or ""
                try:
                    user_agent = request.headers.get("user-agent", "") or ""
                except Exception:  # noqa: BLE001
                    user_agent = ""
                with open(local_file_path, "rb") as f:
                    while chunk := f.read(65536):
                        chunk_count += 1
                        if chunk_count > 1 and chunk_count % AUDIO_RECHECK_INTERVAL == 0:
                            try:
                                await recheck_action_permission(
                                    db=db,
                                    action=RECORDING_MEDIA_ACTION,
                                    project_id=project_id,
                                    current_user=current_user,
                                    request=request,
                                )
                            except PermissionRevokedMidStream as exc:
                                await audit_stream_revoked(
                                    project_id=project_id,
                                    user_id=user_id,
                                    stream_type="audio_wav",
                                    request_id=request_id,
                                    ip=ip,
                                    user_agent=user_agent,
                                    reason=str(exc),
                                )
                                return
                        yield chunk

            # Phase 17 backlog A-5 Round 2 R1-C1 fix (see OGG branch
            # above): no ``Content-Length`` / ``Accept-Ranges`` on the
            # guarded full-file WAV stream. Mid-stream revoke aborts the
            # generator early; chunked transfer + connection close is the
            # only consistent termination signal.
            return StreamingResponse(
                _iter_file_guarded(),
                status_code=status.HTTP_200_OK,
                media_type="audio/wav",
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
# Browser-friendly target sample rate for real-time ultrasonic playback.
# A standard browser cannot play raw 192/256/384 kHz PCM, so ultrasonic
# recordings are resampled down to this rate for default (real-time) playback.
PLAYBACK_TARGET_SAMPLERATE = 48000


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

    Playback rule for ultrasonic recordings (samplerate > 96 kHz):

    - **Default (speed == 1.0): real-time playback.** The audio is genuinely
      resampled down to :data:`PLAYBACK_TARGET_SAMPLERATE` (~48 kHz) with
      anti-aliasing, so the output duration equals the original recording
      duration. Content above ~24 kHz is intentionally discarded — this is the
      accepted trade-off for real-time-by-default. (Previously the default
      rewrote the WAV header to a low rate, which played the PCM ~5.3× slower
      and pitch-shifted; that is no longer the default.)
    - **Explicit slower speed (speed < 1.0): time-expansion.** The legacy
      WAV-header-rewrite path is kept, shifting the *full* ultrasonic spectrum
      down into the audible band (so ultrasonic calls become hearable — the
      bat-detector use case). No resampling is done here, to avoid losing the
      ultrasonic content.

    Non-ultrasonic recordings are unchanged: passthrough at speed 1.0, and the
    existing per-speed header handling for explicit speeds.

    .. note::
        The contract exposes a single ``speed`` query parameter defaulting to
        1.0, so "default" and "explicit speed == 1.0" are indistinguishable.
        We therefore treat ultrasonic + ``speed == 1.0`` as the real-time
        resample case and ultrasonic + ``speed < 1.0`` as time-expansion.

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

    effective_speed = speed
    effective_te = recording.time_expansion
    target_samplerate: int | None = None

    if service.is_ultrasonic(recording):
        if speed == 1.0:
            # Default ultrasonic playback: REAL-TIME. Resample the (clip-bounded)
            # audio down to a browser-playable rate. With speed=1.0 and
            # time_expansion=1.0 the WAV header in load_clip_bytes resolves to
            # exactly PLAYBACK_TARGET_SAMPLERATE, so the output plays at original
            # speed/duration. This actually decodes + resamples (anti-aliased),
            # discarding content above ~24 kHz.
            #
            # Time-expansion semantics (intentional): for ultrasonic real-time
            # playback we intentionally ignore any stored ``time_expansion`` and
            # target 48 kHz at the file's wall-clock duration, so the output
            # duration matches ``recording.duration`` and the UI seek bar stays
            # consistent. Even when a recording carries a stored
            # ``time_expansion != 1.0`` (an independent field) we force
            # ``effective_te = 1.0`` here; the stored time_expansion is only
            # applied for acoustic time-expansion on the explicit slow-speed
            # path below (speed < 1.0). This is deliberate, not a regression.
            target_samplerate = PLAYBACK_TARGET_SAMPLERATE
            effective_speed = 1.0
            effective_te = 1.0
        else:
            # Explicit slower speed: keep the legacy time-expansion / header
            # rewrite so the full ultrasonic spectrum is shifted into the
            # audible band. The recording's stored time_expansion and the
            # requested speed feed the header formula in load_clip_bytes
            # (header_sr = output_sr * speed * time_expansion); no resampling.
            # ``target_samplerate`` is already ``None`` from the default above.
            effective_speed = speed
            effective_te = recording.time_expansion

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
        target_samplerate=target_samplerate,
        range=range,
    )


# T063: Spectrogram generation endpoint
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
    await gate_action(
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
#
# W2-4 PR-A (2026-07-04): the browser-superseded recording download route was
# unmounted from ``/api/v1`` in favour of the ``/web-api/v1`` BFF media-token
# surface. The handler body stays as an importable helper delegated to by
# ``echoroo.api.web_v1.projects._media.download_recording``; only the route
# decorator is removed here. The ``/audio`` and ``/stream`` media routes stay
# mounted (later PR).
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
    await gate_action(
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
