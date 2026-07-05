"""Search session CRUD handlers.

Listing, getting, updating, deleting, and re-running search sessions.
These are unmounted from ``/api/v1``; the ``/web-api/v1`` BFF
(``echoroo.api.web_v1.projects._search``) delegates to them as helpers.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import (
    Body,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

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
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Search session endpoints
# ---------------------------------------------------------------------------


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

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
            logger.warning("Failed to delete reference audio %s after session delete: %s", key, exc)

    return Response(status_code=204)


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

    session.name = name
    await db.commit()
    await db.refresh(session)
    return SearchSessionResponse.model_validate(session)


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

    Clears this session's prior run state (stored results, counters, error
    state, review annotations, and stored query embeddings), resets status,
    then dispatches a new search task reusing the same session record. The
    query embeddings are regenerated by the dispatched task.

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
            logger.warning("Failed to delete stale reference audio %s after rerun: %s", key, exc)

    # Dispatch Celery task
    from echoroo.workers.search_tasks import run_batch_search

    run_batch_search.apply_async(
        args=[artifacts.job_id, str(project_id)],
        task_id=artifacts.job_id,
    )

    return SearchJobAcceptedResponse(
        job_id=artifacts.job_id, status="pending", session_id=session.id
    )
