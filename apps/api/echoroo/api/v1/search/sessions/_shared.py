"""Shared helper for search-session distribution and export handlers.

``_get_query_vectors_from_session`` is consumed by both ``exports.py``
(``_compute_similarity_aggregates``) and ``distribution.py`` (all three
distribution/sample handlers), so it lives here to avoid a cross-module
import cycle.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


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
    rows = (await db.execute(fetch_sql, in_params)).fetchall()

    from echoroo.services.search import _parse_vector_text

    query_vectors: list[list[float]] = []
    for row in rows:
        try:
            query_vectors.append(_parse_vector_text(row.vector_text))
        except ValueError:
            logger.warning("Failed to parse vector text for session query vector, skipping")

    return query_vectors
