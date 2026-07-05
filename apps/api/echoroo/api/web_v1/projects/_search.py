"""Project search BFF adapters (spec/009 PR 4).

Spec/009 PR 4 moves the entire similarity-search + xeno-canto +
embedding-stats + search-annotation surface from ``/api/v1`` to
``/web-api/v1``. The legacy modules continue to own service
orchestration (S3 staging, Celery dispatch, locale enrichment, CSV
streaming via :class:`DetectionExportService`, multi-vector similarity
aggregates, XC proxy + SSRF guard); the BFF layer is a thin adapter
that:

* lands the request on the cookie + CSRF session boundary, and
* fires :func:`gate_action` with the per-endpoint Action constant
  before delegating to the legacy handler. The legacy handler's
  search-service dependency re-fires ``SEARCH_SESSION_LIST_ACTION``
  via :data:`AuthorizedSearchSessionServiceDep` — that is idempotent
  (per-request decision cache short-circuits the second call).

Endpoints (16, plus 2 streaming):

* GET    ``/{pid}/search/embedding-stats``                      → ``SEARCH_EMBEDDING_STATS_ACTION``
* GET    ``/{pid}/xeno-canto/search``                           → ``SEARCH_SESSION_LIST_ACTION`` (legacy unguarded baseline)
* GET    ``/{pid}/xeno-canto/audio/{xc_id}``                    → ``XENO_CANTO_AUDIO_ACTION`` (StreamingResponse)
* POST   ``/{pid}/search/batch``                                → ``SEARCH_BATCH_CREATE_ACTION``
* GET    ``/{pid}/search/jobs/{job_id}``                        → ``SEARCH_BATCH_JOB_GET_ACTION``
* POST   ``/{pid}/annotations``                                 → ``SEARCH_ANNOTATION_ACTION``
* GET    ``/{pid}/search/sessions``                             → ``SEARCH_SESSION_LIST_ACTION``
* GET    ``/{pid}/search/sessions/{session_id}``                → ``SEARCH_SESSION_GET_ACTION``
* DELETE ``/{pid}/search/sessions/{session_id}``                → ``SEARCH_SESSION_DELETE_ACTION``
* PATCH  ``/{pid}/search/sessions/{session_id}``                → ``SEARCH_SESSION_UPDATE_ACTION``
* PUT    ``/{pid}/search/sessions/{session_id}/rerun``          → ``SEARCH_SESSION_RERUN_ACTION``
* GET    ``/{pid}/search/sessions/{session_id}/distribution``   → ``SEARCH_SESSION_DISTRIBUTION_ACTION``
* GET    ``/{pid}/search/sessions/{session_id}/time-distribution`` → ``SEARCH_SESSION_TIME_DISTRIBUTION_ACTION``
* GET    ``/{pid}/search/sessions/{session_id}/sample``         → ``SEARCH_SESSION_SAMPLE_ACTION``
* GET    ``/{pid}/search/sessions/{session_id}/export/csv``     → ``SEARCH_SESSION_EXPORT_CSV_ACTION`` (StreamingResponse)
* GET    ``/{pid}/search/sessions/{session_id}/export-recordings`` → ``SEARCH_SESSION_EXPORT_RECORDINGS_ACTION`` (StreamingResponse)

W2-4 PR-B resolves the previously-deferred reference-audio endpoint:

* ``POST /{pid}/search/sessions/{session_id}/reference-audio/{idx}/media-token``
  → ``SEARCH_SESSION_REFERENCE_AUDIO_ACTION`` — issues a scoped
  ``search_session`` media token (scope ``"audio"``, bound to ``source_index``).
* ``GET  /{pid}/search/sessions/{session_id}/reference-audio/{idx}``
  → ``SEARCH_SESSION_REFERENCE_AUDIO_ACTION`` — delegates to the legacy
  streaming handler. Native ``<audio>`` elements authenticate via the
  ``?media_token=`` query param the auth-router matcher resolves.

Out of scope for this PR:

* Sonogram proxy (``/xeno-canto/sonogram``) — invoked from inside the
  rewritten ``XenoCantoRecording.sonogram_url`` strings emitted by the
  legacy search response, not from a typed frontend caller.
* ``POST /{pid}/search/similar`` + ``/similar-by-audio`` — legacy
  similarity endpoints are not consumed by the spec-009 PR 4 frontend
  surface (the UX flow goes through ``/batch`` instead).

Permission guard allowlist
--------------------------

``search_xeno_canto`` in the legacy module uses ``check_project_access``
rather than ``gate_action``. The BFF adapter mirrors that decision by
firing ``SEARCH_SESSION_LIST_ACTION`` (the broad "user can use search
in this project" baseline shared by every search route via the service
dependency); this is recorded in
``scripts/allowlists/permission_guard_allowlist.txt`` as a thin-adapter
allowlist entry because the lint expects each Action to be named
``XENO_CANTO_SEARCH_ACTION`` for a route ending in ``/search``.

Response filter allowlist
-------------------------

``create_search_annotation`` returns :class:`DetectionResponse` which
the lint flags as a Detection-named response. The legacy entry is
already allowlisted; the BFF adapter is added with the same
``Phase 3 US11 T1xx`` rationale.

Route order note
----------------

Literal sub-paths under ``/sessions/{session_id}/`` (``distribution``,
``time-distribution``, ``sample``, ``rerun``, ``export/csv``,
``export-recordings``) are declared BEFORE the bare ``{session_id}``
family. The literal segments still match deterministically because
FastAPI route lookup falls back to longer literal matches first, but
keeping declaration order aligned with the legacy router preserves the
debug-time obviousness. The legacy ``api/v1/search/sessions.py`` uses
this exact ordering.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import StreamingResponse

from echoroo.api.v1 import xeno_canto as legacy_xeno_canto
from echoroo.api.v1.search import annotations as legacy_search_annotations
from echoroo.api.v1.search import batch as legacy_search_batch
from echoroo.api.v1.search import deps as legacy_search_deps
from echoroo.api.v1.search import sessions as legacy_search_sessions
from echoroo.api.v1.search import similarity as legacy_search_similarity
from echoroo.api.web_v1.projects._media import MediaTokenResponse
from echoroo.core.actions import (
    SEARCH_ANNOTATION_ACTION,
    SEARCH_BATCH_CREATE_ACTION,
    SEARCH_BATCH_JOB_GET_ACTION,
    SEARCH_EMBEDDING_STATS_ACTION,
    SEARCH_SESSION_DELETE_ACTION,
    SEARCH_SESSION_DISTRIBUTION_ACTION,
    SEARCH_SESSION_EXPORT_CSV_ACTION,
    SEARCH_SESSION_EXPORT_RECORDINGS_ACTION,
    SEARCH_SESSION_GET_ACTION,
    SEARCH_SESSION_LIST_ACTION,
    SEARCH_SESSION_REFERENCE_AUDIO_ACTION,
    SEARCH_SESSION_RERUN_ACTION,
    SEARCH_SESSION_SAMPLE_ACTION,
    SEARCH_SESSION_TIME_DISTRIBUTION_ACTION,
    SEARCH_SESSION_UPDATE_ACTION,
    XENO_CANTO_AUDIO_ACTION,
)
from echoroo.core.auth import DEFAULT_MEDIA_TTL, issue_media_token
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.detection import DetectionResponse
from echoroo.schemas.search import (
    EmbeddingStatsResponse,
    SearchAnnotationCreate,
    SearchJobAcceptedResponse,
    SearchJobStatusResponse,
    SearchSessionListResponse,
    SearchSessionResponse,
    SessionDistributionResponse,
    SessionSampleResponse,
    SessionTimeDistributionResponse,
)
from echoroo.schemas.xeno_canto import XenoCantoSearchResponse

router = APIRouter()


# ---------------------------------------------------------------------------
# Embedding stats
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/search/embedding-stats",
    response_model=EmbeddingStatsResponse,
    summary="Embedding statistics",
    description="BFF adapter for the legacy embedding-stats endpoint.",
)
async def get_embedding_stats(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_search_deps.AuthorizedSearchServiceDep,
    dataset_id: UUID | None = None,
) -> EmbeddingStatsResponse:
    """Delegate embedding-stats to the legacy handler."""
    await gate_action(
        action=SEARCH_EMBEDDING_STATS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_similarity.get_embedding_stats(
        project_id=project_id,
        service=service,
        dataset_id=dataset_id,
    )


# ---------------------------------------------------------------------------
# Xeno-canto search + audio proxy
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/xeno-canto/search",
    response_model=XenoCantoSearchResponse,
    summary="Search Xeno-canto recordings",
    description="BFF adapter for the legacy Xeno-canto search proxy.",
)
async def search_xeno_canto(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    query: str = Query(..., min_length=1),
    country: str | None = Query(default=None),
    area: str | None = Query(default=None),
    quality_min: str | None = Query(default=None),
    recording_type: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(
        default=25, ge=1, le=legacy_xeno_canto.XENO_CANTO_MAX_PER_PAGE
    ),
) -> XenoCantoSearchResponse:
    """Delegate Xeno-canto search to the legacy proxy."""
    # Legacy uses ``check_project_access``; mirror it through the broad
    # SEARCH_SESSION_LIST_ACTION baseline so the BFF layer still gates
    # with a canonical Action constant.
    await gate_action(
        action=SEARCH_SESSION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_xeno_canto.search_xeno_canto(
        project_id=project_id,
        current_user=current_user,
        db=db,
        query=query,
        country=country,
        area=area,
        quality_min=quality_min,
        recording_type=recording_type,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/{project_id}/xeno-canto/audio/{xc_id}",
    summary="Proxy Xeno-canto audio download",
    description="BFF adapter for the legacy Xeno-canto audio streaming proxy.",
)
async def proxy_xeno_canto_audio(
    project_id: UUID,
    xc_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> StreamingResponse:
    """Delegate Xeno-canto audio streaming to the legacy proxy."""
    await gate_action(
        action=XENO_CANTO_AUDIO_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_xeno_canto.proxy_audio(
        project_id=project_id,
        xc_id=xc_id,
        request=request,
        current_user=current_user,
        db=db,
    )


# ---------------------------------------------------------------------------
# Batch search + job polling
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/search/batch",
    response_model=SearchJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit batch species search",
    description="BFF adapter for the legacy batch-search submit endpoint.",
)
async def submit_batch_search(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    request: Request,
    metadata: str = Form(...),
) -> SearchJobAcceptedResponse:
    """Delegate batch-search submission to the legacy handler."""
    await gate_action(
        action=SEARCH_BATCH_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_batch.batch_search(
        project_id=project_id,
        current_user=current_user,
        db=db,
        request=request,
        metadata=metadata,
    )


@router.get(
    "/{project_id}/search/jobs/{job_id}",
    response_model=SearchJobStatusResponse,
    summary="Get batch search job status",
    description="BFF adapter for the legacy job-status polling endpoint.",
)
async def get_search_job_status(
    project_id: UUID,
    job_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    locale: str = "en",
) -> SearchJobStatusResponse:
    """Delegate job-status polling to the legacy handler."""
    await gate_action(
        action=SEARCH_BATCH_JOB_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_batch.get_search_job(
        project_id=project_id,
        job_id=job_id,
        request=request,
        current_user=current_user,
        db=db,
        locale=locale,
    )


# ---------------------------------------------------------------------------
# Search annotation
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/annotations",
    response_model=DetectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation from search match",
    description="BFF adapter for the legacy search-annotation creation endpoint.",
)
async def create_annotation_from_search(
    project_id: UUID,
    request: SearchAnnotationCreate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> DetectionResponse:
    """Delegate search-annotation creation to the legacy handler."""
    await gate_action(
        action=SEARCH_ANNOTATION_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_search_annotations.create_search_annotation(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        db=db,
    )


# ---------------------------------------------------------------------------
# Search session literal sub-paths — declared before bare ``{session_id}``
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/search/sessions/{session_id}/distribution",
    response_model=SessionDistributionResponse,
    summary="Session similarity distribution",
    description="BFF adapter for the legacy session-distribution endpoint.",
)
async def get_session_distribution(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    bin_width: float = Query(default=0.05, ge=0.01, le=0.5),
    species_key: str | None = Query(default=None),
) -> SessionDistributionResponse:
    """Delegate session distribution to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_DISTRIBUTION_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.get_session_similarity_distribution(
        project_id=project_id,
        session_id=session_id,
        db=db,
        session_service=session_service,
        bin_width=bin_width,
        species_key=species_key,
    )


