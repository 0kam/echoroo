"""Celery worker tasks for training custom SVM classifiers.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from echoroo.core.settings import get_settings
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)

# Minimum number of positive and negative examples required to start training
_MIN_POSITIVE_SAMPLES = 5
_MIN_NEGATIVE_SAMPLES = 5

# Maximum number of unlabeled embeddings to fetch for semi-supervised training
_MAX_UNLABELED_SAMPLES = 2000


# ---------------------------------------------------------------------------
# Async session factory (same pattern as search_tasks.py / ml_tasks.py)
# ---------------------------------------------------------------------------


def _get_engine_and_session_factory() -> tuple[Any, async_sessionmaker[AsyncSession]]:
    """Create a fresh async engine and session factory for each task invocation.

    Each Celery task calls ``asyncio.run()`` which creates a new event loop.
    Reusing a cached engine across loops causes "Future attached to a different
    loop" errors, so we create a fresh engine every time.

    Returns the engine separately so the caller can dispose it in a finally
    block after the task completes, releasing all pooled connections.
    """
    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.train_custom_model",
    time_limit=600,
    soft_time_limit=540,
)
def train_custom_model(_self: Any, model_id: str) -> dict[str, Any]:
    """Train a custom SVM classifier using Perch embeddings from search session annotations.

    Reads confirmed/rejected annotations from the model's training_session_ids,
    fetches corresponding Perch embedding vectors, runs cross-validated SVM
    training, serializes the model to S3, and updates the DB record with
    metrics and status.

    Args:
        model_id: UUID string of the CustomModel record to train.

    Returns:
        Dict with training result summary (status, metrics, artifact_key).
    """
    return asyncio.run(_train_custom_model(model_id))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _train_custom_model(model_id: str) -> dict[str, Any]:
    """Async implementation of custom model training.

    Args:
        model_id: UUID string of the CustomModel record.

    Returns:
        Dict with training result summary (status, metrics, artifact_key).
    """
    from echoroo.models.custom_model import CustomModel, CustomModelStatus

    engine, session_factory = _get_engine_and_session_factory()
    try:
        async with session_factory() as db:
            # ------------------------------------------------------------------
            # Fetch and validate the CustomModel record
            # ------------------------------------------------------------------
            from sqlalchemy import select

            result = await db.execute(
                select(CustomModel).where(CustomModel.id == UUID(model_id))
            )
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            if model.status not in (CustomModelStatus.DRAFT, CustomModelStatus.FAILED):
                raise ValueError(
                    f"Cannot train model with status '{model.status}'. "
                    "Expected 'draft' or 'failed'."
                )

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name
            training_session_ids: list[str] = [
                str(s) for s in (model.training_session_ids or [])
            ]

            if not training_session_ids:
                raise ValueError("No training_session_ids configured on this model.")

            # ------------------------------------------------------------------
            # Mark model as TRAINING
            # ------------------------------------------------------------------
            model.status = CustomModelStatus.TRAINING
            model.started_at = datetime.now(UTC)
            model.error_message = None
            await db.commit()

            logger.info(
                "Starting training for model_id=%s, project_id=%s, "
                "embedding_model=%s, sessions=%d",
                model_id,
                project_id,
                embedding_model_name,
                len(training_session_ids),
            )

            try:
                result_data = await _run_training(
                    db=db,
                    model=model,
                    project_id=project_id,
                    embedding_model_name=embedding_model_name,
                    training_session_ids=training_session_ids,
                )
            except Exception as exc:
                # Mark model as FAILED and persist error
                model.status = CustomModelStatus.FAILED
                model.error_message = str(exc)
                model.completed_at = datetime.now(UTC)
                try:
                    await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to persist FAILED status for model_id=%s", model_id
                    )
                raise

            return result_data

    finally:
        await engine.dispose()


async def _run_training(
    db: AsyncSession,
    model: Any,
    project_id: UUID,
    embedding_model_name: str,
    training_session_ids: list[str],
) -> dict[str, Any]:
    """Core training logic: collect data, train model, upload to S3, update DB.

    Args:
        db: Active async database session.
        model: CustomModel ORM instance (already in TRAINING state).
        project_id: Project UUID.
        embedding_model_name: Name of the embedding model (e.g. "perch").
        training_session_ids: List of search session UUID strings.

    Returns:
        Dict with training result summary.
    """
    from echoroo.models.custom_model import CustomModelStatus

    # ------------------------------------------------------------------
    # Step 1: Collect training data via a single batch SQL query
    # ------------------------------------------------------------------
    training_rows = await _fetch_training_embeddings(
        db=db,
        session_ids=training_session_ids,
        embedding_model_name=embedding_model_name,
    )

    positive_rows = [r for r in training_rows if r["label"] == 1]
    negative_rows = [r for r in training_rows if r["label"] == 0]

    logger.info(
        "Training data: positive=%d, negative=%d (model_id=%s)",
        len(positive_rows),
        len(negative_rows),
        str(model.id),
    )

    # ------------------------------------------------------------------
    # Step 2: Validate minimum sample requirements
    # ------------------------------------------------------------------
    if len(positive_rows) < _MIN_POSITIVE_SAMPLES:
        raise ValueError(
            f"Insufficient positive examples: {len(positive_rows)} "
            f"(minimum {_MIN_POSITIVE_SAMPLES} required)."
        )
    if len(negative_rows) < _MIN_NEGATIVE_SAMPLES:
        raise ValueError(
            f"Insufficient negative examples: {len(negative_rows)} "
            f"(minimum {_MIN_NEGATIVE_SAMPLES} required)."
        )

    # Build labeled arrays
    embeddings_list = positive_rows + negative_rows
    embeddings = np.array([r["vector"] for r in embeddings_list], dtype=np.float32)
    labels = np.array(
        [1] * len(positive_rows) + [0] * len(negative_rows), dtype=np.int32
    )

    # ------------------------------------------------------------------
    # Step 3: Optionally fetch unlabeled embeddings for semi-supervised training
    # ------------------------------------------------------------------
    use_unlabeled = bool((model.hyperparameters or {}).get("use_unlabeled", True))
    unlabeled_embeddings: np.ndarray | None = None

    if use_unlabeled:
        # Collect already-used embedding IDs to exclude them
        labeled_embedding_ids = [r["embedding_id"] for r in embeddings_list]
        unlabeled_embeddings = await _fetch_unlabeled_embeddings(
            db=db,
            project_id=project_id,
            embedding_model_name=embedding_model_name,
            exclude_embedding_ids=labeled_embedding_ids,
            max_samples=_MAX_UNLABELED_SAMPLES,
        )

        if unlabeled_embeddings is not None and len(unlabeled_embeddings) > 0:
            from echoroo.ml.classifiers import reduce_unlabeled_samples

            if len(unlabeled_embeddings) > _MAX_UNLABELED_SAMPLES:
                unlabeled_embeddings = reduce_unlabeled_samples(
                    unlabeled_embeddings, max_samples=_MAX_UNLABELED_SAMPLES
                )
            logger.info(
                "Unlabeled samples for semi-supervised training: %d (model_id=%s)",
                len(unlabeled_embeddings),
                str(model.id),
            )
        else:
            unlabeled_embeddings = None
            logger.info("No unlabeled embeddings available for model_id=%s", str(model.id))

    # ------------------------------------------------------------------
    # Step 4: Train classifier with cross-validation
    # ------------------------------------------------------------------
    from echoroo.ml.classifiers import train_with_cv

    train_start = datetime.now(UTC)
    trained_classifier, metrics = train_with_cv(
        embeddings=embeddings,
        labels=labels,
        unlabeled_embeddings=unlabeled_embeddings,
    )
    train_duration_s = (datetime.now(UTC) - train_start).total_seconds()

    logger.info(
        "Training complete for model_id=%s: f1=%.4f, roc_auc=%.4f, "
        "duration=%.1fs",
        str(model.id),
        metrics.get("f1", float("nan")),
        metrics.get("roc_auc", float("nan")),
        train_duration_s,
    )

    # ------------------------------------------------------------------
    # Step 5: Serialize model to S3
    # ------------------------------------------------------------------
    artifact_key = f"models/{project_id}/{model.id}/model.joblib"

    with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp_file:
        tmp_path = Path(tmp_file.name)

    try:
        trained_classifier.save(tmp_path)
        await _upload_model_to_s3(local_path=tmp_path, s3_key=artifact_key)
    finally:
        tmp_path.unlink(missing_ok=True)

    logger.info(
        "Model artifact uploaded to S3: key=%s (model_id=%s)", artifact_key, str(model.id)
    )

    # ------------------------------------------------------------------
    # Step 6: Update DB record with results
    # ------------------------------------------------------------------
    best_c = metrics.pop("best_c", 1.0)
    cv_scores = metrics.pop("cv_scores", {})
    skipped_cv = metrics.pop("skipped_cv", False)

    model.status = CustomModelStatus.TRAINED
    model.metrics = dict(metrics.items())
    model.hyperparameters = {
        "best_c": best_c,
        "cv_scores": {str(k): v for k, v in cv_scores.items()},
        "skipped_cv": skipped_cv,
    }
    model.training_stats = {
        "positive_count": len(positive_rows),
        "negative_count": len(negative_rows),
        "unlabeled_count": int(len(unlabeled_embeddings)) if unlabeled_embeddings is not None else 0,
        "training_duration_s": round(train_duration_s, 2),
    }
    model.model_artifact_key = artifact_key
    model.completed_at = datetime.now(UTC)

    await db.commit()

    return {
        "status": "trained",
        "model_id": str(model.id),
        "artifact_key": artifact_key,
        "metrics": model.metrics,
        "hyperparameters": model.hyperparameters,
        "training_stats": model.training_stats,
    }


async def _fetch_training_embeddings(
    db: AsyncSession,
    session_ids: list[str],
    embedding_model_name: str,
) -> list[dict[str, Any]]:
    """Fetch labeled embeddings for confirmed/rejected annotations in the given sessions.

    Uses a single JOIN query (no N+1) to retrieve annotation status and the
    corresponding Perch embedding vector for each matched time window.
    When multiple embeddings overlap a single annotation, each is returned as
    a separate training sample (maximizes training data).

    Args:
        db: Active async database session.
        session_ids: List of search session UUID strings.
        embedding_model_name: Embedding model name to filter (e.g. "perch").

    Returns:
        List of dicts with keys: annotation_id, embedding_id, label (0 or 1), vector.
    """
    sql = text("""
        SELECT
            a.id         AS annotation_id,
            e.id         AS embedding_id,
            a.status     AS annotation_status,
            e.vector     AS vector
        FROM annotations a
        JOIN embeddings e
            ON  e.recording_id = a.recording_id
            AND e.model_name   = :embedding_model_name
            AND e.start_time   < a.end_time
            AND e.end_time     > a.start_time
        WHERE
            a.search_session_id = ANY(:session_ids)
            AND a.status IN ('confirmed', 'rejected')
    """)

    rows = (
        await db.execute(
            sql,
            {
                "embedding_model_name": embedding_model_name,
                "session_ids": session_ids,
            },
        )
    ).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        # pgvector returns Vector as a list-like object; convert to plain list
        raw_vector = row.vector
        if hasattr(raw_vector, "tolist"):
            vector: list[float] = raw_vector.tolist()
        else:
            vector = list(raw_vector)

        label = 1 if row.annotation_status == "confirmed" else 0
        results.append(
            {
                "annotation_id": str(row.annotation_id),
                "embedding_id": str(row.embedding_id),
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
) -> np.ndarray | None:
    """Fetch random unlabeled embeddings from the project for semi-supervised training.

    Excludes embeddings already used as labeled training samples.

    Args:
        db: Active async database session.
        project_id: Project UUID.
        embedding_model_name: Embedding model name to filter.
        exclude_embedding_ids: List of embedding UUID strings to exclude.
        max_samples: Maximum number of unlabeled samples to return.

    Returns:
        Numpy array of shape (n, embedding_dim) or None if no samples found.
    """
    sql = text("""
        SELECT e.vector
        FROM embeddings e
        JOIN recordings r ON r.id = e.recording_id
        WHERE
            r.project_id = :project_id
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
    for row in rows:
        raw_vector = row.vector
        if hasattr(raw_vector, "tolist"):
            vectors.append(raw_vector.tolist())
        else:
            vectors.append(list(raw_vector))

    return np.array(vectors, dtype=np.float32)


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
