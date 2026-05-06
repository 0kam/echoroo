"""Search session CRUD endpoints.

Handles listing, getting, updating, deleting, and re-running search sessions,
as well as streaming reference audio and exporting session annotations as CSV.
"""

from __future__ import annotations

import collections.abc
import contextlib
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
from sqlalchemy import text

from echoroo.api.v1.search.batch import _prepare_batch_job
from echoroo.api.v1.search.deps import AuthorizedSearchSessionServiceDep
from echoroo.core.database import DbSession
from echoroo.core.s3 import delete_object, delete_objects_by_prefix
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.search import (
    BatchSearchResponse,
    SearchJobAcceptedResponse,
    SearchSessionListItem,
    SearchSessionListResponse,
    SearchSessionResponse,
    SessionDistributionResponse,
    SessionSampleResponse,
    SessionTimeDistributionResponse,
    TimeDistributionCell,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Search session endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=SearchSessionListResponse,
    summary="List search sessions",
    description=(
        "List paginated batch search sessions for a project, ordered by creation date descending. "
        "Pass ?locale=ja to receive locale-specific common names in species_config."
    ),
)
async def list_search_sessions(
    project_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    locale: str = "en",
) -> SearchSessionListResponse:
    """List search sessions for a project.

    When locale is provided (e.g. "ja"), common names in species_config
    are enriched with locale-specific vernacular names.

    Args:
        project_id: Project UUID (path parameter)
        db: Database session
        session_service: Authorized search session service
        limit: Maximum number of results
        offset: Number of results to skip
        locale: Locale code for common name resolution (default: "en")

    Returns:
        Paginated list of search sessions

    Raises:
        403: Access denied to project
    """
    from echoroo.api.v1.search.utils import _enrich_species_config_with_locale

    sessions, total = await session_service.list_sessions(project_id, limit, offset)
    items = [SearchSessionListItem.model_validate(s) for s in sessions]

    # Enrich species_config with common names (works for all locales)
    for item in items:
        if item.species_config:
            try:
                item.species_config = await _enrich_species_config_with_locale(
                    item.species_config, locale, db
                )
            except Exception:
                logger.warning(
                    "Failed to enrich species_config for session list item with locale=%r",
                    locale,
                    exc_info=True,
                )

    return SearchSessionListResponse(sessions=items, total=total)


@router.get(
    "/sessions/{session_id}",
    response_model=SearchSessionResponse,
    summary="Get search session detail",
    description=(
        "Get full search session detail with review status merged into results. "
        "Pass ?locale=ja to receive locale-specific common names in results and species_config."
    ),
)
async def get_search_session(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    locale: str = "en",
) -> SearchSessionResponse:
    """Get a search session with review status merged into results.

    When locale is provided (e.g. "ja"), common names in the results and
    species_config are enriched with locale-specific vernacular names from
    the taxon_vernacular_names table.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service
        locale: Locale code for common name resolution (default: "en")

    Returns:
        SearchSessionResponse with live review status merged into results

    Raises:
        403: Access denied to project
        404: Session not found
    """
    from echoroo.api.v1.search.utils import (
        _enrich_search_results_with_locale,
        _enrich_species_config_with_locale,
    )

    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    merged_results = await session_service.get_session_results_with_review_status(
        session_id, project_id, session=session
    )

    response = SearchSessionResponse.model_validate(session)
    if merged_results is not None:
        response.results = merged_results

    # Enrich results with locale-specific vernacular names
    if locale != "en" and response.results is not None:
        try:
            raw_results = response.results
            if isinstance(raw_results, dict):
                inner = raw_results.get("results")
                if isinstance(inner, dict):
                    batch_resp = BatchSearchResponse.model_validate(raw_results)
                    enriched = await _enrich_search_results_with_locale(batch_resp, locale, db)
                    # Merge enriched common_name back into the raw results dict
                    for key, species_data in inner.items():
                        if isinstance(species_data, dict) and key in enriched.results:
                            species_data["common_name"] = enriched.results[key].common_name
        except Exception:
            logger.warning("Failed to enrich session results with locale=%r", locale, exc_info=True)

    # Enrich species_config with common names (works for all locales)
    if response.species_config:
        try:
            response.species_config = await _enrich_species_config_with_locale(
                response.species_config, locale, db
            )
        except Exception:
            logger.warning("Failed to enrich species_config with locale=%r", locale, exc_info=True)

    return response


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete search session",
    description="Delete a search session. S3 reference audio files are cleaned up on a best-effort basis.",
)
async def delete_search_session(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
) -> Response:
    """Delete a search session and attempt S3 cleanup of reference audio.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service

    Returns:
        204 No Content

    Raises:
        403: Access denied to project
        404: Session not found
    """
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    # Snapshot old reference-audio S3 keys BEFORE the service mutates the ORM
    # instance. reference_audio_keys is a JSON column; a value copy ensures the
    # post-commit cleanup sees the pre-delete key set regardless of what the
    # service does to the attribute (or ORM state) before commit.
    stale_keys: list[str] = list(session.reference_audio_keys or [])

    await session_service.delete_session(session_id, project_id)
    await db.commit()

    # Post-commit: best-effort cleanup of reference audio. If the commit raised,
    # we never reach this block, so the session (still referencing stale_keys)
    # remains consistent with S3.
    for key in stale_keys:
        try:
            delete_object(key)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.warning(
                "Failed to delete reference audio %s after session delete: %s", key, exc
            )

    return Response(status_code=204)