@router.get(
    "/{project_id}/search/sessions/{session_id}/time-distribution",
    response_model=SessionTimeDistributionResponse,
    summary="Session time-of-day distribution",
    description="BFF adapter for the legacy session-time-distribution endpoint.",
)
async def get_session_time_distribution(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    species_key: str | None = Query(default=None),
) -> SessionTimeDistributionResponse:
    """Delegate session time distribution to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_TIME_DISTRIBUTION_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.get_session_time_distribution(
        project_id=project_id,
        session_id=session_id,
        db=db,
        session_service=session_service,
        species_key=species_key,
    )


@router.get(
    "/{project_id}/search/sessions/{session_id}/sample",
    response_model=SessionSampleResponse,
    summary="Session similarity sample",
    description="BFF adapter for the legacy session-sample endpoint.",
)
async def get_session_sample(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    min_similarity: float = Query(default=0.0, ge=0.0, le=1.0),
    max_similarity: float = Query(default=1.0, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=200),
    species_key: str | None = Query(default=None),
) -> SessionSampleResponse:
    """Delegate session sample to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_SAMPLE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.sample_session_similarity_range(
        project_id=project_id,
        session_id=session_id,
        db=db,
        session_service=session_service,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        limit=limit,
        species_key=species_key,
    )


@router.put(
    "/{project_id}/search/sessions/{session_id}/rerun",
    response_model=SearchJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a search session",
    description="BFF adapter for the legacy session-rerun endpoint.",
)
async def rerun_search_session(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    request: Request,
    metadata: str = Form(...),
) -> SearchJobAcceptedResponse:
    """Delegate session rerun to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_RERUN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.rerun_search_session(
        project_id=project_id,
        session_id=session_id,
        current_user=current_user,
        db=db,
        session_service=session_service,
        request=request,
        metadata=metadata,
    )


@router.get(
    "/{project_id}/search/sessions/{session_id}/export/csv",
    summary="Export session annotations as CSV",
    description="BFF adapter for the legacy session CSV export streaming endpoint.",
)
async def export_search_session_csv(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
) -> StreamingResponse:
    """Delegate session CSV export to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_EXPORT_CSV_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.export_search_session_csv(
        project_id=project_id,
        session_id=session_id,
        request=request,
        current_user=current_user,
        db=db,
        session_service=session_service,
    )


