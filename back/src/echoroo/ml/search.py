"""Advanced vector similarity search module.

This module provides optimized vector similarity search using pgvector.
It supports filtering by datasets, recordings, tags, model runs, and
date ranges. The search is optimized for performance using CTEs and
index hints.

Example usage:
    search = VectorSearch()
    results = await search.search_clips(
        session,
        embedding=[0.1, 0.2, ...],
        limit=20,
        min_similarity=0.7,
        filters=SearchFilter(
            dataset_uuids=[uuid1, uuid2],
            min_date=datetime(2023, 1, 1),
        ),
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SearchFilter",
    "SimilarityResult",
    "VectorSearch",
    "vector_search",
]


@dataclass
class SearchFilter:
    """Filters for vector search.

    Attributes
    ----------
    dataset_uuids
        Filter by dataset UUIDs. Only clips from recordings in these
        datasets will be returned.
    recording_uuids
        Filter by recording UUIDs. Only clips from these recordings
        will be returned.
    tag_ids
        Filter by tag IDs. Only clips from recordings with any of
        these tags will be returned.
    model_name
        Filter by model name. Only embeddings from model runs with
        this name will be returned.
    model_run_uuid
        Filter by specific model run UUID.
    min_date
        Filter by minimum recording date (inclusive).
    max_date
        Filter by maximum recording date (inclusive).
    exclude_clip_uuids
        Exclude specific clip UUIDs from results.
    """

    dataset_uuids: list[UUID] | None = None
    recording_uuids: list[UUID] | None = None
    tag_ids: list[int] | None = None
    model_name: str | None = None
    model_run_uuid: UUID | None = None
    min_date: datetime | None = None
    max_date: datetime | None = None
    exclude_clip_uuids: list[UUID] | None = None


@dataclass
class SimilarityResult:
    """Single search result.

    Attributes
    ----------
    clip_id
        Database ID of the clip.
    clip_uuid
        UUID of the clip.
    recording_uuid
        UUID of the recording containing the clip.
    start_time
        Start time of the clip in seconds.
    end_time
        End time of the clip in seconds.
    similarity
        Cosine similarity score (0.0 to 1.0).
    model_run_uuid
        UUID of the model run that generated the embedding.
    model_name
        Name of the model that generated the embedding.
    model_version
        Version of the model that generated the embedding.
    """

    clip_id: int
    clip_uuid: UUID
    recording_uuid: UUID
    start_time: float
    end_time: float
    similarity: float
    model_run_uuid: UUID
    model_name: str = ""
    model_version: str = ""


@dataclass
class _FilterComponents:
    """Components for building filtered queries.

    This class holds the CTEs, JOINs, WHERE clauses, and parameters
    needed to apply SearchFilter to a query.
    """

    ctes: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)
    where_clauses: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def build_cte_sql(self) -> str:
        """Build the WITH clause for CTEs."""
        if not self.ctes:
            return ""
        return "WITH " + ",\n".join(self.ctes)

    def build_join_sql(self) -> str:
        """Build the JOIN clauses."""
        return "\n".join(self.joins)

    def build_where_sql(self) -> str:
        """Build the WHERE clause."""
        if not self.where_clauses:
            return "1=1"
        return " AND ".join(self.where_clauses)


def _build_filter_components(
    filters: SearchFilter | None,
    param_prefix: str = "",
) -> _FilterComponents:
    """Build filter components from SearchFilter.

    This function extracts the common filter building logic used by
    both search queries and count queries.

    Parameters
    ----------
    filters
        Optional search filters.
    param_prefix
        Prefix for parameter names to avoid conflicts.

    Returns
    -------
    _FilterComponents
        Components needed to apply the filters.

    Notes
    -----
    All UUID and other user-provided values are passed as parameters
    to prevent SQL injection. Array parameters use PostgreSQL's ANY()
    syntax for efficient matching.
    """
    components = _FilterComponents()

    if filters is None:
        return components

    # Dataset filter - requires CTE for efficient filtering
    if filters.dataset_uuids:
        param_name = f"{param_prefix}dataset_uuids"
        # Convert UUIDs to strings for the parameter
        components.params[param_name] = [str(u) for u in filters.dataset_uuids]
        components.ctes.append(f"""
            dataset_recordings AS (
                SELECT DISTINCT dr.recording_id
                FROM dataset_recording dr
                JOIN dataset d ON dr.dataset_id = d.id
                WHERE d.uuid = ANY(:{param_name}::uuid[])
            )
        """)
        components.joins.append(
            "JOIN dataset_recordings drf ON r.id = drf.recording_id"
        )

    # Recording filter - use parameterized array
    if filters.recording_uuids:
        param_name = f"{param_prefix}recording_uuids"
        components.params[param_name] = [str(u) for u in filters.recording_uuids]
        components.where_clauses.append(f"r.uuid = ANY(:{param_name}::uuid[])")

    # Tag filter - requires CTE
    if filters.tag_ids:
        param_name = f"{param_prefix}tag_ids"
        components.params[param_name] = filters.tag_ids
        components.ctes.append(f"""
            tagged_recordings AS (
                SELECT DISTINCT rt.recording_id
                FROM recording_tag rt
                WHERE rt.tag_id = ANY(:{param_name}::int[])
            )
        """)
        components.joins.append(
            "JOIN tagged_recordings tr ON r.id = tr.recording_id"
        )

    # Model name filter
    if filters.model_name:
        param_name = f"{param_prefix}model_name"
        components.params[param_name] = filters.model_name
        components.where_clauses.append(f"mr.name = :{param_name}")

    # Model run UUID filter
    if filters.model_run_uuid:
        param_name = f"{param_prefix}model_run_uuid"
        components.params[param_name] = str(filters.model_run_uuid)
        components.where_clauses.append(f"mr.uuid = :{param_name}::uuid")

    # Date filters
    if filters.min_date:
        param_name = f"{param_prefix}min_date"
        components.params[param_name] = filters.min_date.isoformat()
        components.where_clauses.append(f"r.datetime >= :{param_name}::timestamp")

    if filters.max_date:
        param_name = f"{param_prefix}max_date"
        components.params[param_name] = filters.max_date.isoformat()
        components.where_clauses.append(f"r.datetime <= :{param_name}::timestamp")

    # Exclude specific clips - use parameterized array
    if filters.exclude_clip_uuids:
        param_name = f"{param_prefix}exclude_clip_uuids"
        components.params[param_name] = [
            str(u) for u in filters.exclude_clip_uuids
        ]
        components.where_clauses.append(
            f"c.uuid != ALL(:{param_name}::uuid[])"
        )

    return components


@dataclass
class _QueryBuilder:
    """Internal helper for building dynamic SQL queries."""

    params: dict = field(default_factory=dict)
    where_clauses: list[str] = field(default_factory=list)

    def add_embedding_param(self, embedding: list[float]) -> str:
        """Add embedding parameter and return the SQL placeholder."""
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        self.params["query_embedding"] = embedding_str
        return ":query_embedding::vector"

    def add_similarity_filter(self, min_similarity: float) -> None:
        """Add minimum similarity filter."""
        self.params["min_similarity"] = min_similarity
        self.where_clauses.append(
            "1 - (ce.embedding <=> :query_embedding::vector) >= :min_similarity"
        )

    def add_limit(self, limit: int) -> None:
        """Add limit parameter."""
        self.params["limit"] = limit


class VectorSearch:
    """Optimized vector similarity search using pgvector.

    This class provides methods for searching similar audio clips
    based on embedding vectors. It uses PostgreSQL's pgvector
    extension with HNSW indexes for efficient approximate nearest
    neighbor search.

    The search supports various filters including dataset, recording,
    tag, model, and date filters. Complex queries use CTEs for
    better performance and readability.
    """

    async def search_clips(
        self,
        session: AsyncSession,
        embedding: list[float],
        limit: int = 20,
        min_similarity: float = 0.7,
        filters: SearchFilter | None = None,
    ) -> list[SimilarityResult]:
        """Search for similar clips with optional filters.

        Uses pgvector's cosine distance operator (<=>).
        similarity = 1 - cosine_distance

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        embedding
            Query embedding vector. Should match the dimension of
            stored embeddings (1536 for Perch 2.0 compatibility).
        limit
            Maximum number of results to return.
        min_similarity
            Minimum cosine similarity threshold (0.0 to 1.0).
            Results with lower similarity are excluded.
        filters
            Optional SearchFilter for restricting results.

        Returns
        -------
        list[SimilarityResult]
            List of search results sorted by similarity (descending).

        Notes
        -----
        The query uses the HNSW index on clip_embedding for fast
        approximate nearest neighbor search. For very restrictive
        filters, the query may fall back to exact search.
        """
        query, params = self._build_search_query(
            embedding=embedding,
            limit=limit,
            min_similarity=min_similarity,
            filters=filters,
        )

        result = await session.execute(text(query), params)
        rows = result.fetchall()

        return [
            SimilarityResult(
                clip_id=row.clip_id,
                clip_uuid=row.clip_uuid,
                recording_uuid=row.recording_uuid,
                start_time=row.start_time,
                end_time=row.end_time,
                similarity=row.similarity,
                model_run_uuid=row.model_run_uuid,
                model_name=row.model_name,
                model_version=row.model_version,
            )
            for row in rows
        ]

    async def search_by_clip(
        self,
        session: AsyncSession,
        clip_uuid: UUID,
        limit: int = 20,
        min_similarity: float = 0.7,
        filters: SearchFilter | None = None,
        model_run_uuid: UUID | None = None,
    ) -> list[SimilarityResult]:
        """Find clips similar to a given clip.

        First retrieves the embedding for the specified clip, then
        searches for similar clips using that embedding.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        clip_uuid
            UUID of the reference clip to find similar clips for.
        limit
            Maximum number of results to return.
        min_similarity
            Minimum cosine similarity threshold (0.0 to 1.0).
        filters
            Optional SearchFilter for restricting results.
        model_run_uuid
            Optional model run UUID to use for the reference embedding.
            If not provided, uses the most recent embedding.

        Returns
        -------
        list[SimilarityResult]
            List of search results sorted by similarity (descending).
            The reference clip is excluded from results.

        Raises
        ------
        ValueError
            If no embedding exists for the specified clip.
        """
        # First, get the embedding for the reference clip
        embedding_query = """
            SELECT ce.embedding, ce.model_run_id, mr.uuid as model_run_uuid
            FROM clip_embedding ce
            JOIN clip c ON ce.clip_id = c.id
            JOIN model_run mr ON ce.model_run_id = mr.id
            WHERE c.uuid = :clip_uuid
        """

        if model_run_uuid is not None:
            embedding_query += " AND mr.uuid = :model_run_uuid"

        embedding_query += " ORDER BY ce.id DESC LIMIT 1"

        params: dict = {"clip_uuid": str(clip_uuid)}
        if model_run_uuid is not None:
            params["model_run_uuid"] = str(model_run_uuid)

        result = await session.execute(text(embedding_query), params)
        row = result.fetchone()

        if row is None:
            raise ValueError(
                f"No embedding found for clip {clip_uuid}"
                + (
                    f" with model run {model_run_uuid}"
                    if model_run_uuid
                    else ""
                )
            )

        # Ensure we exclude the reference clip
        if filters is None:
            filters = SearchFilter()

        if filters.exclude_clip_uuids is None:
            filters.exclude_clip_uuids = []
        if clip_uuid not in filters.exclude_clip_uuids:
            filters.exclude_clip_uuids.append(clip_uuid)

        # Search using the retrieved embedding
        # Note: pgvector stores vectors as numpy arrays, convert to list
        embedding = list(row.embedding)

        return await self.search_clips(
            session=session,
            embedding=embedding,
            limit=limit,
            min_similarity=min_similarity,
            filters=filters,
        )

    async def batch_search(
        self,
        session: AsyncSession,
        embeddings: list[list[float]],
        limit_per_query: int = 10,
        min_similarity: float = 0.7,
        filters: SearchFilter | None = None,
    ) -> list[list[SimilarityResult]]:
        """Batch search for multiple embeddings.

        Executes multiple similarity searches efficiently. Each
        embedding is searched independently, but queries are
        executed within the same session.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        embeddings
            List of query embedding vectors.
        limit_per_query
            Maximum number of results per query.
        min_similarity
            Minimum cosine similarity threshold (0.0 to 1.0).
        filters
            Optional SearchFilter applied to all queries.

        Returns
        -------
        list[list[SimilarityResult]]
            List of result lists, one per input embedding.
            Results are sorted by similarity within each list.

        Notes
        -----
        For large batches, consider using asyncio.gather for
        parallel execution if your database connection pool
        supports it.
        """
        results = []
        for embedding in embeddings:
            query_results = await self.search_clips(
                session=session,
                embedding=embedding,
                limit=limit_per_query,
                min_similarity=min_similarity,
                filters=filters,
            )
            results.append(query_results)
        return results

    async def search_diverse(
        self,
        session: AsyncSession,
        embedding: list[float],
        limit: int = 20,
        min_similarity: float = 0.7,
        diversity_threshold: float = 0.3,
        filters: SearchFilter | None = None,
    ) -> list[SimilarityResult]:
        """Search for diverse similar clips using maximal marginal relevance.

        Returns clips that are similar to the query but diverse among
        themselves. This helps avoid returning many nearly identical clips.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        embedding
            Query embedding vector.
        limit
            Maximum number of results to return.
        min_similarity
            Minimum cosine similarity threshold (0.0 to 1.0).
        diversity_threshold
            Threshold for diversity. Higher values prioritize diversity
            over similarity. Range: 0.0 to 1.0.
        filters
            Optional SearchFilter for restricting results.

        Returns
        -------
        list[SimilarityResult]
            List of diverse search results.

        Notes
        -----
        This method fetches more candidates than requested and then
        applies a greedy selection algorithm to maximize diversity.
        The trade-off between similarity and diversity is controlled
        by diversity_threshold.
        """
        # Fetch more candidates for diversity selection
        candidates = await self.search_clips(
            session=session,
            embedding=embedding,
            limit=limit * 5,  # Oversample for diversity
            min_similarity=min_similarity,
            filters=filters,
        )

        if len(candidates) <= limit:
            return candidates

        # Greedy selection for diversity using maximal marginal relevance
        selected: list[SimilarityResult] = []
        remaining = list(candidates)

        # First, select the most similar result
        if remaining:
            selected.append(remaining.pop(0))

        while len(selected) < limit and remaining:
            best_score = -float("inf")
            best_idx = 0

            for idx, candidate in enumerate(remaining):
                # Similarity component (relevance to query)
                sim_score = candidate.similarity

                # Diversity component (dissimilarity to selected)
                # Using heuristic based on clip temporal distance
                max_overlap = 0.0
                for sel in selected:
                    if candidate.recording_uuid == sel.recording_uuid:
                        # Same recording - compute temporal overlap
                        overlap_start = max(
                            candidate.start_time, sel.start_time
                        )
                        overlap_end = min(candidate.end_time, sel.end_time)
                        if overlap_end > overlap_start:
                            duration = candidate.end_time - candidate.start_time
                            if duration > 0:
                                overlap = (
                                    overlap_end - overlap_start
                                ) / duration
                                max_overlap = max(max_overlap, overlap)

                diversity_score = 1.0 - max_overlap

                # Combined score using MMR formula
                mmr_score = (
                    1 - diversity_threshold
                ) * sim_score + diversity_threshold * diversity_score

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_idx = idx

            selected.append(remaining.pop(best_idx))

        return selected

    def _build_search_query(
        self,
        embedding: list[float],
        limit: int,
        min_similarity: float,
        filters: SearchFilter | None,
    ) -> tuple[str, dict]:
        """Build optimized SQL query for vector search.

        Constructs a query using CTEs for complex filters.
        The query is optimized to use pgvector's HNSW index.

        Parameters
        ----------
        embedding
            Query embedding vector.
        limit
            Maximum number of results.
        min_similarity
            Minimum similarity threshold.
        filters
            Optional search filters.

        Returns
        -------
        tuple[str, dict]
            SQL query string and parameters dictionary.
        """
        builder = _QueryBuilder()

        # Add embedding parameter
        embedding_param = builder.add_embedding_param(embedding)
        builder.add_similarity_filter(min_similarity)
        builder.add_limit(limit)

        # Build filter components using shared function
        filter_components = _build_filter_components(filters)

        # Merge filter params with builder params
        all_params = {**builder.params, **filter_components.params}

        # Combine where clauses
        all_where_clauses = builder.where_clauses + filter_components.where_clauses
        where_sql = " AND ".join(all_where_clauses) if all_where_clauses else "1=1"

        # Build the final query
        query = f"""
            {filter_components.build_cte_sql()}
            SELECT
                c.id as clip_id,
                c.uuid as clip_uuid,
                r.uuid as recording_uuid,
                c.start_time,
                c.end_time,
                1 - (ce.embedding <=> {embedding_param}) as similarity,
                mr.uuid as model_run_uuid,
                mr.name as model_name,
                mr.version as model_version
            FROM clip_embedding ce
            JOIN clip c ON ce.clip_id = c.id
            JOIN recording r ON c.recording_id = r.id
            JOIN model_run mr ON ce.model_run_id = mr.id
            {filter_components.build_join_sql()}
            WHERE {where_sql}
            ORDER BY ce.embedding <=> {embedding_param}
            LIMIT :limit
        """

        return query.strip(), all_params

    async def count_embeddings(
        self,
        session: AsyncSession,
        filters: SearchFilter | None = None,
    ) -> int:
        """Count total embeddings matching filters.

        Useful for pagination and progress tracking.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        filters
            Optional SearchFilter for restricting count.

        Returns
        -------
        int
            Total number of embeddings matching the filters.
        """
        # Build filter components using shared function
        filter_components = _build_filter_components(filters, param_prefix="count_")

        query = f"""
            {filter_components.build_cte_sql()}
            SELECT COUNT(*) as count
            FROM clip_embedding ce
            JOIN clip c ON ce.clip_id = c.id
            JOIN recording r ON c.recording_id = r.id
            JOIN model_run mr ON ce.model_run_id = mr.id
            {filter_components.build_join_sql()}
            WHERE {filter_components.build_where_sql()}
        """

        result = await session.execute(text(query.strip()), filter_components.params)
        row = result.fetchone()
        return int(row[0]) if row else 0

    async def get_embedding_stats(
        self,
        session: AsyncSession,
        filters: SearchFilter | None = None,
    ) -> dict:
        """Get statistics about embeddings.

        Returns count by model and other useful statistics.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession for database operations.
        filters
            Optional SearchFilter for restricting statistics.

        Returns
        -------
        dict
            Dictionary containing:
            - total_count: Total number of embeddings
            - by_model: Count per model name
            - by_dataset: Count per dataset (if dataset filter not applied)
        """
        total = await self.count_embeddings(session, filters)

        # Count by model
        model_query = """
            SELECT mr.name, mr.version, COUNT(*) as count
            FROM clip_embedding ce
            JOIN model_run mr ON ce.model_run_id = mr.id
            GROUP BY mr.name, mr.version
            ORDER BY count DESC
        """
        result = await session.execute(text(model_query))
        by_model = [
            {"name": row.name, "version": row.version, "count": row.count}
            for row in result.fetchall()
        ]

        return {
            "total_count": total,
            "by_model": by_model,
        }


# Module-level instance for convenience
vector_search = VectorSearch()