@router.patch(
    "/sessions/{session_id}",
    response_model=SearchSessionResponse,
    summary="Update search session",
    description="Update a search session's name.",
)
async def update_search_session(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    name: str = Body(..., embed=True),
) -> SearchSessionResponse:
    """Update a search session's name.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service
        name: New session name

    Returns:
        Updated SearchSessionResponse

    Raises:
        403: Access denied to project
        404: Session not found
    """
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    session.name = name
    await db.commit()
    await db.refresh(session)
    return SearchSessionResponse.model_validate(session)


@router.put(
    "/sessions/{session_id}/rerun",
    response_model=SearchJobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a search session with updated reference sources",
    description=(
        "Update a session's species_config and re-run the search. "
        "Clears existing results and annotations, resets status to pending, "
        "and dispatches a new Celery search task. "
        "Send as multipart/form-data with a 'metadata' JSON field and optional audio files."
    ),
)
async def rerun_search_session(
    project_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    request: Request,
    metadata: str = Form(
        ...,
        description="JSON string of BatchSearchRequest",
    ),
) -> SearchJobAcceptedResponse:
    """Re-run an existing search session with updated reference sources.

    Clears existing annotations for this session, resets status and results,
    then dispatches a new search task reusing the same session record.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        current_user: Current authenticated user
        db: Database session
        session_service: Search session service
        request: Raw FastAPI request (to access multipart form data)
        metadata: JSON string encoding a BatchSearchRequest

    Returns:
        202 Accepted with job_id and session_id

    Raises:
        400: Malformed metadata JSON
        403: Access denied to project
        404: Session not found
        413: One or more uploaded files exceed 10 MB
        422: Constraint violation or invalid model
    """
    # Fetch and validate the session
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    # Validate input, stage S3 reference audio, and build the job manifest.
    # Any validation / upload failure is already cleaned up inside the helper.
    artifacts = await _prepare_batch_job(
        db=db,
        project_id=project_id,
        current_user_id=current_user.id,
        request=request,
        metadata=metadata,
        log_tag="rerun job",
    )

    # Snapshot old reference-audio S3 keys BEFORE the service mutates the ORM
    # instance. reference_audio_keys is a JSON column; taking a value copy
    # ensures the post-commit cleanup sees the pre-rerun key set regardless of
    # how the service later assigns the attribute.
    stale_keys: list[str] = list(session.reference_audio_keys or [])

    parameters: dict[str, object] = {
        "min_similarity": artifacts.batch_request.min_similarity,
        "limit_per_species": artifacts.batch_request.limit_per_species,
        "dataset_id": artifacts.batch_request.dataset_id,
    }

    # Delegate annotation DELETE + session field reset + name regeneration to
    # the service. The service stays S3-free, so cleanup of old reference
    # audio is orchestrated here (after commit succeeds).
    await session_service.reset_for_rerun(
        session=session,
        job_id=artifacts.job_id,
        model_name=artifacts.batch_request.model_name,
        parameters=parameters,
        species_config=artifacts.species_config_with_s3,
        reference_audio_keys=artifacts.all_s3_keys if artifacts.all_s3_keys else None,
    )

    # Commit first; if it fails, roll back the newly uploaded S3 objects and
    # tmp dir so we don't leak storage. This mirrors the POST /batch path.
    try:
        await db.commit()
    except Exception:
        with contextlib.suppress(Exception):
            delete_objects_by_prefix(artifacts.s3_prefix)
        shutil.rmtree(Path(f"/data/search_tmp/{artifacts.job_id}"), ignore_errors=True)
        raise

    # Post-commit: best-effort cleanup of the *old* reference audio. Only
    # delete keys that are no longer referenced by the new session state.
    new_keys_set: set[str] = set(artifacts.all_s3_keys or [])
    keys_to_delete = [k for k in stale_keys if k not in new_keys_set]
    for key in keys_to_delete:
        try:
            delete_object(key)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.warning(
                "Failed to delete stale reference audio %s after rerun: %s", key, exc
            )

    # Dispatch Celery task
    from echoroo.workers.search_tasks import run_batch_search

    run_batch_search.apply_async(
        args=[artifacts.job_id, str(project_id)],
        task_id=artifacts.job_id,
    )

    return SearchJobAcceptedResponse(
        job_id=artifacts.job_id, status="pending", session_id=session.id
    )


