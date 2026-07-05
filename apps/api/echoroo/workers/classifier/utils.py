"""Shared helper functions for the custom classifier worker tasks.

Embedding fetch/parse helpers plus S3 model-artifact download/upload. Split
out of the former ``classifier_tasks`` monolith; behavior is unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings

logger = logging.getLogger(__name__)

# Maximum number of unlabeled embeddings to fetch for semi-supervised training
_MAX_UNLABELED_SAMPLES = 2000


async def _fetch_training_embeddings(
    db: AsyncSession,
    model_id: UUID,
    embedding_model_name: str,
    target_tag_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """Fetch labeled embeddings from completed sampling rounds for the given model.

    Uses a single JOIN query (no N+1) to retrieve annotation status and the
    directly linked Perch embedding vector from sampling_round_items.
    Only items from completed sampling rounds are used.

    When target_tag_id is provided, only annotations matching that tag are
    fetched. This is required to ensure only the correct species' annotations
    are used for training.

    Args:
        db: Active async database session.
        model_id: CustomModel UUID to fetch training data for.
        embedding_model_name: Embedding model name to filter (e.g. "perch").
        target_tag_id: If provided, restrict annotations to this tag UUID.
            confirmed + matching tag -> label 1 (positive)
            rejected  + matching tag -> label 0 (negative)
            Different tag            -> excluded by WHERE clause

    Returns:
        List of dicts with keys: annotation_id, embedding_id, recording_id,
        label (0 or 1), vector.
    """
    if target_tag_id is not None:
        sql = text("""
            SELECT
                a.id         AS annotation_id,
                sri.embedding_id AS embedding_id,
                a.status     AS annotation_status,
                e.vector     AS vector,
                e.recording_id AS recording_id
            FROM sampling_round_items sri
            JOIN sampling_rounds sr
                ON sr.id = sri.sampling_round_id
                AND sr.custom_model_id = :model_id
                AND sr.status = 'completed'
            JOIN recording_annotations a
                ON a.id = sri.annotation_id
                AND a.status IN ('confirmed', 'rejected')
                AND a.tag_id = :target_tag_id
            JOIN embeddings e
                ON e.id = sri.embedding_id
                AND e.model_name = :embedding_model_name
        """)
        params: dict[str, Any] = {
            "model_id": str(model_id),
            "embedding_model_name": embedding_model_name,
            "target_tag_id": str(target_tag_id),
        }
    else:
        sql = text("""
            SELECT
                a.id         AS annotation_id,
                sri.embedding_id AS embedding_id,
                a.status     AS annotation_status,
                e.vector     AS vector,
                e.recording_id AS recording_id
            FROM sampling_round_items sri
            JOIN sampling_rounds sr
                ON sr.id = sri.sampling_round_id
                AND sr.custom_model_id = :model_id
                AND sr.status = 'completed'
            JOIN recording_annotations a
                ON a.id = sri.annotation_id
                AND a.status IN ('confirmed', 'rejected')
            JOIN embeddings e
                ON e.id = sri.embedding_id
                AND e.model_name = :embedding_model_name
        """)
        params = {
            "model_id": str(model_id),
            "embedding_model_name": embedding_model_name,
        }

    rows = (
        await db.execute(
            sql,
            params,
        )
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        # pgvector may return a Vector object, numpy array, or list depending on
        # the driver (asyncpg vs psycopg2) and pgvector version. Convert to a
        # plain Python list of floats to guarantee a homogeneous shape for
        # np.array() later.
        raw_vector = row.vector
        if isinstance(raw_vector, str):
            # asyncpg returns pgvector as a string like "[0.1,0.2,...]"
            import json
            vector: list[float] = [float(x) for x in json.loads(raw_vector)]
        elif hasattr(raw_vector, "tolist"):
            # numpy array or pgvector Vector with .tolist()
            vector = [float(x) for x in raw_vector.tolist()]
        elif hasattr(raw_vector, "__iter__"):
            vector = [float(x) for x in raw_vector]
        else:
            raise ValueError(
                f"Unexpected vector type {type(raw_vector)} for "
                f"embedding_id={row.embedding_id}"
            )

        logger.debug(
            "Fetched embedding embedding_id=%s annotation_id=%s "
            "vector_type=%s vector_len=%d",
            row.embedding_id,
            row.annotation_id,
            type(raw_vector).__name__,
            len(vector),
        )

        label = 1 if row.annotation_status == "confirmed" else 0
        results.append(
            {
                "annotation_id": str(row.annotation_id),
                "embedding_id": str(row.embedding_id),
                "recording_id": str(row.recording_id),
                "label": label,
                "vector": vector,
            }
        )

    return results

async def _fetch_unlabeled_embeddings(
    db: AsyncSession,
    project_id: UUID,
    embedding_model_name: str,
    exclude_embedding_ids: list[str],
    max_samples: int = _MAX_UNLABELED_SAMPLES,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Fetch random unlabeled embeddings from the project for semi-supervised training.

    Excludes embeddings already used as labeled training samples.

    Args:
        db: Active async database session.
        project_id: Project UUID.
        embedding_model_name: Embedding model name to filter.
        exclude_embedding_ids: List of embedding UUID strings to exclude.
        max_samples: Maximum number of unlabeled samples to return.

    Returns:
        Tuple of (embeddings_array, recording_ids_array) where embeddings_array
        has shape (n, embedding_dim) and recording_ids_array has shape (n,), or
        None if no samples found.
    """
    sql = text("""
        SELECT e.vector, e.recording_id
        FROM embeddings e
        JOIN recordings r ON r.id = e.recording_id
        JOIN datasets d ON d.id = r.dataset_id
        WHERE
            d.project_id = :project_id
            AND e.model_name = :embedding_model_name
            AND NOT (e.id = ANY(:exclude_ids))
        ORDER BY RANDOM()
        LIMIT :max_samples
    """)

    rows = (
        await db.execute(
            sql,
            {
                "project_id": str(project_id),
                "embedding_model_name": embedding_model_name,
                "exclude_ids": exclude_embedding_ids,
                "max_samples": max_samples,
            },
        )
    ).fetchall()

    if not rows:
        return None

    vectors: list[list[float]] = []
    recording_ids: list[str] = []
    for row in rows:
        raw_vector = row.vector
        if isinstance(raw_vector, str):
            import json
            vectors.append([float(x) for x in json.loads(raw_vector)])
        elif hasattr(raw_vector, "tolist"):
            vectors.append([float(x) for x in raw_vector.tolist()])
        else:
            vectors.append([float(x) for x in raw_vector])
        recording_ids.append(str(row.recording_id))

    return np.array(vectors, dtype=np.float32), np.array(recording_ids)

