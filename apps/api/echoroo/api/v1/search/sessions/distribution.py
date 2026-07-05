"""Similarity distribution and random sampling handlers for search sessions.

Three read handlers (similarity histogram, time distribution, similarity-range
sampling) that reuse the session's stored query vectors. These are unmounted
from ``/api/v1``; the ``/web-api/v1`` BFF delegates to them as helpers.
"""

from __future__ import annotations

import contextlib
from uuid import UUID

from fastapi import HTTPException, Query, status

from echoroo.api.v1.search.deps import AuthorizedSearchSessionServiceDep
from echoroo.api.v1.search.sessions._shared import _get_query_vectors_from_session
from echoroo.core.database import DbSession
from echoroo.schemas.search import (
    SessionDistributionResponse,
    SessionSampleResponse,
    SessionTimeDistributionResponse,
    TimeDistributionCell,
)

# ---------------------------------------------------------------------------
# Similarity distribution and random sampling endpoints
# ---------------------------------------------------------------------------


async def get_session_similarity_distribution(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    bin_width: float = Query(default=0.05, ge=0.01, le=0.5, description="Histogram bin width"),
    species_key: str | None = Query(
        default=None, description="Filter to a single species by its result key"
    ),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

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


async def get_session_time_distribution(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    species_key: str | None = Query(
        default=None, description="Filter to a single species by its result key"
    ),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

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


async def sample_session_similarity_range(
    project_id: UUID,
    session_id: UUID,
    db: DbSession,
    session_service: AuthorizedSearchSessionServiceDep,
    min_similarity: float = Query(
        default=0.0, ge=0.0, le=1.0, description="Lower bound (inclusive)"
    ),
    max_similarity: float = Query(
        default=1.0, ge=0.0, le=1.0, description="Upper bound (inclusive)"
    ),
    limit: int = Query(default=20, ge=1, le=200, description="Maximum number of results to return"),
    species_key: str | None = Query(
        default=None, description="Filter to a single species by its result key"
    ),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Search session not found"
        )

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