@router.get(
    "/sessions/{session_id}/reference-audio/{source_index}",
    summary="Stream reference audio for a search session",
    description=(
        "Stream a persisted reference audio file for a search session by its index "
        "in the reference_audio_keys list. Supports HTTP Range requests."
    ),
)
async def stream_reference_audio(
    project_id: UUID,
    session_id: UUID,
    source_index: int,
    session_service: AuthorizedSearchSessionServiceDep,
    range: str | None = Header(None),
) -> StreamingResponse:
    """Stream a reference audio file stored in S3 for a search session.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        source_index: Index into the session's reference_audio_keys list
        session_service: Authorized search session service
        range: Optional HTTP Range header for partial content streaming

    Returns:
        StreamingResponse with audio content

    Raises:
        403: Access denied to project
        404: Session not found or source_index out of bounds
        500: S3 retrieval error
    """
    import mimetypes

    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    if not session.reference_audio_keys or source_index >= len(session.reference_audio_keys):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reference audio source index {source_index} not found",
        )

    if source_index < 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid source index",
        )

    s3_key = session.reference_audio_keys[source_index]

    try:
        from echoroo.core.s3 import get_s3_client as _get_s3_stream_client
        from echoroo.core.settings import get_settings as _get_stream_settings

        _stream_settings = _get_stream_settings()
        _stream_client = _get_s3_stream_client()
        s3_params: dict[str, Any] = {
            "Bucket": _stream_settings.S3_BUCKET,
            "Key": s3_key,
        }
        if range:
            s3_params["Range"] = range
        s3_response = _stream_client.get_object(**s3_params)
    except Exception as exc:
        logger.exception("Failed to stream reference audio key=%s", s3_key)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve reference audio from storage",
        ) from exc

    body = s3_response["Body"]
    content_length = s3_response.get("ContentLength")

    # Determine content type from file extension
    suffix = Path(s3_key).suffix.lower()
    content_type, _ = mimetypes.guess_type(f"file{suffix}")
    if not content_type:
        content_type = "audio/wav"

    def _iter_stream() -> collections.abc.Iterator[bytes]:
        try:
            while True:
                chunk = body.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    response_headers: dict[str, str] = {}
    if content_length is not None:
        response_headers["Content-Length"] = str(content_length)
    response_headers["Accept-Ranges"] = "bytes"

    response_status = 206 if range else 200
    if range and "ContentRange" in s3_response:
        response_headers["Content-Range"] = s3_response["ContentRange"]

    return StreamingResponse(
        _iter_stream(),
        status_code=response_status,
        media_type=content_type,
        headers=response_headers,
    )


async def _build_species_labels(
    session: Any,
    db: Any,
) -> tuple[dict[str, str], list[str]]:
    """Resolve the species_key list and their scientific-name labels.

    Responsibilities consolidated from the original inline block:

    - Pulls the ``results`` dict out of ``session.results`` and validates
      its shape, raising 404 on malformed or empty results using the
      documented detail strings.
    - Computes ``species_keys`` as the ordered list of result keys
      (tag UUIDs) in the session's results payload.
    - Builds ``species_labels`` (species_key → scientific_name) via a
      two-pass lookup whose ordering MUST be preserved for behaviour
      parity: first pass matches by ``species_config[*].tag_id``, second
      pass falls back to a ``tags`` table query by scientific_name for
      any keys still unmapped (typical when the session was created from
      a URL-source tag with no pre-existing tag_id).

    Args:
        session: SearchSession ORM instance. ``results`` is the canonical
            source for ``species_keys``; ``species_config`` (optional) is
            used for display labels.
        db: AsyncSession used for the tags fallback lookup.

    Returns:
        Tuple of (species_labels, species_keys). ``species_labels`` only
        contains entries for keys that were successfully resolved.

    Raises:
        HTTPException 404: When ``session.results["results"]`` is not a
            dict (``"Session has no results to export"``) or contains no
            species keys (``"Session has no species results to export"``).
    """
    # Extract all species from the session's results.
    # Each result key matches the species_config tag_id used during search.
    raw_results = session.results.get("results")
    if not isinstance(raw_results, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to export",
        )

    species_keys: list[str] = list(raw_results.keys())
    if not species_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no species results to export",
        )

    # Build display name mapping: species_key -> scientific name.
    #
    # The keys in raw_results are tag UUIDs. species_config entries may have
    # tag_id=null (when the search was created from a URL source without an
    # existing tag), so we fall back to looking up the tag by scientific_name.
    species_labels: dict[str, str] = {}

    # First pass: map by tag_id when available
    if session.species_config and isinstance(session.species_config, list):
        for sp_cfg in session.species_config:
            if not isinstance(sp_cfg, dict):
                continue
            sp_tag_id = str(sp_cfg.get("tag_id") or "")
            sp_sci_name = str(sp_cfg.get("scientific_name") or "")
            label = sp_sci_name or sp_tag_id or "Unknown"
            for key in species_keys:
                if sp_tag_id and key == sp_tag_id:
                    species_labels[key] = label

    # Second pass: for keys still unmapped, look up tag by scientific_name
    unmapped_keys = [k for k in species_keys if k not in species_labels]
    if unmapped_keys and session.species_config and isinstance(session.species_config, list):
        sci_names_in_config = [
            str(sp_cfg.get("scientific_name") or "")
            for sp_cfg in session.species_config
            if isinstance(sp_cfg, dict) and sp_cfg.get("scientific_name")
        ]
        if sci_names_in_config:
            tag_lookup_sql = text(
                "SELECT id::text, scientific_name FROM tags "
                "WHERE id = ANY(:ids) OR scientific_name = ANY(:names)"
            )
            tag_rows = (
                await db.execute(
                    tag_lookup_sql,
                    {"ids": unmapped_keys, "names": sci_names_in_config},
                )
            ).fetchall()
            # Build: tag_id -> scientific_name from DB
            tag_id_to_sci: dict[str, str] = {
                str(row[0]): str(row[1]) for row in tag_rows if row[1]
            }
            for key in unmapped_keys:
                if key in tag_id_to_sci:
                    species_labels[key] = tag_id_to_sci[key]

    return species_labels, species_keys