@router.get(
    "/{project_id}/search/sessions/{session_id}/export-recordings",
    summary="Export per-(recording × species) CSV",
    description="BFF adapter for the legacy export-recordings streaming endpoint.",
)
async def export_search_session_recordings_csv(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    locale: str = Query(default="en"),
) -> StreamingResponse:
    """Delegate export-recordings CSV to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_EXPORT_RECORDINGS_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.export_search_session_recordings_csv(
        project_id=project_id,
        session_id=session_id,
        request=request,
        current_user=current_user,
        db=db,
        session_service=session_service,
        locale=locale,
    )


# ---------------------------------------------------------------------------
# Search session reference audio (media-token surface, W2-4 PR-B)
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/search/sessions/{session_id}/reference-audio/{source_index}/media-token",
    response_model=MediaTokenResponse,
    summary="Issue a scoped search-session reference-audio media token",
    description=(
        "Issue a short-lived JWT scoped to one reference-audio source of a "
        "search session, for native ``<audio>`` streaming."
    ),
)
async def issue_reference_audio_media_token(
    project_id: UUID,
    session_id: UUID,
    source_index: int,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
) -> MediaTokenResponse:
    """Gate the reference-audio action, then issue a session+index-scoped token.

    The token binds ``resource_type="search_session"`` + the session id with
    scope ``"audio"`` and the ``source_index`` so a native ``<audio>`` element
    can authenticate the streaming GET without an Authorization header. The
    ``source_index`` must be in range for the session's
    ``reference_audio_keys`` list (404 otherwise, anti-enumeration).
    """
    await gate_action(
        action=SEARCH_SESSION_REFERENCE_AUDIO_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    session = await session_service.get_session(session_id, project_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference audio not found",
        )

    keys = session.reference_audio_keys or []
    if source_index < 0 or source_index >= len(keys):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference audio not found",
        )

    token = issue_media_token(
        user_id=current_user.id,
        security_stamp=current_user.security_stamp,
        project_id=project_id,
        resource_type="search_session",
        resource_id=session_id,
        scope="audio",
        source_index=source_index,
        ttl=DEFAULT_MEDIA_TTL,
    )
    return MediaTokenResponse(
        token=token,
        expires_in=int(DEFAULT_MEDIA_TTL.total_seconds()),
    )


@router.get(
    "/{project_id}/search/sessions/{session_id}/reference-audio/{source_index}",
    summary="Stream reference audio for a search session",
    description="BFF adapter for the legacy session reference-audio stream.",
)
async def stream_reference_audio(
    project_id: UUID,
    session_id: UUID,
    source_index: int,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    range: str | None = Header(None),
) -> StreamingResponse:
    """Delegate reference-audio streaming to the legacy handler.

    Native ``<audio>`` elements authenticate via a scoped media token (the
    auth-router matcher resolves it) so this GET keeps HTTP Range semantics
    unchanged from the legacy handler.
    """
    await gate_action(
        action=SEARCH_SESSION_REFERENCE_AUDIO_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.stream_reference_audio(
        project_id=project_id,
        session_id=session_id,
        source_index=source_index,
        request=request,
        current_user=current_user,
        db=db,
        session_service=session_service,
        range=range,
    )


# ---------------------------------------------------------------------------
# Search session collection + bare ``{session_id}`` family
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/search/sessions",
    response_model=SearchSessionListResponse,
    summary="List search sessions",
    description="BFF adapter for the legacy session list endpoint.",
)
async def list_search_sessions(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    locale: str = "en",
) -> SearchSessionListResponse:
    """Delegate session list to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.list_search_sessions(
        project_id=project_id,
        db=db,
        session_service=session_service,
        limit=limit,
        offset=offset,
        locale=locale,
    )


