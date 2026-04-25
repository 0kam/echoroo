"""Similarity search service using pgvector cosine distance.

Provides vector similarity search over stored embeddings, supporting both
embedding-ID-based queries (reuse a stored vector) and raw vector queries
(e.g., generated from an uploaded audio file).

All queries are scoped to a project_id to enforce data isolation.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.schemas.search import (
    BatchSearchRequest,
    BatchSearchResponse,
    EmbeddingStatsResponse,
    SimilarityBin,
    SimilarityDistributionResponse,
    SimilarityResult,
    SimilaritySearchResponse,
    SpeciesMatchResult,
)

if TYPE_CHECKING:
    from echoroo.ml.base import InferenceEngine, ModelLoader

logger = logging.getLogger(__name__)

# All stored embeddings use this fixed dimension.
# Models with smaller output vectors (e.g. BirdNET at 1024-dim) are zero-padded
# at write time.  Query vectors must be padded to the same dimension before
# performing a cosine distance search, otherwise pgvector raises a dimension
# mismatch error.
_STORAGE_EMBEDDING_DIM = 1536


class SimilaritySearchService:
    """Service for vector similarity search over stored embeddings.

    Uses pgvector's cosine distance operator (<=>). All queries are
    scoped to a project_id to ensure data isolation across tenants.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def search_by_embedding_id(
        self,
        project_id: UUID,
        embedding_id: UUID,
        model_name: str,
        limit: int = 20,
        min_similarity: float = 0.5,
        dataset_id: UUID | None = None,
    ) -> SimilaritySearchResponse:
        """Find similar embeddings using an existing stored embedding as query.

        Fetches the embedding vector for embedding_id, then delegates to
        search_by_vector. The query embedding itself is excluded from results.

        Args:
            project_id: Project UUID for access scoping
            embedding_id: UUID of the stored embedding to use as query
            model_name: Model name filter (e.g. "perch", "birdnet")
            limit: Maximum results to return
            min_similarity: Minimum cosine similarity threshold (0.0-1.0)
            dataset_id: Optional dataset filter

        Returns:
            SimilaritySearchResponse with ordered results

        Raises:
            ValueError: If no embedding found for embedding_id
        """
        # Retrieve the query embedding vector
        fetch_sql = text(
            """
            SELECT e.vector::text AS vector_text
            FROM embeddings e
            JOIN recordings r ON e.recording_id = r.id
            JOIN datasets d ON r.dataset_id = d.id
            WHERE e.id = :embedding_id
              AND d.project_id = :project_id
            LIMIT 1
            """
        )
        row = (
            await self.db.execute(
                fetch_sql,
                {"embedding_id": str(embedding_id), "project_id": str(project_id)},
            )
        ).fetchone()

        if row is None:
            raise ValueError(
                f"Embedding {embedding_id} not found in project {project_id}"
            )

        # pgvector returns the vector as a Python list when accessed via ORM,
        # but as text when using raw SQL — parse it here.
        vector_text: str = row.vector_text
        query_vector = _parse_vector_text(vector_text)

        results = await self.search_by_vector(
            project_id=project_id,
            query_vector=query_vector,
            model_name=model_name,
            limit=limit,
            min_similarity=min_similarity,
            dataset_id=dataset_id,
            exclude_embedding_ids=[embedding_id],
        )

        return SimilaritySearchResponse(
            results=results,
            query_model=model_name,
            total_results=len(results),
        )

    async def search_by_vector(
        self,
        project_id: UUID,
        query_vector: list[float],
        model_name: str,
        limit: int = 20,
        min_similarity: float = 0.5,
        dataset_id: UUID | None = None,
        exclude_embedding_ids: list[UUID] | None = None,
    ) -> list[SimilarityResult]:
        """Find similar embeddings using a raw floating-point vector.

        Uses pgvector cosine distance: similarity = 1 - (vector <=> query).

        Args:
            project_id: Project UUID for access scoping
            query_vector: Float list matching the stored embedding dimension
            model_name: Model name filter
            limit: Maximum results to return
            min_similarity: Minimum cosine similarity threshold (0.0-1.0)
            dataset_id: Optional dataset filter
            exclude_embedding_ids: Optional embedding UUIDs to exclude from results

        Returns:
            List of SimilarityResult ordered by descending similarity
        """
        # Build the pgvector literal string: '[0.1,0.2,...]'
        # NOTE: vector_literal is built from float values only (no user input),
        # so there is no SQL injection risk here.  All actual user-supplied
        # filter values (project_id, model_name, dataset_id, etc.) are passed
        # through SQLAlchemy bind parameters in the `params` dict below.
        # Do NOT add any string-interpolated user input to extra_sql.
        vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

        # Build optional WHERE clauses — all values go through bind parameters
        extra_where: list[str] = []
        params: dict[str, object] = {
            "project_id": str(project_id),
            "model_name": model_name,
            "min_similarity": min_similarity,
            "limit": limit,
            "query_vector": vector_literal,
        }

        if dataset_id is not None:
            extra_where.append("d.id = :dataset_id")
            params["dataset_id"] = str(dataset_id)

        if exclude_embedding_ids:
            # Build parameterised exclusion list
            exc_strs = [str(uid) for uid in exclude_embedding_ids]
            params["exclude_ids"] = exc_strs
            extra_where.append("e.id != ALL(:exclude_ids::uuid[])")

        extra_sql = ""
        if extra_where:
            extra_sql = " AND " + " AND ".join(extra_where)

        sql = text(
            f"""
            SELECT
                e.id          AS embedding_id,
                e.recording_id,
                r.filename    AS recording_filename,
                r.datetime    AS recording_datetime,
                r.dataset_id,
                e.start_time,
                e.end_time,
                1 - (e.vector <=> CAST(:query_vector AS vector)) AS similarity
            FROM embeddings e
            JOIN recordings r ON e.recording_id = r.id
            JOIN datasets d   ON r.dataset_id   = d.id
            WHERE d.project_id = :project_id
              AND e.model_name  = :model_name
              AND 1 - (e.vector <=> CAST(:query_vector AS vector)) >= :min_similarity
              {extra_sql}
            ORDER BY e.vector <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        )

        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        return [
            SimilarityResult(
                embedding_id=row.embedding_id,
                recording_id=row.recording_id,
                recording_filename=row.recording_filename,
                recording_datetime=row.recording_datetime,
                dataset_id=row.dataset_id,
                start_time=float(row.start_time),
                end_time=float(row.end_time),
                similarity=float(row.similarity),
            )
            for row in rows
        ]

    async def search_by_audio_file(
        self,
        project_id: UUID,
        audio_path: str,
        model_name: str,
        limit: int = 20,
        min_similarity: float = 0.5,
        dataset_id: UUID | None = None,
    ) -> SimilaritySearchResponse:
        """Generate an embedding from a local audio file and search for similar sounds.

        Loads the model via ModelRegistry, runs inference on the audio file,
        then searches using the resulting embedding vectors.

        Args:
            project_id: Project UUID for access scoping
            audio_path: Absolute local path to the audio file
            model_name: Model name to use for embedding generation
            limit: Maximum results to return
            min_similarity: Minimum cosine similarity threshold (0.0-1.0)
            dataset_id: Optional dataset filter

        Returns:
            SimilaritySearchResponse with ordered results

        Raises:
            ValueError: If the model is not registered or audio cannot be processed
            FileNotFoundError: If the audio file does not exist
        """
        from echoroo.ml.registry import ModelNotFoundError, ModelRegistry

        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Retrieve or initialise the model from the process-level cache.
        # Loading model weights is expensive (several seconds), so we keep a
        # cached (loader, engine) pair for each model name and reuse it across
        # requests.
        try:
            _, engine = _get_or_load_model(model_name)
        except ModelNotFoundError as exc:
            available = ModelRegistry.available_models()
            raise ValueError(
                f"Model '{model_name}' not registered. Available: {available}"
            ) from exc

        # Run file inference to get embeddings
        inference_results = engine.predict_file(Path(audio_path))

        if not inference_results:
            logger.warning(
                "No inference results from audio file %s with model %s",
                audio_path,
                model_name,
            )
            return SimilaritySearchResponse(
                results=[],
                query_model=model_name,
                total_results=0,
            )

        # Use the first segment's embedding as the representative query vector
        # (for short uploaded clips there will typically be one segment)
        raw_embedding: list[float] = inference_results[0].embedding.tolist()

        # Zero-pad to the storage dimension so the pgvector distance operator
        # does not raise a dimension mismatch error.  Stored vectors are always
        # _STORAGE_EMBEDDING_DIM-dimensional (BirdNET 1024-dim is padded at
        # write time); query vectors must match.
        if len(raw_embedding) < _STORAGE_EMBEDDING_DIM:
            raw_embedding.extend([0.0] * (_STORAGE_EMBEDDING_DIM - len(raw_embedding)))
        query_embedding: list[float] = raw_embedding[:_STORAGE_EMBEDDING_DIM]

        logger.info(
            "Generated embedding from audio (model=%s, segments=%d, dim=%d)",
            model_name,
            len(inference_results),
            len(query_embedding),
        )

        results = await self.search_by_vector(
            project_id=project_id,
            query_vector=query_embedding,
            model_name=model_name,
            limit=limit,
            min_similarity=min_similarity,
            dataset_id=dataset_id,
        )

        return SimilaritySearchResponse(
            results=results,
            query_model=model_name,
            total_results=len(results),
        )

    async def get_embedding_stats(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
    ) -> EmbeddingStatsResponse:
        """Get statistics about stored embeddings for a project.

        Args:
            project_id: Project UUID for access scoping
            dataset_id: Optional dataset filter

        Returns:
            EmbeddingStatsResponse with total count, per-model, and per-dataset counts
        """
        # Build optional dataset filter clause
        dataset_filter = ""
        params: dict[str, object] = {"project_id": str(project_id)}

        if dataset_id is not None:
            dataset_filter = "AND d.id = :dataset_id"
            params["dataset_id"] = str(dataset_id)

        # Total count
        total_sql = text(
            f"""
            SELECT COUNT(*) AS cnt
            FROM embeddings e
            JOIN recordings r ON e.recording_id = r.id
            JOIN datasets d   ON r.dataset_id   = d.id
            WHERE d.project_id = :project_id
              {dataset_filter}
            """
        )
        total_row = (await self.db.execute(total_sql, params)).fetchone()
        total_count = int(total_row.cnt) if total_row else 0

        # Count by model name
        model_sql = text(
            f"""
            SELECT e.model_name, COUNT(*) AS cnt
            FROM embeddings e
            JOIN recordings r ON e.recording_id = r.id
            JOIN datasets d   ON r.dataset_id   = d.id
            WHERE d.project_id = :project_id
              {dataset_filter}
            GROUP BY e.model_name
            ORDER BY cnt DESC
            """
        )
        model_rows = (await self.db.execute(model_sql, params)).fetchall()
        by_model: dict[str, int] = {row.model_name: int(row.cnt) for row in model_rows}

        # Count by dataset (skip when already filtered to one dataset)
        if dataset_id is not None:
            by_dataset: dict[str, int] = {str(dataset_id): total_count}
        else:
            dataset_sql = text(
                """
                SELECT d.id AS dataset_id, COUNT(*) AS cnt
                FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d   ON r.dataset_id   = d.id
                WHERE d.project_id = :project_id
                GROUP BY d.id
                ORDER BY cnt DESC
                """
            )
            dataset_rows = (
                await self.db.execute(dataset_sql, {"project_id": str(project_id)})
            ).fetchall()
            by_dataset = {str(row.dataset_id): int(row.cnt) for row in dataset_rows}

        return EmbeddingStatsResponse(
            total_count=total_count,
            by_model=by_model,
            by_dataset=by_dataset,
        )

    async def get_similarity_distribution(
        self,
        project_id: UUID,
        query_vectors: list[list[float]],
        model_name: str,
        bin_width: float = 0.05,
        dataset_id: UUID | None = None,
    ) -> SimilarityDistributionResponse:
        """Compute a histogram of cosine similarities for all embeddings against query vectors.

        For each embedding in the project, computes the maximum cosine similarity
        across all provided query vectors, then bins the result into a histogram.
        Uses SQL aggregation so no individual vectors are loaded into Python.

        Args:
            project_id: Project UUID for access scoping
            query_vectors: List of query vectors to compute similarities against
            model_name: Model name filter
            bin_width: Histogram bin width (default 0.05 gives 20 bins from 0 to 1)
            dataset_id: Optional dataset filter

        Returns:
            SimilarityDistributionResponse with histogram bins and total count
        """
        if not query_vectors:
            return SimilarityDistributionResponse(bins=[], total=0, bin_width=bin_width)

        dataset_filter = ""
        base_params: dict[str, object] = {
            "project_id": str(project_id),
            "model_name": model_name,
        }
        if dataset_id is not None:
            dataset_filter = "AND d.id = :dataset_id"
            base_params["dataset_id"] = str(dataset_id)

        # Build a UNION ALL CTE that computes similarity for each query vector,
        # then take the max similarity per embedding_id across all query vectors.
        # NOTE: vector literals are constructed from float values only (no user input),
        # so there is no SQL injection risk.
        union_parts: list[str] = []
        params: dict[str, object] = dict(base_params)

        for idx, qv in enumerate(query_vectors):
            vec_literal = "[" + ",".join(str(v) for v in qv) + "]"
            param_key = f"qv_{idx}"
            params[param_key] = vec_literal
            union_parts.append(
                f"""
                SELECT
                    e.id AS embedding_id,
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
        params["bin_width"] = bin_width

        # Filter out NaN similarities (zero-vector embeddings produce NaN when
        # divided in cosine distance). The ``similarity = similarity`` predicate
        # is the SQL idiom for "not NaN" since NaN never equals itself.
        # FLOOR(NaN / x) returns NaN in Postgres which then breaks the Python
        # ``int(NaN)`` conversion downstream — filter at SQL so the loop never
        # sees them.
        dist_sql = text(
            f"""
            WITH all_similarities AS (
                {union_sql}
            ),
            max_similarities AS (
                SELECT embedding_id, MAX(similarity) AS similarity
                FROM all_similarities
                GROUP BY embedding_id
            )
            SELECT
                FLOOR(similarity / :bin_width) * :bin_width AS bin_lower,
                COUNT(*) AS cnt
            FROM max_similarities
            WHERE similarity = similarity
            GROUP BY bin_lower
            ORDER BY bin_lower
            """
        )

        rows = (await self.db.execute(dist_sql, params)).fetchall()

        # Count total embeddings (sum of all bins)
        total = sum(int(row.cnt) for row in rows)

        # Build complete bin list covering [0, 1] in steps of bin_width,
        # filling in zero-count bins for ranges with no results.
        n_bins = round(1.0 / bin_width)
        bin_counts: dict[int, int] = {}
        for row in rows:
            bin_lower = float(row.bin_lower)
            # Defensive guard: if any NaN slipped past the SQL filter, skip the
            # row rather than raising ``ValueError`` from ``int(NaN)``.
            if bin_lower != bin_lower:  # NaN check
                continue
            # Use integer index to avoid floating-point key comparison issues
            bin_idx = round(bin_lower / bin_width)
            bin_counts[bin_idx] = int(row.cnt)

        bins: list[SimilarityBin] = []
        for i in range(n_bins):
            lower = round(i * bin_width, 10)
            upper = round((i + 1) * bin_width, 10)
            bins.append(
                SimilarityBin(
                    lower=lower,
                    upper=upper,
                    count=bin_counts.get(i, 0),
                )
            )

        return SimilarityDistributionResponse(bins=bins, total=total, bin_width=bin_width)

    async def sample_by_similarity_range(
        self,
        project_id: UUID,
        query_vectors: list[list[float]],
        model_name: str,
        min_similarity: float,
        max_similarity: float,
        limit: int = 20,
        dataset_id: UUID | None = None,
    ) -> tuple[list[SimilarityResult], int]:
        """Randomly sample embeddings within a similarity range against query vectors.

        For each embedding, the max similarity across all query vectors is computed.
        Only embeddings whose max similarity falls within [min_similarity, max_similarity]
        are considered. A random sample of up to `limit` results is returned.

        Args:
            project_id: Project UUID for access scoping
            query_vectors: List of query vectors to compute similarities against
            model_name: Model name filter
            min_similarity: Lower bound of similarity range (inclusive)
            max_similarity: Upper bound of similarity range (inclusive)
            limit: Maximum number of randomly sampled results to return
            dataset_id: Optional dataset filter

        Returns:
            Tuple of (list of SimilarityResult randomly sampled, total count in range)
        """
        if not query_vectors:
            return [], 0

        dataset_filter = ""
        base_params: dict[str, object] = {
            "project_id": str(project_id),
            "model_name": model_name,
        }
        if dataset_id is not None:
            dataset_filter = "AND d.id = :dataset_id"
            base_params["dataset_id"] = str(dataset_id)

        # Build UNION ALL across all query vectors to get similarity per embedding_id.
        # NOTE: vector literals are constructed from float values only — no injection risk.
        union_parts: list[str] = []
        params: dict[str, object] = dict(base_params)

        for idx, qv in enumerate(query_vectors):
            vec_literal = "[" + ",".join(str(v) for v in qv) + "]"
            param_key = f"qv_{idx}"
            params[param_key] = vec_literal
            union_parts.append(
                f"""
                SELECT
                    e.id AS embedding_id,
                    e.recording_id,
                    r.filename    AS recording_filename,
                    r.datetime    AS recording_datetime,
                    r.dataset_id,
                    e.start_time,
                    e.end_time,
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
        params["min_similarity"] = min_similarity
        params["max_similarity"] = max_similarity
        params["limit"] = limit

        # Use a CTE to compute max similarities, then count total in range and
        # randomly sample up to `limit` results in one round trip.
        sample_sql = text(
            f"""
            WITH all_similarities AS (
                {union_sql}
            ),
            max_similarities AS (
                SELECT
                    embedding_id,
                    recording_id,
                    recording_filename,
                    recording_datetime,
                    dataset_id,
                    start_time,
                    end_time,
                    MAX(similarity) AS similarity
                FROM all_similarities
                GROUP BY
                    embedding_id,
                    recording_id,
                    recording_filename,
                    recording_datetime,
                    dataset_id,
                    start_time,
                    end_time
            ),
            in_range AS (
                SELECT *
                FROM max_similarities
                WHERE similarity >= :min_similarity
                  AND similarity <= :max_similarity
            ),
            total AS (
                SELECT COUNT(*) AS total_in_range FROM in_range
            )
            SELECT ir.*, t.total_in_range
            FROM in_range ir
            CROSS JOIN total t
            ORDER BY RANDOM()
            LIMIT :limit
            """
        )

        rows = (await self.db.execute(sample_sql, params)).fetchall()

        total_in_range = int(rows[0].total_in_range) if rows else 0

        results = [
            SimilarityResult(
                embedding_id=row.embedding_id,
                recording_id=row.recording_id,
                recording_filename=row.recording_filename,
                recording_datetime=row.recording_datetime,
                dataset_id=row.dataset_id,
                start_time=float(row.start_time),
                end_time=float(row.end_time),
                similarity=float(row.similarity),
            )
            for row in rows
        ]

        return results, total_in_range

    async def get_time_distribution(
        self,
        project_id: UUID,
        query_vectors: list[list[float]],
        model_name: str,
        dataset_id: UUID | None = None,
    ) -> dict[str, object]:
        """Compute average similarity grouped by (date, hour) for all project embeddings.

        For each embedding with a recording datetime, computes the maximum cosine
        similarity across all provided query vectors, then groups by date and hour
        returning average similarity and count per cell.

        Recording datetimes are converted to the dataset's configured timezone
        (``datetime_timezone``) before extracting the hour. If datasets have
        different timezones, each recording uses its own dataset's timezone.

        Args:
            project_id: Project UUID for access scoping
            query_vectors: List of query vectors to compute similarities against
            model_name: Model name filter
            dataset_id: Optional dataset filter

        Returns:
            Dict with keys:
                cells: list of dicts with date, hour, avg_similarity, count
                timezone: IANA timezone string used (or "Mixed" if multiple)
        """
        if not query_vectors:
            return {"cells": [], "timezone": "UTC"}

        dataset_filter = ""
        base_params: dict[str, object] = {
            "project_id": str(project_id),
            "model_name": model_name,
        }
        if dataset_id is not None:
            dataset_filter = "AND d.id = :dataset_id"
            base_params["dataset_id"] = str(dataset_id)

        # Build UNION ALL across all query vectors
        union_parts: list[str] = []
        params: dict[str, object] = dict(base_params)

        for idx, qv in enumerate(query_vectors):
            vec_literal = "[" + ",".join(str(v) for v in qv) + "]"
            param_key = f"qv_{idx}"
            params[param_key] = vec_literal
            union_parts.append(
                f"""
                SELECT
                    e.id AS embedding_id,
                    r.datetime AS recording_datetime,
                    COALESCE(d.datetime_timezone, 'UTC') AS tz,
                    1 - (e.vector <=> CAST(:{param_key} AS vector)) AS similarity
                FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d   ON r.dataset_id   = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name  = :model_name
                  AND r.datetime IS NOT NULL
                  {dataset_filter}
                """
            )

        union_sql = " UNION ALL ".join(union_parts)

        # Convert each recording's datetime to its dataset's timezone before
        # extracting date and hour.  PostgreSQL's ``AT TIME ZONE`` converts a
        # ``timestamptz`` to a ``timestamp`` in the given zone, so EXTRACT
        # will return the local hour.
        time_dist_sql = text(
            f"""
            WITH all_similarities AS (
                {union_sql}
            ),
            max_similarities AS (
                SELECT
                    embedding_id,
                    recording_datetime,
                    tz,
                    MAX(similarity) AS similarity
                FROM all_similarities
                GROUP BY embedding_id, recording_datetime, tz
            )
            SELECT
                DATE(recording_datetime AT TIME ZONE tz)::text AS date,
                EXTRACT(HOUR FROM recording_datetime AT TIME ZONE tz)::int AS hour,
                AVG(similarity) AS avg_similarity,
                COUNT(*) AS count
            FROM max_similarities
            GROUP BY DATE(recording_datetime AT TIME ZONE tz),
                     EXTRACT(HOUR FROM recording_datetime AT TIME ZONE tz)
            ORDER BY date, hour
            """
        )

        rows = (await self.db.execute(time_dist_sql, params)).fetchall()

        cells = [
            {
                "date": row.date,
                "hour": int(row.hour),
                "avg_similarity": float(row.avg_similarity),
                "count": int(row._mapping["count"]),
            }
            for row in rows
        ]

        # Determine the timezone label for the response
        tz_sql = text(
            f"""
            SELECT DISTINCT COALESCE(d.datetime_timezone, 'UTC') AS tz
            FROM embeddings e
            JOIN recordings r ON e.recording_id = r.id
            JOIN datasets d   ON r.dataset_id   = d.id
            WHERE d.project_id = :project_id
              AND e.model_name  = :model_name
              AND r.datetime IS NOT NULL
              {dataset_filter}
            """
        )
        tz_rows = (await self.db.execute(tz_sql, base_params)).fetchall()
        distinct_tzs = [r.tz for r in tz_rows]
        if len(distinct_tzs) == 1:
            timezone = distinct_tzs[0]
        elif len(distinct_tzs) > 1:
            timezone = "Mixed"
        else:
            timezone = "UTC"

        return {"cells": cells, "timezone": timezone}

    async def batch_search(
        self,
        project_id: UUID,
        request: BatchSearchRequest,
        audio_files: dict[str, str],
    ) -> BatchSearchResponse:
        """Search for multiple species simultaneously using reference audio clips.

        For each species config, this method:
        1. Processes each source audio file (clip to start_time/end_time if set)
        2. Runs model inference to generate query embeddings
        3. Searches pgvector for each query vector
        4. Aggregates results: max(similarity) per candidate across all query vectors
        5. Deduplicates overlapping time ranges, keeps highest score
        6. Sorts and trims to limit_per_species

        Args:
            project_id: Project UUID for access scoping
            request: Batch search parameters including species configs
            audio_files: Mapping of file_key to local temp file paths

        Returns:
            BatchSearchResponse with per-species results and timing

        Raises:
            ValueError: If model is not registered or audio cannot be processed
        """
        import contextlib
        import os

        start_ts = time.monotonic()

        dataset_id: UUID | None = None
        if request.dataset_id is not None and request.dataset_id.strip() != "":
            try:
                dataset_id = UUID(request.dataset_id)
            except ValueError as exc:
                raise ValueError(
                    f"Invalid dataset_id: {request.dataset_id!r}"
                ) from exc

        # Load model once for all species
        from echoroo.ml.registry import ModelNotFoundError, ModelRegistry

        try:
            _, engine = _get_or_load_model(request.model_name)
        except ModelNotFoundError as exc:
            available = ModelRegistry.available_models()
            raise ValueError(
                f"Model '{request.model_name}' not registered. Available: {available}"
            ) from exc

        results: dict[str, SpeciesMatchResult] = {}
        total_matches = 0

        for species_cfg in request.species:
            # Resolve or create the tag for this species
            tag_id_key: str
            common_name: str | None = None

            if species_cfg.tag_id is not None:
                tag_id_key = species_cfg.tag_id
                # Fetch common_name from DB
                tag_sql = text(
                    "SELECT common_name FROM tags WHERE id = :tag_id LIMIT 1"
                )
                tag_row = (
                    await self.db.execute(
                        tag_sql, {"tag_id": str(species_cfg.tag_id)}
                    )
                ).fetchone()
                if tag_row is not None:
                    common_name = tag_row.common_name
            else:
                # Auto-create a tag for the custom species and use its ID as key
                from echoroo.repositories.tag import TagRepository

                tag_repo = TagRepository(self.db)
                tag = await tag_repo.get_or_create_species(
                    project_id=project_id,
                    scientific_name=species_cfg.scientific_name,
                    common_name=species_cfg.scientific_name,
                )
                tag_id_key = str(tag.id)
                common_name = tag.common_name

            # Collect all query vectors for this species across all sources
            query_vectors: list[list[float]] = []
            clipped_tmp_paths: list[str] = []

            for source in species_cfg.sources:
                if source.type == "url":
                    # Download the audio file from the provided URL and process it
                    if not source.source_url:
                        logger.warning(
                            "URL source for species '%s' has no source_url, skipping",
                            species_cfg.scientific_name,
                        )
                        continue

                    downloaded_path = await _download_audio_url(source.source_url)
                    if downloaded_path is None:
                        logger.warning(
                            "Failed to download audio from URL '%s' for species '%s', skipping",
                            source.source_url,
                            species_cfg.scientific_name,
                        )
                        continue

                    clipped_tmp_paths.append(downloaded_path)

                    # Clip audio if start_time or end_time is specified
                    audio_path_for_inference = downloaded_path
                    if source.start_time is not None or source.end_time is not None:
                        clipped_path = _clip_audio(
                            downloaded_path,
                            start_time=source.start_time,
                            end_time=source.end_time,
                        )
                        if clipped_path is not None:
                            clipped_tmp_paths.append(clipped_path)
                            audio_path_for_inference = clipped_path

                    # Run inference on the downloaded audio
                    try:
                        inference_results = engine.predict_file(Path(audio_path_for_inference))
                    except Exception:
                        logger.exception(
                            "Inference failed for URL source '%s', skipping",
                            source.source_url,
                        )
                        continue

                    for inf_res in inference_results:
                        raw_emb: list[float] = inf_res.embedding.tolist()
                        if len(raw_emb) < _STORAGE_EMBEDDING_DIM:
                            raw_emb.extend([0.0] * (_STORAGE_EMBEDDING_DIM - len(raw_emb)))
                        query_vectors.append(raw_emb[:_STORAGE_EMBEDDING_DIM])

                    continue

                if source.file_key is None or source.file_key not in audio_files:
                    logger.warning(
                        "Missing audio file for key '%s', skipping source",
                        source.file_key,
                    )
                    continue

                src_path = audio_files[source.file_key]

                # Clip audio if start_time or end_time is specified
                audio_path_for_inference = src_path
                if source.start_time is not None or source.end_time is not None:
                    clipped_path = _clip_audio(
                        src_path,
                        start_time=source.start_time,
                        end_time=source.end_time,
                    )
                    if clipped_path is not None:
                        clipped_tmp_paths.append(clipped_path)
                        audio_path_for_inference = clipped_path

                # Run inference to get embedding vectors
                try:
                    inference_results = engine.predict_file(Path(audio_path_for_inference))
                except Exception:
                    logger.exception(
                        "Inference failed for source '%s', skipping",
                        source.file_key,
                    )
                    continue

                for inf_res in inference_results:
                    upload_emb: list[float] = inf_res.embedding.tolist()
                    # Zero-pad to storage dimension
                    if len(upload_emb) < _STORAGE_EMBEDDING_DIM:
                        upload_emb.extend([0.0] * (_STORAGE_EMBEDDING_DIM - len(upload_emb)))
                    query_vectors.append(upload_emb[:_STORAGE_EMBEDDING_DIM])

            # Clean up clipped temp files for this source set
            for tmp_p in clipped_tmp_paths:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_p)

            if not query_vectors:
                logger.warning(
                    "No valid query vectors generated for species '%s', skipping",
                    species_cfg.scientific_name,
                )
                results[tag_id_key] = SpeciesMatchResult(
                    tag_id=tag_id_key,
                    scientific_name=species_cfg.scientific_name,
                    common_name=common_name,
                    matches=[],
                )
                continue

            # Search using all query vectors concurrently and aggregate by max similarity.
            # asyncio.gather() parallelises the pgvector queries instead of
            # issuing them sequentially (N+1 fix).
            best_by_candidate: dict[str, SimilarityResult] = {}

            per_vector_results: list[list[SimilarityResult]] = await asyncio.gather(
                *[
                    self.search_by_vector(
                        project_id=project_id,
                        query_vector=qv,
                        model_name=request.model_name,
                        # Fetch more candidates than needed to ensure coverage
                        # after deduplication
                        limit=request.limit_per_species * 3,
                        min_similarity=request.min_similarity,
                        dataset_id=dataset_id,
                    )
                    for qv in query_vectors
                ]
            )
            for vec_results in per_vector_results:
                for sim_result in vec_results:
                    candidate_key = _candidate_key(sim_result)
                    existing = best_by_candidate.get(candidate_key)
                    if existing is None or sim_result.similarity > existing.similarity:
                        best_by_candidate[candidate_key] = sim_result

            # Sort by descending similarity and truncate
            sorted_matches = sorted(
                best_by_candidate.values(),
                key=lambda r: r.similarity,
                reverse=True,
            )[: request.limit_per_species]

            total_matches += len(sorted_matches)
            results[tag_id_key] = SpeciesMatchResult(
                tag_id=tag_id_key,
                scientific_name=species_cfg.scientific_name,
                common_name=common_name,
                matches=sorted_matches,
            )

            logger.info(
                "Batch search: species='%s' query_vectors=%d matches=%d",
                species_cfg.scientific_name,
                len(query_vectors),
                len(sorted_matches),
            )

        elapsed_ms = int((time.monotonic() - start_ts) * 1000)

        return BatchSearchResponse(
            results=results,
            total_matches=total_matches,
            search_duration_ms=elapsed_ms,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Maximum file size allowed for URL audio downloads (10 MB)
_URL_DOWNLOAD_MAX_BYTES = 10 * 1024 * 1024

# Timeout in seconds for audio file downloads from URLs
_URL_DOWNLOAD_TIMEOUT = 30.0


async def _download_audio_url(url: str) -> str | None:
    """Download an audio file from a URL to a local temporary file.

    Streams the response to avoid loading large files entirely into memory.
    Enforces a 10 MB size limit and a 30-second download timeout.

    Args:
        url: Public URL of the audio file to download

    Returns:
        Absolute path to the downloaded temporary file, or None on any error
    """
    import contextlib
    import os

    import httpx

    # Determine a reasonable file suffix from the URL path
    url_path = url.split("?")[0]  # strip query string before inspecting extension
    suffix = Path(url_path).suffix.lower() or ".wav"
    allowed = {".wav", ".mp3", ".flac", ".ogg", ".opus"}
    if suffix not in allowed:
        suffix = ".wav"

    tmp_path: str | None = None
    try:
        async with httpx.AsyncClient(timeout=_URL_DOWNLOAD_TIMEOUT) as client, client.stream("GET", url) as resp:
            resp.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                tmp_path = tmp_file.name
                downloaded = 0
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    downloaded += len(chunk)
                    if downloaded > _URL_DOWNLOAD_MAX_BYTES:
                        logger.warning(
                            "Audio download from '%s' exceeded %d byte limit, aborting",
                            url,
                            _URL_DOWNLOAD_MAX_BYTES,
                        )
                        # Clean up the partial file before returning
                        with contextlib.suppress(OSError):
                            os.unlink(tmp_path)
                        return None
                    tmp_file.write(chunk)

        logger.info("Downloaded audio from '%s' to '%s' (%d bytes)", url, tmp_path, downloaded)
        return tmp_path

    except httpx.TimeoutException:
        logger.warning("Timed out downloading audio from '%s'", url)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP %s error downloading audio from '%s'", exc.response.status_code, url
        )
    except httpx.RequestError as exc:
        logger.warning("Network error downloading audio from '%s': %s", url, exc)
    except Exception:
        logger.exception("Unexpected error downloading audio from '%s'", url)

    # Clean up any partial temp file on error
    if tmp_path is not None:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)

    return None


def _clip_audio(
    src_path: str,
    start_time: float | None,
    end_time: float | None,
) -> str | None:
    """Read a time slice from an audio file and write it to a new temp file.

    Returns the path to the clipped temp file, or None on error.

    Args:
        src_path: Path to the source audio file
        start_time: Clip start in seconds (None = 0)
        end_time: Clip end in seconds (None = full duration)

    Returns:
        Path to the clipped temp file, or None if clipping failed
    """
    import tempfile

    import soundfile as sf

    try:
        info = sf.info(src_path)
        sr = info.samplerate

        frame_start = int((start_time or 0.0) * sr)
        frames = (
            max(1, int((end_time - (start_time or 0.0)) * sr)) if end_time is not None else -1
        )

        data, _ = sf.read(src_path, start=frame_start, frames=frames, dtype="float32")

        suffix = Path(src_path).suffix or ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            clipped_path = tmp.name

        sf.write(clipped_path, data, sr)
        return clipped_path
    except Exception:
        logger.exception("Failed to clip audio '%s'", src_path)
        return None


def _candidate_key(result: SimilarityResult) -> str:
    """Build a deduplication key for a similarity result.

    Results from the same recording with the same segment boundaries are
    considered identical. We use embedding_id as it uniquely identifies a
    stored segment.

    Args:
        result: Similarity result to build a key for

    Returns:
        String key suitable for dict-based deduplication
    """
    return str(result.embedding_id)


def _get_or_load_model(model_name: str) -> tuple[ModelLoader, InferenceEngine]:
    """Return a cached (loader, engine) pair, loading it on first call.

    Delegates to the centralised model_preloader so that GPU workers share
    the same pre-loaded instances rather than maintaining a separate cache.

    Args:
        model_name: Registered model name (e.g. "birdnet", "perch")

    Returns:
        Tuple of (loader, engine) ready for inference

    Raises:
        ModelNotFoundError: If model_name is not in the ModelRegistry
    """
    from echoroo.workers.model_preloader import get_model

    return get_model(model_name)


def _parse_vector_text(vector_text: str) -> list[float]:
    """Parse pgvector text representation '[0.1,0.2,...]' into a float list.

    Args:
        vector_text: Vector string as returned by pgvector via raw SQL

    Returns:
        List of float values

    Raises:
        ValueError: If the vector text cannot be parsed
    """
    try:
        stripped = vector_text.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        return [float(x) for x in stripped.split(",") if x.strip()]
    except Exception as exc:
        raise ValueError(
            f"Cannot parse pgvector text as float list: {vector_text!r}"
        ) from exc