async def _fetch_session_recordings(
    session: Any,
    project_id: UUID,
    db: Any,
) -> list[tuple[str, str, str | None]]:
    """Fetch the project's recordings (optionally filtered by dataset_id).

    Extracts the ``dataset_id`` filter from ``session.parameters`` (nullable)
    and returns every recording in the project whose dataset matches.
    Timestamps are converted into the dataset's configured timezone (falling
    back to UTC) so the CSV consumer sees wall-clock times consistent with
    the session-detail UI.

    Args:
        session: SearchSession ORM instance (``parameters`` attr read).
        project_id: Project UUID used to scope the recordings query.
        db: AsyncSession.

    Returns:
        Ordered list of ``(recording_id, recording_filename, recording_datetime)``
        tuples sorted by recording_datetime ASC (NULLs last, then filename
        ASC for stable ordering).
    """
    # Determine optional dataset filter from session parameters
    dataset_id_str: str | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        dataset_id_str = str(session.parameters["dataset_id"])

    # Returns: recording_id, recording_filename, recording_datetime (in dataset tz)
    dataset_filter_sql = "AND d.id = :dataset_id" if dataset_id_str else ""
    recordings_sql = text(
        f"""
        SELECT
            r.id::text AS recording_id,
            r.filename AS recording_filename,
            CASE
                WHEN r.datetime IS NOT NULL THEN
                    (r.datetime AT TIME ZONE COALESCE(d.datetime_timezone, 'UTC'))::text
                ELSE NULL
            END AS recording_datetime
        FROM recordings r
        JOIN datasets d ON r.dataset_id = d.id
        WHERE d.project_id = :project_id
          {dataset_filter_sql}
        ORDER BY r.datetime ASC NULLS LAST, r.filename ASC
        """
    )
    rec_params: dict[str, object] = {"project_id": str(project_id)}
    if dataset_id_str:
        rec_params["dataset_id"] = dataset_id_str

    rec_rows = (await db.execute(recordings_sql, rec_params)).fetchall()

    # Build an ordered list of (recording_id, filename, datetime_str)
    return [
        (str(row.recording_id), str(row.recording_filename), row.recording_datetime)
        for row in rec_rows
    ]


async def _resolve_locale_common_names(
    session: Any,
    species_keys: list[str],
    species_labels: dict[str, str],
    locale: str,
    db: Any,
) -> dict[str, str]:
    """Resolve ``species_key -> common_name`` for the export-recordings CSV.

    Mirrors the locale-enrichment guard used by the list/detail routes: when
    ``_enrich_species_config_with_locale`` raises (e.g. transient GBIF outage
    or an internal SQLAlchemy greenlet error), we MUST NOT bubble the failure
    up as a 500. Instead we log a warning and fall back to the raw
    ``session.species_config``.  If the raw config still has ``common_name``
    values populated (typical when the search was created from a local tag),
    those are preserved in the returned mapping so the CSV does not suddenly
    lose its ``common_name`` column content.

    Args:
        session: SearchSession ORM instance (``species_config`` attr read).
        species_keys: Ordered list of species keys (tag UUIDs) from the
            session results. Only keys present here are populated in the
            returned dict.
        species_labels: Mapping of species_key → scientific_name used to
            join against the ``sci_name -> common_name`` lookup.
        locale: Locale string (``en``/``ja``) passed through to the
            enrichment helper.
        db: AsyncSession for GBIF / vernacular lookups.

    Returns:
        Dict keyed by species_key with common_name values. Empty when
        ``species_config`` is missing/invalid, or when neither the enriched
        nor the raw config yielded a matching ``common_name`` for any of
        the given ``species_keys``.
    """
    species_common_names: dict[str, str] = {}
    if not (session.species_config and isinstance(session.species_config, list)):
        return species_common_names

    from echoroo.api.v1.search.utils import _enrich_species_config_with_locale

    try:
        enriched_config = await _enrich_species_config_with_locale(
            list(session.species_config), locale, db
        )
    except Exception:
        logger.warning(
            "Failed to enrich species_config for export-recordings (locale=%r); "
            "falling back to raw species_config",
            locale,
            exc_info=True,
        )
        enriched_config = list(session.species_config)

    # Build sci_name -> common_name from enriched (or raw-fallback) config
    sci_to_common: dict[str, str] = {}
    for sp_cfg in enriched_config:
        if not isinstance(sp_cfg, dict):
            continue
        sp_sci = str(sp_cfg.get("scientific_name") or "")
        sp_common = str(sp_cfg.get("common_name") or "")
        if sp_sci and sp_common:
            sci_to_common[sp_sci] = sp_common

    # Map species_key -> common_name using species_labels (key -> sci_name)
    for key in species_keys:
        sci_name = species_labels.get(key, "")
        if sci_name in sci_to_common:
            species_common_names[key] = sci_to_common[sci_name]

    return species_common_names