@router.get(
    "/{project_id}/search/sessions/{session_id}",
    response_model=SearchSessionResponse,
    summary="Get search session detail",
    description="BFF adapter for the legacy session detail endpoint.",
)
async def get_search_session(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    locale: str = "en",
) -> SearchSessionResponse:
    """Delegate session detail to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.get_search_session(
        project_id=project_id,
        session_id=session_id,
        db=db,
        session_service=session_service,
        locale=locale,
    )


@router.delete(
    "/{project_id}/search/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete search session",
    description="BFF adapter for the legacy session delete endpoint.",
)
async def delete_search_session(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
) -> Response:
    """Delegate session delete to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.delete_search_session(
        project_id=project_id,
        session_id=session_id,
        db=db,
        session_service=session_service,
    )


@router.patch(
    "/{project_id}/search/sessions/{session_id}",
    response_model=SearchSessionResponse,
    summary="Update search session",
    description="BFF adapter for the legacy session update endpoint.",
)
async def update_search_session(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: legacy_search_deps.AuthorizedSearchSessionServiceDep,
    name: str = Body(..., embed=True),
) -> SearchSessionResponse:
    """Delegate session update to the legacy handler."""
    await gate_action(
        action=SEARCH_SESSION_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_search_sessions.update_search_session(
        project_id=project_id,
        session_id=session_id,
        db=db,
        session_service=session_service,
        name=name,
    )


