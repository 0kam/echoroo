"""Similarity search service using pgvector cosine distance.

Provides vector similarity search over stored embeddings, supporting both
embedding-ID-based queries (reuse a stored vector) and raw vector queries
(e.g., generated from an uploaded audio file).

All queries are scoped to a project_id to enforce data isolation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.schemas.search import (
    EmbeddingStatsResponse,
    SimilarityResult,
    SimilaritySearchResponse,
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

# Module-level cache so model weights are loaded once per worker process
# rather than on every incoming request.  Keys are model names; values are
# (loader, engine) pairs ready for inference.
#
# IMPORTANT: This cache is NOT thread-safe for concurrent model initialisation.
# Celery workers and gunicorn workers are single-process/single-thread per
# request, so this is safe in practice.  If you move to a threaded server,
# add a threading.Lock around the cache write.
_model_cache: dict[str, tuple[ModelLoader, InferenceEngine]] = {}


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
            loader, engine = _get_or_load_model(model_name)
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_or_load_model(model_name: str) -> tuple[ModelLoader, InferenceEngine]:
    """Return a cached (loader, engine) pair, loading it on first call.

    Model weights are expensive to load (~seconds), so we keep one instance
    per model name alive for the lifetime of the worker process.

    Args:
        model_name: Registered model name (e.g. "birdnet", "perch")

    Returns:
        Tuple of (loader, engine) ready for inference

    Raises:
        ModelNotFoundError: If model_name is not in the ModelRegistry
    """
    # Import triggers __init__.py registration side-effects for each model package
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.ml.registry import ModelRegistry

    if model_name not in _model_cache:
        loader_cls = ModelRegistry.get_loader_class(model_name)
        engine_cls = ModelRegistry.get_engine_class(model_name)
        loader = loader_cls()
        loader.load()
        engine = engine_cls(loader)
        _model_cache[model_name] = (loader, engine)
        logger.info("Loaded and cached model '%s' for similarity search", model_name)

    return _model_cache[model_name]


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