async def _compute_similarity_aggregates(
    session: Any,
    species_keys: list[str],
    all_recordings: list[tuple[str, str, str | None]],
    db: Any,
) -> dict[str, dict[str, dict[str, float]]]:
    """Compute per-(species, recording) similarity aggregates.

    For each species key in the session's results, runs the stored query
    vectors against every project embedding via ``<=>`` cosine distance and
    rolls the similarities up to one MAX/MIN/AVG row per recording_id.
    Species with no stored query vectors (e.g. results were truncated or
    the originating embeddings have been deleted) are silently skipped —
    the CSV writer will fall back to empty similarity cells for them.

    The ``all_recordings`` argument is accepted to satisfy the original
    "aggregate only over recordings we're going to emit" contract, even
    though the current SQL still computes over all project embeddings.
    Passing the list keeps the route-level data flow explicit and lets a
    future optimisation restrict the set of recordings without changing
    the helper's signature.

    Args:
        session: SearchSession ORM instance (``model_name``, ``parameters``
            attrs read; the dataset filter is derived here).
        species_keys: Ordered list of species keys to aggregate over.
        all_recordings: The recordings list returned by
            ``_fetch_session_recordings``. Not directly used by the SQL
            today but kept in the signature per plan (Codex M-2).
        db: AsyncSession.

    Returns:
        Nested dict ``{species_key: {recording_id: {max_sim, min_sim, avg_sim}}}``.
        Missing species and missing recordings default to an empty inner
        dict so callers can use ``.get(...)`` chaining.
    """
    del all_recordings  # accepted for plan-prescribed signature parity; SQL spans all project embeddings

    # Determine optional dataset filter from session parameters.
    dataset_id_str: str | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        dataset_id_str = str(session.parameters["dataset_id"])

    model_name = session.model_name or "perch"
    dataset_filter = "AND d.id = :dataset_id" if dataset_id_str else ""
    project_id_str = str(session.project_id)

    agg: dict[str, dict[str, dict[str, float]]] = {}

    for sp_key in species_keys:
        query_vectors = await _get_query_vectors_from_session(session, db, species_key=sp_key)
        if not query_vectors:
            continue

        # Build UNION ALL for multi-vector MAX similarity per embedding
        union_parts: list[str] = []
        sim_params: dict[str, object] = {
            "project_id": project_id_str,
            "model_name": model_name,
        }
        if dataset_id_str:
            sim_params["dataset_id"] = dataset_id_str

        for idx, qv in enumerate(query_vectors):
            vec_literal = "[" + ",".join(str(v) for v in qv) + "]"
            param_key = f"qv_{idx}"
            sim_params[param_key] = vec_literal
            union_parts.append(
                f"""
                SELECT
                    e.id AS embedding_id,
                    e.recording_id,
                    1 - (e.vector <=> CAST(:{param_key} AS vector)) AS similarity
                FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d   ON r.dataset_id   = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name  = :model_name
                  {dataset_filter}
                """
            )

        union_sql = " UNION ALL ".join(union_parts)
        agg_sql = text(
            f"""
            WITH all_sims AS (
                {union_sql}
            ),
            best_per_embedding AS (
                SELECT recording_id, MAX(similarity) AS similarity
                FROM all_sims
                GROUP BY recording_id, embedding_id
            )
            SELECT
                recording_id::text,
                MAX(similarity) AS max_sim,
                MIN(similarity) AS min_sim,
                AVG(similarity) AS avg_sim
            FROM best_per_embedding
            GROUP BY recording_id
            """
        )
        rows = (await db.execute(agg_sql, sim_params)).fetchall()
        species_agg = agg.setdefault(sp_key, {})
        for row in rows:
            species_agg[str(row[0])] = {
                "max_sim": float(row[1]),
                "min_sim": float(row[2]),
                "avg_sim": float(row[3]),
            }

    return agg


_EXPORT_CSV_HEADER: list[str] = [
    "recording_filename",
    "recording_datetime",
    "scientific_name",
    "common_name",
    "max_similarity",
    "min_similarity",
    "avg_similarity",
]