async def _download_model_from_s3(s3_key: str, local_path: Path) -> None:
    """Download a serialized model file from S3 to a local path.

    Args:
        s3_key: S3 object key (e.g. "models/{project_id}/{model_id}/model.joblib").
        local_path: Absolute local path to write the downloaded file to.

    Raises:
        Exception: If the S3 download fails.
    """
    import asyncio

    from echoroo.core.s3 import get_s3_client

    settings = get_settings()
    s3_client = get_s3_client()

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: s3_client.download_file(
            settings.S3_BUCKET,
            s3_key,
            str(local_path),
        ),
    )

async def _upload_model_to_s3(local_path: Path, s3_key: str) -> None:
    """Upload a serialized model file to S3.

    Args:
        local_path: Absolute path to the local joblib file.
        s3_key: Target S3 object key (e.g. "models/{project_id}/{model_id}/model.joblib").

    Raises:
        Exception: If the S3 upload fails.
    """
    import asyncio

    from echoroo.core.s3 import get_s3_client

    settings = get_settings()
    s3_client = get_s3_client()

    # boto3 upload_file is blocking — run in a thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: s3_client.upload_file(
            str(local_path),
            settings.S3_BUCKET,
            s3_key,
        ),
    )

def _parse_vectors(raw_vectors: list[Any]) -> np.ndarray:
    """Parse a list of raw pgvector values into a float32 numpy array.

    Handles the three formats pgvector drivers may return:
    - str (asyncpg with pgvector as text)
    - numpy array / Vector with .tolist()
    - any iterable

    Args:
        raw_vectors: List of raw vector values from the database.

    Returns:
        Float32 numpy array of shape (N, D).
    """
    import json  # noqa: PLC0415

    vectors: list[list[float]] = []
    for raw in raw_vectors:
        if isinstance(raw, str):
            vectors.append([float(x) for x in json.loads(raw)])
        elif hasattr(raw, "tolist"):
            vectors.append([float(x) for x in raw.tolist()])
        elif hasattr(raw, "__iter__"):
            vectors.append([float(x) for x in raw])
        else:
            raise ValueError(f"Unexpected vector type {type(raw)}")
    return np.array(vectors, dtype=np.float32)