def _write_recordings_csv(
    session: Any,
    all_recordings: list[tuple[str, str, str | None]],
    species_labels: dict[str, str],
    species_common_names: dict[str, str],
    species_keys: list[str],
    agg: dict[str, dict[str, dict[str, float]]],
) -> tuple[str, str]:
    """Serialise the export-recordings CSV body and compute its filename.

    Unifies the empty-state path (no recordings → header-only CSV) and
    the populated path (one row per ``(recording, species)`` with
    aggregated similarities). Both paths share the same writer, header
    row, and ``search_summary_{safe_name}_{YYYYMMDD}.csv`` filename
    template — a user whose project happens to be empty must still see a
    correctly-named download.

    The returned body is a ``str``, not ``bytes``: the route streams it
    via ``StreamingResponse(iter([csv_content]))`` exactly as the original
    inline code did.  The ``safe_name`` sanitisation used for the filename
    is byte-for-byte identical to the original (same six replacements in
    the same order).

    Args:
        session: SearchSession ORM instance. ``session.name`` and
            ``session.id`` are used for the filename.
        all_recordings: Output of ``_fetch_session_recordings`` — iteration
            order is preserved as the row order in the CSV.
        species_labels: species_key → scientific_name.
        species_common_names: species_key → common_name (possibly empty).
        species_keys: Ordered list of species keys to emit per recording.
        agg: Output of ``_compute_similarity_aggregates``; ``{}`` when no
            recordings were found.

    Returns:
        Tuple of (csv_content, filename).
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_EXPORT_CSV_HEADER)

    for rec_id, rec_filename, rec_datetime in all_recordings:
        for sp_key in species_keys:
            sci_name = species_labels.get(sp_key, sp_key)
            common_name = species_common_names.get(sp_key, "")
            rec_agg = agg.get(sp_key, {}).get(rec_id)
            if rec_agg is not None:
                writer.writerow([
                    rec_filename,
                    rec_datetime or "",
                    sci_name,
                    common_name,
                    f"{rec_agg['max_sim']:.4f}",
                    f"{rec_agg['min_sim']:.4f}",
                    f"{rec_agg['avg_sim']:.4f}",
                ])
            else:
                writer.writerow([
                    rec_filename,
                    rec_datetime or "",
                    sci_name,
                    common_name,
                    "",
                    "",
                    "",
                ])

    csv_content = output.getvalue()
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    safe_name = (
        (session.name or str(session.id))
        .replace('"', '_')
        .replace('\n', '_')
        .replace('\r', '_')
        .replace(' ', '_')
        .replace('/', '-')
    )
    filename = f"search_summary_{safe_name}_{date_str}.csv"
    return csv_content, filename


@router.get(
    "/sessions/{session_id}/export-recordings",
    summary="Export search summary: all recordings × all species as CSV",
    description=(
        "Export a search summary CSV with one row per (recording × species). "
        "All recordings in the project's datasets are included (even those with no "
        "matching embeddings). Similarity is computed against each species' stored "
        "query vectors. Rows are sorted by recording_datetime ASC."
    ),
)
async def export_search_session_recordings_csv(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    locale: str = Query(default="en", description="Locale for common names (en, ja)"),
) -> StreamingResponse:
    """Export per-(recording × species) aggregated similarity results as CSV.

    For each species in the session, computes similarity for all project
    recordings using the stored query vectors. All recordings are included
    (those without embeddings get NULL similarities). Produces one row per
    (recording, species) combination sorted by recording_datetime ASC.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service

    Returns:
        CSV file as streaming response with columns:
        recording_filename, recording_datetime, species,
        max_similarity, min_similarity, avg_similarity

    Raises:
        403: Access denied to project
        404: Session not found or has no results
    """
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    if not session.results:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to export",
        )

    # Snapshot every ORM attribute we will need into a plain-old-data proxy
    # BEFORE any helper that may flush/commit/rollback the DB session.  The
    # locale-enrichment chain (``_resolve_locale_common_names`` ->
    # ``_enrich_species_config_with_locale`` -> ``_resolve_vernacular_via_gbif``)
    # transparently caches new GBIF Taxon / TaxonVernacularName rows and runs
    # ``await db.rollback()`` inside its duplicate-race guard.  SQLAlchemy's
    # ``rollback()`` EXPIRES every ORM-tracked attribute on every instance in
    # the session, regardless of ``expire_on_commit``.  Any subsequent access
    # to ``session.parameters`` / ``session.name`` / ``session.results`` would
    # then trigger an implicit lazy-load outside the async context and raise
    # ``MissingGreenlet``.  The POD proxy is immune because its values are
    # concrete dict/str/UUID copies held in memory.
    from types import SimpleNamespace

    session_snapshot = SimpleNamespace(
        id=session.id,
        name=session.name,
        project_id=session.project_id,
        model_name=session.model_name,
        parameters=dict(session.parameters) if session.parameters else None,
        results=dict(session.results) if session.results else None,
        species_config=list(session.species_config) if session.species_config else None,
    )

    # Extract species_labels + species_keys (tag_id lookup + sci_name fallback).
    # The helper owns the two 404 paths for malformed / empty results.
    species_labels, species_keys = await _build_species_labels(session_snapshot, db)

    # Build common name mapping using the same enrichment as session detail API.
    # Locale enrichment is best-effort: a transient GBIF outage or an internal
    # SQLAlchemy error must NOT cause the export to fail. Mirror the guard used
    # by the list/detail routes — degrade to scientific names when enrichment
    # raises.
    species_common_names = await _resolve_locale_common_names(
        session_snapshot, species_keys, species_labels, locale, db
    )

    # Fetch all recordings for this project (with the optional dataset filter
    # from session.parameters applied inside the helper).
    all_recordings = await _fetch_session_recordings(session_snapshot, project_id, db)

    # For each species, compute similarity against ALL embeddings via SQL
    # (same pattern as distribution/time-distribution APIs).
    # Aggregate per recording: MAX, MIN, AVG similarity.
    agg = (
        await _compute_similarity_aggregates(
            session_snapshot, species_keys, all_recordings, db
        )
        if all_recordings
        else {}
    )

    csv_content, filename = _write_recordings_csv(
        session_snapshot,
        all_recordings,
        species_labels,
        species_common_names,
        species_keys,
        agg,
    )
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/sessions/{session_id}/export/csv",
    summary="Export session annotations as CSV",
    description="Export all annotations linked to a search session as a CSV file.",
)
async def export_search_session_csv(
    project_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
) -> StreamingResponse:
    """Export search session annotations as CSV.

    Phase 17 backlog A-5 (Hybrid Contract): the underlying export
    pipeline now streams row-by-row and re-checks the EXPORT permission
    every ``CSV_RECHECK_INTERVAL`` rows. Pre-start gating is performed
    via :func:`gate_action` (was implicitly via
    ``AuthorizedSearchSessionServiceDep`` → ``check_project_access``;
    we keep that for the session lookup and add the explicit Action
    gate so the mid-stream guard has a canonical Action to re-evaluate).

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        request: FastAPI request (used by the streaming guard).
        current_user: Authenticated caller (used by the streaming guard).
        db: Database session
        session_service: Authorized search session service

    Returns:
        CSV file as streaming response

    Raises:
        403: Access denied to project
        404: Session not found
    """
    # Local import — DETECTION_EXPORT_CSV_ACTION lives in echoroo.core.actions
    # which depends on routers; lazy to avoid a top-level cycle.
    from echoroo.core.actions import DETECTION_EXPORT_CSV_ACTION
    from echoroo.core.permissions import gate_action
    from echoroo.services.detection_export import DetectionExportService

    await gate_action(
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    export_service = DetectionExportService(db)
    body_iterator = export_service.export_csv_stream(
        project_id=project_id,
        action=DETECTION_EXPORT_CSV_ACTION,
        current_user=current_user,
        request=request,
        stream_type="csv_export_search_session",
        search_session_id=session_id,
    )

    date_str = datetime.now(UTC).strftime("%Y%m%d")
    safe_name = (
        (session.name or str(session_id))
        .replace('"', "_")
        .replace("\n", "_")
        .replace("\r", "_")
        .replace(" ", "_")
        .replace("/", "-")
    )
    filename = f"search_session_{safe_name}_{date_str}.csv"
    return StreamingResponse(
        body_iterator,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Similarity distribution and random sampling endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/sessions/{session_id}/distribution",
    response_model=SessionDistributionResponse,
    summary="Get similarity distribution for a search session",
    description=(
        "Compute a histogram of cosine similarities for all project embeddings "
        "against the session's reference vectors. Uses SQL aggregation for efficiency "
        "— individual vectors are never loaded into Python. "
        "Query vectors are derived from the top stored matches for each species."
    ),
)
async def get_session_similarity_distribution(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    bin_width: float = Query(default=0.05, ge=0.01, le=0.5, description="Histogram bin width"),
    species_key: str | None = Query(default=None, description="Filter to a single species by its result key"),
) -> SessionDistributionResponse:
    """Get a similarity histogram for all project embeddings vs. the session's reference vectors.

    Retrieves the stored top-match embedding vectors from the session results and
    uses them as query vectors to compute a full-space similarity distribution.
    This approach avoids re-running model inference.

    When ``species_key`` is provided, only the query vector for that species is
    used, so the distribution reflects similarity to that single species only.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service
        bin_width: Histogram bin width (default 0.05 = 20 bins from 0.0 to 1.0)
        species_key: Optional species key to filter distribution to a single species

    Returns:
        SessionDistributionResponse with histogram bins, total count, and session_id

    Raises:
        403: Access denied to project
        404: Session not found or has no results
    """
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    query_vectors = await _get_query_vectors_from_session(session, db, species_key=species_key)
    if not query_vectors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to compute distribution from",
        )

    dataset_id: UUID | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        with contextlib.suppress(ValueError):
            dataset_id = UUID(str(session.parameters["dataset_id"]))

    from echoroo.services.search import SimilaritySearchService

    search_service = SimilaritySearchService(db)
    dist = await search_service.get_similarity_distribution(
        project_id=project_id,
        query_vectors=query_vectors,
        model_name=session.model_name,
        bin_width=bin_width,
        dataset_id=dataset_id,
    )

    return SessionDistributionResponse(
        session_id=session_id,
        bins=dist.bins,
        total_count=dist.total,
    )


@router.get(
    "/sessions/{session_id}/time-distribution",
    response_model=SessionTimeDistributionResponse,
    summary="Get time-of-day similarity distribution for a search session",
    description=(
        "Compute average cosine similarity grouped by (date, hour) for all "
        "project embeddings against the session's reference vectors. "
        "Returns one cell per (date, hour) combination with average similarity "
        "and embedding count. Useful for rendering time-of-day heatmaps."
    ),
)
async def get_session_time_distribution(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    species_key: str | None = Query(default=None, description="Filter to a single species by its result key"),
) -> SessionTimeDistributionResponse:
    """Get average similarity per (date, hour) for all project embeddings.

    When ``species_key`` is provided, only the query vector for that species is
    used, so the distribution reflects similarity to that single species only.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service
        species_key: Optional species key to filter distribution to a single species

    Returns:
        SessionTimeDistributionResponse with cells for each (date, hour) combination

    Raises:
        403: Access denied to project
        404: Session not found or has no results
    """
    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    query_vectors = await _get_query_vectors_from_session(session, db, species_key=species_key)
    if not query_vectors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to compute time distribution from",
        )

    dataset_id: UUID | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        with contextlib.suppress(ValueError):
            dataset_id = UUID(str(session.parameters["dataset_id"]))

    from echoroo.services.search import SimilaritySearchService

    search_service = SimilaritySearchService(db)
    result = await search_service.get_time_distribution(
        project_id=project_id,
        query_vectors=query_vectors,
        model_name=session.model_name,
        dataset_id=dataset_id,
    )

    raw_cells = result["cells"]
    timezone = str(result["timezone"])

    cells = [
        TimeDistributionCell(
            date=str(c["date"]),
            hour=int(c["hour"]),
            avg_similarity=float(c["avg_similarity"]),
            count=int(c["count"]),
        )
        for c in raw_cells  # type: ignore[attr-defined]
    ]

    return SessionTimeDistributionResponse(
        session_id=session_id,
        cells=cells,
        timezone=timezone,
    )


@router.get(
    "/sessions/{session_id}/sample",
    response_model=SessionSampleResponse,
    summary="Randomly sample embeddings within a similarity range",
    description=(
        "Return a random sample of embeddings whose cosine similarity to the "
        "session's reference vectors falls within [min_similarity, max_similarity]. "
        "Useful for exploring which sounds exist in a specific similarity band."
    ),
)
async def sample_session_similarity_range(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    min_similarity: float = Query(default=0.0, ge=0.0, le=1.0, description="Lower bound (inclusive)"),
    max_similarity: float = Query(default=1.0, ge=0.0, le=1.0, description="Upper bound (inclusive)"),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum number of results to return"),
    species_key: str | None = Query(default=None, description="Filter to a single species by its result key"),
) -> SessionSampleResponse:
    """Return a random sample of embeddings within a given similarity range.

    When ``species_key`` is provided, only the query vector for that species is
    used, so the sampled results reflect similarity to that single species only.

    Args:
        project_id: Project UUID (path parameter)
        session_id: Session UUID (path parameter)
        db: Database session
        session_service: Authorized search session service
        min_similarity: Lower bound of similarity range
        max_similarity: Upper bound of similarity range
        limit: Maximum number of randomly sampled results
        species_key: Optional species key to filter sample to a single species

    Returns:
        SessionSampleResponse with randomly sampled SimilarityResult items and total_in_range

    Raises:
        400: min_similarity > max_similarity
        403: Access denied to project
        404: Session not found or has no results
    """
    if min_similarity > max_similarity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"min_similarity ({min_similarity}) must be <= max_similarity ({max_similarity})",
        )

    session = await session_service.get_session(session_id, project_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found")

    query_vectors = await _get_query_vectors_from_session(session, db, species_key=species_key)
    if not query_vectors:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session has no results to sample from",
        )

    dataset_id: UUID | None = None
    if session.parameters and session.parameters.get("dataset_id"):
        with contextlib.suppress(ValueError):
            dataset_id = UUID(str(session.parameters["dataset_id"]))

    from echoroo.services.search import SimilaritySearchService

    search_service = SimilaritySearchService(db)
    results, total_in_range = await search_service.sample_by_similarity_range(
        project_id=project_id,
        query_vectors=query_vectors,
        model_name=session.model_name,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        limit=limit,
        dataset_id=dataset_id,
    )

    return SessionSampleResponse(
        session_id=session_id,
        results=results,
        total_in_range=total_in_range,
    )


async def _get_query_vectors_from_session(
    session: Any,
    db: Any,
    species_key: str | None = None,
) -> list[list[float]]:
    """Extract query vectors from a completed session's stored match embeddings.

    Retrieves the embedding_id of the best (highest similarity) match per species
    from the stored session results, then fetches the corresponding stored vectors
    from the embeddings table. This avoids re-running model inference.

    For multi-species sessions, one representative vector per species is returned
    so the distribution reflects similarity to any of the searched species.

    When ``species_key`` is provided, only the query vector for that specific
    species is returned, allowing callers to compute per-species distributions.

    Args:
        session: SearchSession ORM instance with populated results field
        db: SQLAlchemy async session
        species_key: Optional species key to filter results to a single species

    Returns:
        List of float vectors (each of length _STORAGE_EMBEDDING_DIM), one per species.
        Empty list if session has no results or no valid embedding IDs can be resolved.
    """
    from sqlalchemy import text as _text

    if not session.results:
        return []

    raw_results = session.results.get("results")
    if not isinstance(raw_results, dict):
        return []

    # Collect the best embedding_id per species (highest similarity match)
    best_embedding_ids: list[str] = []
    for _species_key, species_data in raw_results.items():
        # If a species_key filter is provided, skip non-matching species
        if species_key is not None and _species_key != species_key:
            continue
        if not isinstance(species_data, dict):
            continue
        matches = species_data.get("matches", [])
        if not isinstance(matches, list) or not matches:
            continue
        # Matches are stored in descending similarity order; take the first one
        best_match = matches[0]
        if isinstance(best_match, dict) and best_match.get("embedding_id"):
            best_embedding_ids.append(str(best_match["embedding_id"]))

    if not best_embedding_ids:
        return []

    # Fetch vectors from the embeddings table for all collected IDs.
    # Use != ALL with an inverted query is not needed here — instead use a
    # parameterised IN list to avoid the asyncpg ::uuid[] cast syntax issue.
    # Build a parameterised set of bind variables for the IN clause.
    in_params: dict[str, str] = {f"eid_{i}": eid for i, eid in enumerate(best_embedding_ids)}
    in_clause = ", ".join(f":eid_{i}" for i in range(len(best_embedding_ids)))
    fetch_sql = _text(
        f"""
        SELECT e.vector::text AS vector_text
        FROM embeddings e
        WHERE e.id IN ({in_clause})
        """
    )
    rows = (
        await db.execute(fetch_sql, in_params)
    ).fetchall()

    from echoroo.services.search import _parse_vector_text

    query_vectors: list[list[float]] = []
    for row in rows:
        try:
            query_vectors.append(_parse_vector_text(row.vector_text))
        except ValueError:
            logger.warning("Failed to parse vector text for session query vector, skipping")

    return query_vectors
