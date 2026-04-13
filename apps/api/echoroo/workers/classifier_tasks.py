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
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)

# Minimum number of positive and negative examples required to start training
_MIN_POSITIVE_SAMPLES = 5
_MIN_NEGATIVE_SAMPLES = 5

# Maximum number of unlabeled embeddings to fetch for semi-supervised training
_MAX_UNLABELED_SAMPLES = 2000


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
    """Train a custom SVM classifier using Perch embeddings from sampling round annotations.

    Reads confirmed/rejected annotations from the model's sampling rounds,
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

    engine, session_factory = get_worker_engine_and_session_factory()
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

            if model.status not in (
                CustomModelStatus.DRAFT,
                CustomModelStatus.FAILED,
                CustomModelStatus.TRAINING,
            ):
                raise ValueError(
                    f"Cannot train model with status '{model.status}'. "
                    "Expected 'draft', 'failed', or 'training'."
                )

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name

            # ------------------------------------------------------------------
            # Mark model as TRAINING
            # ------------------------------------------------------------------
            model.status = CustomModelStatus.TRAINING
            model.started_at = datetime.now(UTC)
            model.error_message = None
            await db.commit()

            logger.info(
                "Starting training for model_id=%s, project_id=%s, "
                "embedding_model=%s",
                model_id,
                project_id,
                embedding_model_name,
            )

            try:
                result_data = await _run_training(
                    db=db,
                    model=model,
                    project_id=project_id,
                    embedding_model_name=embedding_model_name,
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
) -> dict[str, Any]:
    """Core training logic: collect data, train model, upload to S3, update DB.

    Args:
        db: Active async database session.
        model: CustomModel ORM instance (already in TRAINING state).
        project_id: Project UUID.
        embedding_model_name: Name of the embedding model (e.g. "perch").

    Returns:
        Dict with training result summary.
    """
    from echoroo.models.custom_model import CustomModelStatus

    # ------------------------------------------------------------------
    # Step 1: Collect training data via a single batch SQL query
    # Fetches embeddings linked to annotations from all completed sampling rounds
    # ------------------------------------------------------------------
    training_rows = await _fetch_training_embeddings(
        db=db,
        model_id=model.id,
        embedding_model_name=embedding_model_name,
        target_tag_id=model.target_tag_id,
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
    # r["vector"] is already a list[float] from _fetch_training_embeddings(),
    # but we guard against any remaining non-homogeneous shapes by validating
    # vector lengths before passing to np.array().
    raw_vectors = [r["vector"] for r in embeddings_list]
    vector_lengths = {len(v) for v in raw_vectors}
    if len(vector_lengths) != 1:
        raise ValueError(
            f"Inhomogeneous embedding vectors detected: found lengths {vector_lengths}. "
            "All embeddings must have the same dimension."
        )
    embeddings = np.array(raw_vectors, dtype=np.float32)
    labels = np.array(
        [1] * len(positive_rows) + [0] * len(negative_rows), dtype=np.int32
    )
    # Extract recording_ids for each labeled embedding to enable recording-level
    # group CV and unlabeled exclusion from the held-out test recordings.
    recording_ids = np.array([r["recording_id"] for r in embeddings_list])

    # ------------------------------------------------------------------
    # Step 3: Optionally fetch unlabeled embeddings for semi-supervised training
    # ------------------------------------------------------------------
    training_config = model.training_config or {}
    use_unlabeled = bool(training_config.get("use_unlabeled", True))
    max_unlabeled = int(training_config.get("max_unlabeled_samples", 2000))
    unlabeled_embeddings: np.ndarray | None = None
    unlabeled_recording_ids: np.ndarray | None = None

    if use_unlabeled:
        # Collect already-used embedding IDs to exclude them
        labeled_embedding_ids = [r["embedding_id"] for r in embeddings_list]
        unlabeled_result = await _fetch_unlabeled_embeddings(
            db=db,
            project_id=project_id,
            embedding_model_name=embedding_model_name,
            exclude_embedding_ids=labeled_embedding_ids,
            max_samples=max_unlabeled,
        )

        if unlabeled_result is not None:
            unlabeled_embeddings, unlabeled_recording_ids = unlabeled_result

        if unlabeled_embeddings is not None and len(unlabeled_embeddings) > 0:
            from echoroo.ml.classifiers import reduce_unlabeled_samples

            if len(unlabeled_embeddings) > max_unlabeled:
                # Keep the same indices for both embeddings and recording_ids
                reduced = reduce_unlabeled_samples(
                    unlabeled_embeddings, max_samples=max_unlabeled
                )
                # Identify which rows were kept by matching reduced rows back
                # to the original array (reduce_unlabeled_samples returns a
                # subset of the original rows, so we can use index lookup).
                # For simplicity we truncate recording_ids to the same length
                # since reduce_unlabeled_samples preserves row correspondence.
                keep_count = len(reduced)
                unlabeled_embeddings = reduced
                if unlabeled_recording_ids is not None:
                    unlabeled_recording_ids = unlabeled_recording_ids[:keep_count]
            logger.info(
                "Unlabeled samples for semi-supervised training: %d (model_id=%s)",
                len(unlabeled_embeddings),
                str(model.id),
            )
        else:
            unlabeled_embeddings = None
            unlabeled_recording_ids = None
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
        recording_ids=recording_ids,
        unlabeled_recording_ids=unlabeled_recording_ids,
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
            JOIN annotations a
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
            JOIN annotations a
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


# ---------------------------------------------------------------------------
# Custom model inference task
# ---------------------------------------------------------------------------

# Number of embeddings to fetch per batch during inference
_INFERENCE_BATCH_SIZE = 1000

# Number of annotations to accumulate before flushing to DB
_INFERENCE_COMMIT_BATCH = 5000


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.run_custom_model_inference",
    time_limit=3600,
    soft_time_limit=3500,
)
def run_custom_model_inference(
    _self: Any,
    model_id: str,
    detection_run_id: str,
    dataset_id: str,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Apply a trained custom SVM model to all Perch embeddings in a dataset.

    Loads the SVM artifact from S3, fetches all Perch embeddings for the given
    dataset in batches, runs predict_proba(), and creates Annotation records
    for every clip whose probability meets the threshold. The DetectionRun
    status is updated from PENDING -> RUNNING -> COMPLETED (or FAILED).

    Args:
        model_id: UUID string of the CustomModel to apply.
        detection_run_id: UUID string of the DetectionRun to update.
        dataset_id: UUID string of the dataset to run inference on.
        threshold: Minimum confidence score for annotation creation (default: 0.5).

    Returns:
        Dict with inference result summary (status, annotation_count).
    """
    return asyncio.run(
        _run_custom_model_inference(model_id, detection_run_id, dataset_id, threshold)
    )


async def _run_custom_model_inference(
    model_id: str,
    detection_run_id: str,
    dataset_id: str,
    threshold: float,
) -> dict[str, Any]:
    """Async implementation of custom model inference.

    Args:
        model_id: UUID string of the CustomModel.
        detection_run_id: UUID string of the DetectionRun.
        dataset_id: UUID string of the target dataset.
        threshold: Minimum confidence score for annotation creation.

    Returns:
        Dict with inference result summary.
    """
    from sqlalchemy import select

    from echoroo.models.custom_model import CustomModel, CustomModelStatus
    from echoroo.models.enums import DetectionRunStatus, DetectionSource, DetectionStatus
    from echoroo.repositories.detection_run import DetectionRunRepository

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        # ------------------------------------------------------------------
        # Step 1: Mark DetectionRun as RUNNING
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            detection_run = await run_repo.get_by_id(UUID(detection_run_id))
            if detection_run is None:
                raise ValueError(f"DetectionRun not found: {detection_run_id}")

            detection_run.status = DetectionRunStatus.RUNNING
            detection_run.started_at = datetime.now(UTC)
            await db.commit()

        logger.info(
            "Starting custom SVM inference: model_id=%s, detection_run_id=%s, "
            "dataset_id=%s, threshold=%.3f",
            model_id,
            detection_run_id,
            dataset_id,
            threshold,
        )

        try:
            # ------------------------------------------------------------------
            # Step 2: Load CustomModel and its artifact key from DB
            # ------------------------------------------------------------------
            async with session_factory() as db:
                result = await db.execute(
                    select(CustomModel).where(CustomModel.id == UUID(model_id))
                )
                custom_model = result.scalar_one_or_none()

            if custom_model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            if custom_model.status not in (
                CustomModelStatus.TRAINED,
                CustomModelStatus.DEPLOYED,
            ):
                raise ValueError(
                    f"CustomModel {model_id} has status '{custom_model.status}'; "
                    "expected 'trained' or 'deployed'."
                )

            artifact_key = custom_model.model_artifact_key
            if not artifact_key:
                raise ValueError(f"CustomModel {model_id} has no model artifact key.")

            target_tag_id = custom_model.target_tag_id
            embedding_model_name = custom_model.embedding_model_name

            # ------------------------------------------------------------------
            # Step 3: Download model artifact from S3 and load classifier
            # ------------------------------------------------------------------
            from echoroo.ml.classifiers import UnifiedClassifier

            with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp_file:
                tmp_path = Path(tmp_file.name)

            try:
                await _download_model_from_s3(artifact_key, tmp_path)
                classifier = UnifiedClassifier.load(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            logger.info(
                "Loaded classifier from S3 artifact: key=%s (model_id=%s)",
                artifact_key,
                model_id,
            )

            # ------------------------------------------------------------------
            # Step 4: Fetch Perch embeddings for the dataset in batches and
            #         run predict_proba(), creating annotations above threshold
            # ------------------------------------------------------------------
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.engine import CursorResult

            from echoroo.models.annotation import Annotation

            total_embeddings = 0
            total_annotations = 0
            offset = 0
            now = datetime.now(UTC)

            while True:
                sql = text("""
                    SELECT
                        e.id         AS embedding_id,
                        e.recording_id,
                        e.start_time,
                        e.end_time,
                        e.vector
                    FROM embeddings e
                    JOIN recordings r ON r.id = e.recording_id
                    WHERE
                        r.dataset_id  = :dataset_id
                        AND e.model_name = :embedding_model_name
                    ORDER BY e.recording_id, e.start_time
                    LIMIT :limit OFFSET :offset
                """)

                async with session_factory() as db:
                    rows = (
                        await db.execute(
                            sql,
                            {
                                "dataset_id": dataset_id,
                                "embedding_model_name": embedding_model_name,
                                "limit": _INFERENCE_BATCH_SIZE,
                                "offset": offset,
                            },
                        )
                    ).fetchall()

                if not rows:
                    break

                # Parse vectors (asyncpg may return as string)
                import json

                batch_meta: list[tuple[Any, Any, float, float]] = []
                batch_vectors: list[list[float]] = []

                for row in rows:
                    raw_vector = row.vector
                    if isinstance(raw_vector, str):
                        vec: list[float] = [float(x) for x in json.loads(raw_vector)]
                    elif hasattr(raw_vector, "tolist"):
                        vec = [float(x) for x in raw_vector.tolist()]
                    elif hasattr(raw_vector, "__iter__"):
                        vec = [float(x) for x in raw_vector]
                    else:
                        raise ValueError(
                            f"Unexpected vector type {type(raw_vector)} for "
                            f"embedding_id={row.embedding_id}"
                        )

                    batch_meta.append(
                        (row.embedding_id, row.recording_id, row.start_time, row.end_time)
                    )
                    batch_vectors.append(vec)

                # Run SVM inference on the batch
                embeddings_array = np.array(batch_vectors, dtype=np.float32)
                probabilities = classifier.predict_proba(embeddings_array)

                pending_annotation_dicts: list[dict[str, Any]] = []
                for (_embedding_id, recording_id, start_time, end_time), prob in zip(
                    batch_meta, probabilities, strict=False
                ):
                    if prob >= threshold:
                        pending_annotation_dicts.append(
                            {
                                "id": uuid4(),
                                "recording_id": recording_id,
                                "tag_id": target_tag_id,
                                "detection_run_id": UUID(detection_run_id),
                                "source": DetectionSource.CUSTOM_SVM,
                                "status": DetectionStatus.UNREVIEWED,
                                "confidence": float(prob),
                                "start_time": start_time,
                                "end_time": end_time,
                                "created_at": now,
                                "updated_at": now,
                            }
                        )

                total_embeddings += len(rows)

                # Bulk insert accumulated annotations when the buffer is large enough
                if len(pending_annotation_dicts) >= _INFERENCE_COMMIT_BATCH:
                    async with session_factory() as db:
                        stmt = (
                            pg_insert(Annotation)
                            .values(pending_annotation_dicts)
                            .on_conflict_do_nothing()
                        )
                        cursor: CursorResult[tuple[()]] = await db.execute(stmt)  # type: ignore[assignment]
                        inserted = cursor.rowcount
                        await db.commit()

                    total_annotations += inserted
                    pending_annotation_dicts = []

                    logger.info(
                        "Inference progress: embeddings_processed=%d, annotations=%d "
                        "(detection_run_id=%s)",
                        total_embeddings,
                        total_annotations,
                        detection_run_id,
                    )

                    # Persist progress to DetectionRun
                    async with session_factory() as db:
                        run_repo = DetectionRunRepository(db)
                        run = await run_repo.get_by_id(UUID(detection_run_id))
                        if run is not None:
                            run.annotation_count = total_annotations
                            await db.commit()

                elif pending_annotation_dicts:
                    # Flush smaller batch at end of loop iteration
                    async with session_factory() as db:
                        stmt = (
                            pg_insert(Annotation)
                            .values(pending_annotation_dicts)
                            .on_conflict_do_nothing()
                        )
                        cursor = await db.execute(stmt)  # type: ignore[assignment]
                        inserted = cursor.rowcount
                        await db.commit()

                    total_annotations += inserted

                offset += len(rows)

                # Stop if we received fewer rows than the batch size
                if len(rows) < _INFERENCE_BATCH_SIZE:
                    break

            # ------------------------------------------------------------------
            # Step 5: Mark DetectionRun as COMPLETED
            # ------------------------------------------------------------------
            async with session_factory() as db:
                run_repo = DetectionRunRepository(db)
                run = await run_repo.get_by_id(UUID(detection_run_id))
                if run is not None:
                    run.status = DetectionRunStatus.COMPLETED
                    run.annotation_count = total_annotations
                    run.completed_at = datetime.now(UTC)
                    await db.commit()

            logger.info(
                "Custom SVM inference complete: model_id=%s, detection_run_id=%s, "
                "embeddings_processed=%d, annotations_created=%d",
                model_id,
                detection_run_id,
                total_embeddings,
                total_annotations,
            )

            return {
                "status": "completed",
                "detection_run_id": detection_run_id,
                "embeddings_processed": total_embeddings,
                "annotation_count": total_annotations,
            }

        except Exception as exc:
            # Mark DetectionRun as FAILED and persist error message
            logger.exception(
                "Custom SVM inference failed: model_id=%s, detection_run_id=%s",
                model_id,
                detection_run_id,
            )
            async with session_factory() as db:
                run_repo = DetectionRunRepository(db)
                run = await run_repo.get_by_id(UUID(detection_run_id))
                if run is not None:
                    run.status = DetectionRunStatus.FAILED
                    run.error_message = str(exc)
                    run.completed_at = datetime.now(UTC)
                    try:
                        await db.commit()
                    except Exception:
                        logger.exception(
                            "Failed to persist FAILED status for detection_run_id=%s",
                            detection_run_id,
                        )
            raise

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Seed sampling task
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.generate_seed_samples",
    time_limit=600,
    soft_time_limit=540,
)
def generate_seed_samples(_self: Any, model_id: str, round_id: str) -> dict[str, Any]:
    """Generate three-category seed samples for a custom model.

    Fetches reference embedding vectors stored in training_config, queries
    candidate embeddings from the project's pgvector store, runs the
    farthest-first seed sampling algorithm, and creates Annotation +
    SamplingRoundItem records in the database.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the SamplingRound record (already in 'pending' status).

    Returns:
        Dict with sampling result summary (status, sample_count).
    """
    return asyncio.run(_generate_seed_samples(model_id, round_id))


async def _generate_seed_samples(model_id: str, round_id: str) -> dict[str, Any]:
    """Async implementation of seed sample generation.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the SamplingRound record.

    Returns:
        Dict with sampling result summary.
    """
    from echoroo.models.custom_model import CustomModel, CustomModelStatus

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            # ------------------------------------------------------------------
            # Step 1: Fetch and validate the CustomModel record
            # ------------------------------------------------------------------
            result = await db.execute(
                select(CustomModel).where(CustomModel.id == UUID(model_id))
            )
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            if model.status not in (
                CustomModelStatus.DRAFT,
                CustomModelStatus.FAILED,
            ):
                raise ValueError(
                    f"Cannot generate seed samples for model with status '{model.status}'. "
                    "Expected 'draft' or 'failed'."
                )

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name
            target_tag_id = model.target_tag_id
            search_session_id = model.search_session_id
            dataset_id = model.dataset_id

            # ------------------------------------------------------------------
            # Step 2: Mark the SamplingRound as running
            # ------------------------------------------------------------------
            from echoroo.repositories.sampling_round import SamplingRoundRepository  # noqa: PLC0415

            round_repo = SamplingRoundRepository(db)
            round_ = await round_repo.get_round(UUID(round_id))
            if round_ is None:
                raise ValueError(f"SamplingRound not found: {round_id}")

            round_.status = "running"
            await db.flush()

            # ------------------------------------------------------------------
            # Step 3: Fetch reference (query) vectors
            # When search_session_id is set, load vectors from search_query_embeddings.
            # Otherwise fall back to the reference_embedding_ids stored in training_config.
            # ------------------------------------------------------------------
            training_config: dict[str, Any] = model.training_config or {}

            if search_session_id is not None:
                ref_sql = text("""
                    SELECT id, vector
                    FROM search_query_embeddings
                    WHERE search_session_id = :session_id
                      AND species_key = :species_key
                """)
                species_key = str(target_tag_id)
                ref_rows = (
                    await db.execute(
                        ref_sql,
                        {"session_id": str(search_session_id), "species_key": species_key},
                    )
                ).fetchall()

                if not ref_rows:
                    raise ValueError(
                        f"No query embeddings found for search_session_id={search_session_id}, "
                        f"species_key={species_key}"
                    )

                logger.info(
                    "Fetching %d query embeddings from search_query_embeddings for model_id=%s",
                    len(ref_rows),
                    model_id,
                )
            else:
                reference_embedding_ids: list[str] = training_config.get(
                    "reference_embedding_ids", []
                )

                if not reference_embedding_ids:
                    raise ValueError(
                        "No reference_embedding_ids found in model.training_config. "
                        "Set reference_embedding_ids before dispatching seed sampling."
                    )

                logger.info(
                    "Fetching %d reference embeddings for model_id=%s",
                    len(reference_embedding_ids),
                    model_id,
                )

                ref_sql = text("""
                    SELECT id, vector
                    FROM embeddings
                    WHERE id = ANY(:embedding_ids)
                      AND model_name = :embedding_model_name
                """)
                ref_rows = (
                    await db.execute(
                        ref_sql,
                        {
                            "embedding_ids": reference_embedding_ids,
                            "embedding_model_name": embedding_model_name,
                        },
                    )
                ).fetchall()

                if not ref_rows:
                    raise ValueError(
                        f"No reference embeddings found for IDs: {reference_embedding_ids}"
                    )

            query_vectors = _parse_vectors([r.vector for r in ref_rows])

            # ------------------------------------------------------------------
            # Step 4: Fetch candidate embeddings
            # ------------------------------------------------------------------
            sampling_config_data: dict[str, Any] = training_config.get(
                "sampling_config", {}
            )
            from echoroo.ml.sampling import SeedSamplingConfig  # noqa: PLC0415

            config = SeedSamplingConfig(
                easy_positive_k=sampling_config_data.get("easy_positive_k", 5),
                boundary_n=sampling_config_data.get("boundary_n", 200),
                boundary_m=sampling_config_data.get("boundary_m", 10),
                others_p=sampling_config_data.get("others_p", 20),
            )

            # Fetch near candidates for easy_positive + boundary: top 205 by similarity
            # We use a single query vector's average as the ordering proxy when multiple
            # query vectors are given.
            top_limit = config.easy_positive_k + config.boundary_n + 5  # small buffer
            avg_query = query_vectors.mean(axis=0).tolist()

            # Build exclude list: ref_rows always have an id column regardless of source
            exclude_ids_for_near: list[str] = [str(r.id) for r in ref_rows]
            dataset_id_param: str | None = str(dataset_id) if dataset_id is not None else None

            near_sql = text("""
                SELECT e.id, e.vector, e.recording_id, e.start_time, e.end_time
                FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d ON r.dataset_id = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name = :embedding_model_name
                  AND NOT (e.id = ANY(:exclude_ids))
                  AND (CAST(:dataset_id AS uuid) IS NULL OR d.id = CAST(:dataset_id AS uuid))
                ORDER BY e.vector <=> :query_vector
                LIMIT :limit
            """)

            near_rows = (
                await db.execute(
                    near_sql,
                    {
                        "project_id": str(project_id),
                        "embedding_model_name": embedding_model_name,
                        "exclude_ids": exclude_ids_for_near,
                        "dataset_id": dataset_id_param,
                        "query_vector": str(avg_query),
                        "limit": top_limit,
                    },
                )
            ).fetchall()

            # Fetch "others" via TABLESAMPLE for diversity
            # Estimate Bernoulli sample percentage to get ~1000 rows
            count_sql = text("""
                SELECT COUNT(*) FROM embeddings e
                JOIN recordings r ON e.recording_id = r.id
                JOIN datasets d ON r.dataset_id = d.id
                WHERE d.project_id = :project_id
                  AND e.model_name = :embedding_model_name
                  AND (CAST(:dataset_id AS uuid) IS NULL OR d.id = CAST(:dataset_id AS uuid))
            """)
            total_count_result = await db.execute(
                count_sql,
                {
                    "project_id": str(project_id),
                    "embedding_model_name": embedding_model_name,
                    "dataset_id": dataset_id_param,
                },
            )
            total_count = total_count_result.scalar() or 0

            near_row_ids = [str(r.id) for r in near_rows]
            all_exclude_ids = exclude_ids_for_near + near_row_ids

            if total_count > 0:
                # Target ~1000 rows for "others" pool
                target_others = 1000
                bernoulli_pct = min(100.0, (target_others / total_count) * 100.0)
                bernoulli_pct = max(0.01, bernoulli_pct)

                others_sql = text("""
                    SELECT e.id, e.vector, e.recording_id, e.start_time, e.end_time
                    FROM embeddings e TABLESAMPLE BERNOULLI(:pct)
                    JOIN recordings r ON e.recording_id = r.id
                    JOIN datasets d ON r.dataset_id = d.id
                    WHERE d.project_id = :project_id
                      AND e.model_name = :embedding_model_name
                      AND NOT (e.id = ANY(:exclude_ids))
                      AND (CAST(:dataset_id AS uuid) IS NULL OR d.id = CAST(:dataset_id AS uuid))
                    LIMIT 1000
                """)
                others_rows = (
                    await db.execute(
                        others_sql,
                        {
                            "pct": bernoulli_pct,
                            "project_id": str(project_id),
                            "embedding_model_name": embedding_model_name,
                            "exclude_ids": all_exclude_ids,
                            "dataset_id": dataset_id_param,
                        },
                    )
                ).fetchall()
            else:
                others_rows = []

            # Merge candidate rows (near + others, deduplicated by id)
            seen_ids: set[str] = set()
            all_rows = []
            for r in list(near_rows) + list(others_rows):
                rid = str(r.id)
                if rid not in seen_ids:
                    seen_ids.add(rid)
                    all_rows.append(r)

            if not all_rows:
                raise ValueError(
                    f"No candidate embeddings found for project_id={project_id} "
                    f"with embedding_model={embedding_model_name}"
                )

            logger.info(
                "Candidate pool: near=%d, others=%d, total=%d (model_id=%s)",
                len(near_rows),
                len(others_rows),
                len(all_rows),
                model_id,
            )

            # ------------------------------------------------------------------
            # Step 5: Run compute_seed_samples
            # ------------------------------------------------------------------
            import numpy as np  # noqa: PLC0415

            from echoroo.ml.sampling import compute_seed_samples  # noqa: PLC0415

            candidate_ids = np.array([str(r.id) for r in all_rows])
            candidate_recording_ids = np.array([str(r.recording_id) for r in all_rows])
            candidate_vectors = _parse_vectors([r.vector for r in all_rows])

            samples = compute_seed_samples(
                query_vectors=query_vectors,
                candidate_ids=candidate_ids,
                candidate_vectors=candidate_vectors,
                candidate_recording_ids=candidate_recording_ids,
                config=config,
            )

            logger.info(
                "Seed sampling complete: %d samples selected (model_id=%s)",
                len(samples),
                model_id,
            )

            # ------------------------------------------------------------------
            # Step 6: Build a lookup map from embedding_id -> row metadata
            # ------------------------------------------------------------------
            row_map = {str(r.id): r for r in all_rows}

            # ------------------------------------------------------------------
            # Step 7: Create Annotation records + SamplingRoundItem records
            # ------------------------------------------------------------------
            from echoroo.models.annotation import Annotation  # noqa: PLC0415
            from echoroo.models.enums import DetectionSource, DetectionStatus  # noqa: PLC0415

            now = datetime.now(UTC)
            item_dicts: list[dict[str, Any]] = []

            for sample in samples:
                row = row_map[sample.embedding_id]
                annotation = Annotation(
                    recording_id=UUID(sample.recording_id),
                    tag_id=target_tag_id,
                    source=DetectionSource.SAMPLING_ROUND,
                    status=DetectionStatus.UNREVIEWED,
                    start_time=float(row.start_time),
                    end_time=float(row.end_time),
                    created_at=now,
                    updated_at=now,
                )
                db.add(annotation)
                await db.flush()
                await db.refresh(annotation)

                item_dicts.append(
                    {
                        "embedding_id": UUID(sample.embedding_id),
                        "sample_type": sample.sample_type,
                        "annotation_id": annotation.id,
                        "similarity": sample.similarity,
                    }
                )

            # Bulk insert SamplingRoundItems
            await round_repo.add_items(UUID(round_id), item_dicts)

            # ------------------------------------------------------------------
            # Step 8: Update round status to completed
            # ------------------------------------------------------------------
            await round_repo.update_round_status(
                round_id=UUID(round_id),
                status="completed",
                sample_count=len(samples),
            )

            await db.commit()

            logger.info(
                "Seed sampling round completed: round_id=%s, model_id=%s, "
                "sample_count=%d",
                round_id,
                model_id,
                len(samples),
            )

            return {
                "status": "completed",
                "model_id": model_id,
                "round_id": round_id,
                "sample_count": len(samples),
            }

    except Exception as exc:
        logger.exception(
            "Seed sampling failed: model_id=%s, round_id=%s", model_id, round_id
        )
        # Mark sampling round as failed
        try:
            engine2, session_factory2 = get_worker_engine_and_session_factory()
            try:
                async with session_factory2() as db2:
                    from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                        SamplingRoundRepository,
                    )

                    repo2 = SamplingRoundRepository(db2)
                    await repo2.update_round_status(
                        round_id=UUID(round_id),
                        status="failed",
                        error_message=str(exc),
                    )
                    await db2.commit()
            finally:
                await engine2.dispose()
        except Exception:
            logger.exception(
                "Failed to persist FAILED status for round_id=%s", round_id
            )
        raise

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Active learning iteration task
# ---------------------------------------------------------------------------

# Batch size for fetching project embeddings during active learning scoring
_AL_SCORING_BATCH_SIZE = 5000

# Number of uncertain candidates to maintain in the margin tracker
_AL_MARGIN_TRACKER_K = 60

# Number of final AL samples to select
_AL_SAMPLE_COUNT = 20


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.run_al_iteration",
    time_limit=600,
    soft_time_limit=540,
    max_retries=1,
)
def run_al_iteration(_self: Any, model_id: str, round_id: str) -> dict[str, Any]:
    """Run one active learning iteration for a custom model.

    Trains a lightweight SVM on labeled data from completed sampling rounds,
    scores all unlabeled project embeddings to find the most uncertain ones,
    and populates the pre-created SamplingRound (round_id) with
    SamplingRoundItem records for human review.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the SamplingRound record (already in 'pending' status).

    Returns:
        Dict with AL iteration result summary (status, round_id, sample_count).
    """
    return asyncio.run(_run_al_iteration(model_id, round_id))


async def _run_al_iteration(model_id: str, round_id: str) -> dict[str, Any]:
    """Async implementation of active learning iteration.

    Args:
        model_id: UUID string of the CustomModel record.
        round_id: UUID string of the pre-created SamplingRound (status='pending').

    Returns:
        Dict with AL iteration result summary.
    """
    from echoroo.models.custom_model import CustomModel

    engine, session_factory = get_worker_engine_and_session_factory()

    # Use the round_id passed in from the API (pre-created pending round)
    round_id_str: str = round_id

    try:
        # ------------------------------------------------------------------
        # Step 1: Fetch and validate the CustomModel record
        # ------------------------------------------------------------------
        async with session_factory() as db:
            result = await db.execute(
                select(CustomModel).where(CustomModel.id == UUID(model_id))
            )
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name
            target_tag_id = model.target_tag_id

        logger.info(
            "Starting AL iteration: model_id=%s, project_id=%s, "
            "embedding_model=%s",
            model_id,
            project_id,
            embedding_model_name,
        )

        # ------------------------------------------------------------------
        # Step 2: Fetch labeled training data from completed sampling rounds
        # ------------------------------------------------------------------
        async with session_factory() as db:
            training_rows = await _fetch_training_embeddings(
                db=db,
                model_id=UUID(model_id),
                embedding_model_name=embedding_model_name,
                target_tag_id=target_tag_id,
            )

        positive_rows = [r for r in training_rows if r["label"] == 1]
        negative_rows = [r for r in training_rows if r["label"] == 0]

        logger.info(
            "AL training data: positive=%d, negative=%d (model_id=%s)",
            len(positive_rows),
            len(negative_rows),
            model_id,
        )

        if len(positive_rows) < _MIN_POSITIVE_SAMPLES:
            raise ValueError(
                f"Insufficient positive examples for AL: {len(positive_rows)} "
                f"(minimum {_MIN_POSITIVE_SAMPLES} required)."
            )
        if len(negative_rows) < _MIN_NEGATIVE_SAMPLES:
            raise ValueError(
                f"Insufficient negative examples for AL: {len(negative_rows)} "
                f"(minimum {_MIN_NEGATIVE_SAMPLES} required)."
            )

        # ------------------------------------------------------------------
        # Step 3: Build labeled arrays and train lightweight SVM (no CV)
        # ------------------------------------------------------------------
        from sklearn.svm import SVC  # noqa: PLC0415

        from echoroo.ml.classifiers import UnifiedClassifier  # noqa: PLC0415

        embeddings_list = positive_rows + negative_rows
        raw_vectors = [r["vector"] for r in embeddings_list]
        vector_lengths = {len(v) for v in raw_vectors}
        if len(vector_lengths) != 1:
            raise ValueError(
                f"Inhomogeneous embedding vectors detected: found lengths {vector_lengths}."
            )

        embeddings_array = np.array(raw_vectors, dtype=np.float32)
        labels_array = np.array(
            [1] * len(positive_rows) + [0] * len(negative_rows), dtype=np.int32
        )
        labeled_vectors = embeddings_array  # keep reference for diversity seeds

        # Train a fast linear SVM directly (skip self-training and CV)
        from sklearn.pipeline import Pipeline  # noqa: PLC0415
        from sklearn.preprocessing import Normalizer  # noqa: PLC0415

        svm = SVC(kernel="linear", C=1.0, probability=False)
        pipeline = Pipeline([
            ("normalizer", Normalizer(norm="l2")),
            ("classifier", svm),
        ])
        pipeline.fit(embeddings_array, labels_array)

        # Wrap in UnifiedClassifier so decision_function() works correctly
        classifier = UnifiedClassifier.__new__(UnifiedClassifier)
        from echoroo.ml.classifiers import ClassifierType  # noqa: PLC0415
        classifier.classifier_type = ClassifierType.SELF_TRAINING_SVM
        classifier.model = pipeline
        classifier.is_fitted = True
        classifier._single_class = None

        logger.info(
            "Lightweight SVM trained on %d samples (model_id=%s)",
            len(embeddings_array),
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 4: Collect excluded embedding IDs (cross-round dedup + audit set)
        # ------------------------------------------------------------------
        async with session_factory() as db:
            from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                SamplingRoundRepository,
            )

            round_repo = SamplingRoundRepository(db)
            existing_embedding_ids = await round_repo.get_existing_embedding_ids(
                UUID(model_id)
            )

        # Convert to string list for SQL exclusion
        exclude_ids = [str(eid) for eid in existing_embedding_ids]

        logger.info(
            "Excluding %d already-sampled embedding IDs (model_id=%s)",
            len(exclude_ids),
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 5: Score project embeddings in chunks, feed into MarginTracker
        # ------------------------------------------------------------------
        from echoroo.ml.active_learning import MarginTracker, select_al_samples  # noqa: PLC0415

        tracker = MarginTracker(k=_AL_MARGIN_TRACKER_K)
        offset = 0
        total_scored = 0

        while True:
            chunk_sql = text("""
                SELECT e.id, e.vector
                FROM embeddings e
                JOIN recordings r ON r.id = e.recording_id
                JOIN datasets d ON d.id = r.dataset_id
                WHERE
                    d.project_id = :project_id
                    AND e.model_name = :embedding_model_name
                    AND NOT (e.id = ANY(:exclude_ids))
                ORDER BY e.id
                LIMIT :limit OFFSET :offset
            """)

            async with session_factory() as db:
                rows = (
                    await db.execute(
                        chunk_sql,
                        {
                            "project_id": str(project_id),
                            "embedding_model_name": embedding_model_name,
                            "exclude_ids": exclude_ids,
                            "limit": _AL_SCORING_BATCH_SIZE,
                            "offset": offset,
                        },
                    )
                ).fetchall()

            if not rows:
                break

            chunk_ids = [str(r.id) for r in rows]
            chunk_vectors = _parse_vectors([r.vector for r in rows])
            chunk_distances = classifier.decision_function(chunk_vectors)

            tracker.update(
                ids=chunk_ids,
                distances=chunk_distances,
                vectors=chunk_vectors,
            )

            total_scored += len(rows)
            offset += len(rows)

            if len(rows) < _AL_SCORING_BATCH_SIZE:
                break

        logger.info(
            "AL scoring complete: %d embeddings scored (model_id=%s)",
            total_scored,
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 6: Select diverse uncertain samples
        # ------------------------------------------------------------------
        candidate_ids, candidate_distances, candidate_vectors = tracker.get()

        al_samples = select_al_samples(
            candidate_ids=candidate_ids,
            candidate_distances=candidate_distances,
            candidate_vectors=candidate_vectors,
            labeled_vectors=labeled_vectors,
            n_samples=_AL_SAMPLE_COUNT,
        )

        logger.info(
            "AL sample selection: %d candidates -> %d selected (model_id=%s)",
            len(candidate_ids),
            len(al_samples),
            model_id,
        )

        if not al_samples:
            raise ValueError(
                "No active learning candidates found. "
                "Ensure the project has unlabeled embeddings not yet sampled."
            )

        # ------------------------------------------------------------------
        # Step 7: Fetch embedding metadata (recording_id, start_time, end_time)
        # for the selected AL sample IDs
        # ------------------------------------------------------------------
        al_sample_ids = [s.embedding_id for s in al_samples]

        meta_sql = text("""
            SELECT e.id, e.recording_id, e.start_time, e.end_time
            FROM embeddings e
            WHERE e.id = ANY(:embedding_ids)
        """)

        async with session_factory() as db:
            meta_rows = (
                await db.execute(
                    meta_sql,
                    {"embedding_ids": al_sample_ids},
                )
            ).fetchall()

        meta_map = {str(r.id): r for r in meta_rows}

        # ------------------------------------------------------------------
        # Step 8: Load pre-created round, mark it running, then insert items
        # ------------------------------------------------------------------
        from echoroo.models.annotation import Annotation  # noqa: PLC0415
        from echoroo.models.enums import DetectionSource, DetectionStatus  # noqa: PLC0415

        async with session_factory() as db:
            from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                SamplingRoundRepository,
            )

            round_repo = SamplingRoundRepository(db)

            # Load the pre-created pending round and transition to running
            round_ = await round_repo.get_round(UUID(round_id_str))
            if round_ is None:
                raise ValueError(f"SamplingRound not found: {round_id_str}")

            round_number = round_.round_number
            round_.status = "running"
            await db.flush()

            now = datetime.now(UTC)
            item_dicts: list[dict[str, Any]] = []

            for sample in al_samples:
                meta = meta_map.get(sample.embedding_id)
                if meta is None:
                    logger.warning(
                        "Missing metadata for AL embedding_id=%s, skipping",
                        sample.embedding_id,
                    )
                    continue

                annotation = Annotation(
                    recording_id=meta.recording_id,
                    tag_id=target_tag_id,
                    source=DetectionSource.SAMPLING_ROUND,
                    status=DetectionStatus.UNREVIEWED,
                    start_time=float(meta.start_time),
                    end_time=float(meta.end_time),
                    created_at=now,
                    updated_at=now,
                )
                db.add(annotation)
                await db.flush()
                await db.refresh(annotation)

                item_dicts.append(
                    {
                        "embedding_id": UUID(sample.embedding_id),
                        "sample_type": "active_learning",
                        "annotation_id": annotation.id,
                        "similarity": None,
                        "decision_distance": sample.decision_distance,
                    }
                )

            await round_repo.add_items(UUID(round_id_str), item_dicts)
            await round_repo.update_round_status(
                round_id=UUID(round_id_str),
                status="completed",
                sample_count=len(item_dicts),
            )

            await db.commit()

        logger.info(
            "AL iteration completed: model_id=%s, round_id=%s, "
            "round_number=%d, sample_count=%d",
            model_id,
            round_id_str,
            round_number,
            len(item_dicts),
        )

        return {
            "status": "completed",
            "model_id": model_id,
            "round_id": round_id_str,
            "round_number": round_number,
            "sample_count": len(item_dicts),
        }

    except Exception as exc:
        logger.exception(
            "AL iteration failed: model_id=%s, round_id=%s", model_id, round_id_str
        )
        # Mark the pre-created sampling round as failed
        try:
            engine2, session_factory2 = get_worker_engine_and_session_factory()
            try:
                async with session_factory2() as db2:
                    from echoroo.repositories.sampling_round import (  # noqa: PLC0415
                        SamplingRoundRepository,
                    )

                    repo2 = SamplingRoundRepository(db2)
                    await repo2.update_round_status(
                        round_id=UUID(round_id_str),
                        status="failed",
                        error_message=str(exc),
                    )
                    await db2.commit()
            finally:
                await engine2.dispose()
        except Exception:
            logger.exception(
                "Failed to persist FAILED status for AL round_id=%s", round_id_str
            )
        raise

    finally:
        await engine.dispose()


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


# ---------------------------------------------------------------------------
# Audit set generation task
# ---------------------------------------------------------------------------

# Batch size for fetching project embeddings during audit set scoring
_AUDIT_SCORING_BATCH_SIZE = 5000


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.classifier_tasks.generate_audit_set",
    time_limit=600,
    soft_time_limit=540,
    max_retries=1,
)
def generate_audit_set(_self: Any, model_id: str) -> dict[str, Any]:
    """Generate a score-stratified audit set for a trained custom model.

    Loads the trained classifier from S3, scores all project embeddings
    (excluding those already in sampling rounds and previous audit items),
    applies score-stratified sampling to select representative audit
    candidates, and creates Annotation + AuditSetItem records for human review.

    Args:
        model_id: UUID string of the CustomModel record (must be TRAINED).

    Returns:
        Dict with summary: model_id, audit_item_count.
    """
    return asyncio.run(_generate_audit_set(model_id))


async def _generate_audit_set(model_id: str) -> dict[str, Any]:
    """Async implementation of audit set generation.

    Args:
        model_id: UUID string of the CustomModel record.

    Returns:
        Dict with summary keys: model_id, audit_item_count.
    """
    from echoroo.models.custom_model import CustomModel, CustomModelStatus

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            # ------------------------------------------------------------------
            # Step 1: Fetch and validate the CustomModel
            # ------------------------------------------------------------------
            result = await db.execute(
                select(CustomModel).where(CustomModel.id == UUID(model_id))
            )
            model = result.scalar_one_or_none()

            if model is None:
                raise ValueError(f"CustomModel not found: {model_id}")

            if model.status != CustomModelStatus.TRAINED:
                raise ValueError(
                    f"Cannot generate audit set for model with status '{model.status}'. "
                    "Only TRAINED models are supported."
                )

            if not model.model_artifact_key:
                raise ValueError(
                    f"CustomModel {model_id} has no model artifact key. "
                    "Train the model before generating an audit set."
                )

            project_id = model.project_id
            embedding_model_name = model.embedding_model_name
            target_tag_id = model.target_tag_id
            artifact_key = model.model_artifact_key

        logger.info(
            "Starting audit set generation: model_id=%s, project_id=%s",
            model_id,
            project_id,
        )

        # ------------------------------------------------------------------
        # Step 2: Load classifier artifact from S3
        # ------------------------------------------------------------------
        from echoroo.ml.classifiers import UnifiedClassifier  # noqa: PLC0415

        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

        try:
            await _download_model_from_s3(artifact_key, tmp_path)
            classifier = UnifiedClassifier.load(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        logger.info(
            "Loaded classifier from S3 for audit set generation: key=%s (model_id=%s)",
            artifact_key,
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 3: Collect exclude set
        #   - sampling_round_items.embedding_id for this model
        #   - existing audit_set_items.embedding_id for this model
        # ------------------------------------------------------------------
        exclude_sql = text("""
            SELECT DISTINCT sri.embedding_id
            FROM sampling_round_items sri
            JOIN sampling_rounds sr ON sr.id = sri.sampling_round_id
            WHERE sr.custom_model_id = :model_id
            UNION
            SELECT embedding_id
            FROM audit_set_items
            WHERE custom_model_id = :model_id
        """)

        async with session_factory() as db:
            exclude_rows = (
                await db.execute(exclude_sql, {"model_id": model_id})
            ).fetchall()

        exclude_ids: set[str] = {str(row[0]) for row in exclude_rows}

        logger.info(
            "Audit set exclude set: %d embedding IDs (model_id=%s)",
            len(exclude_ids),
            model_id,
        )

        # ------------------------------------------------------------------
        # Step 4+5: Fetch embeddings in chunks, score each chunk immediately,
        # and accumulate only (id, recording_id, proba) lightweight tuples.
        # Raw vectors are freed after each chunk so peak memory stays at
        # _AUDIT_SCORING_BATCH_SIZE × D × 4 bytes (≈30 MB for 5000 × 1536).
        # ------------------------------------------------------------------
        from echoroo.ml.evaluation import AuditSample  # noqa: PLC0415

        # scored_items collects lightweight tuples — no raw vectors kept.
        scored_items: list[tuple[str, str, float]] = []  # (embedding_id, recording_id, proba)
        offset = 0
        total_scored = 0

        chunk_sql = text("""
            SELECT e.id, e.recording_id, e.vector
            FROM embeddings e
            JOIN recordings r ON r.id = e.recording_id
            JOIN datasets d ON d.id = r.dataset_id
            WHERE
                d.project_id = :project_id
                AND e.model_name = :embedding_model_name
            ORDER BY e.id
            LIMIT :limit OFFSET :offset
        """)

        while True:
            async with session_factory() as db:
                rows = (
                    await db.execute(
                        chunk_sql,
                        {
                            "project_id": str(project_id),
                            "embedding_model_name": embedding_model_name,
                            "limit": _AUDIT_SCORING_BATCH_SIZE,
                            "offset": offset,
                        },
                    )
                ).fetchall()

            if not rows:
                break

            # Filter excluded IDs before building the vector array.
            candidate_rows = [r for r in rows if str(r.id) not in exclude_ids]

            if candidate_rows:
                chunk_vectors = _parse_vectors([r.vector for r in candidate_rows])
                chunk_probas: np.ndarray = classifier.predict_proba(chunk_vectors)
                del chunk_vectors  # free ~30 MB chunk buffer immediately

                for row, proba in zip(candidate_rows, chunk_probas.tolist(), strict=False):
                    scored_items.append((str(row.id), str(row.recording_id), float(proba)))

            total_scored += len(rows)
            offset += len(rows)
            if len(rows) < _AUDIT_SCORING_BATCH_SIZE:
                break

        logger.info(
            "Audit set scoring complete: %d total rows scanned, %d candidates (model_id=%s)",
            total_scored,
            len(scored_items),
            model_id,
        )

        if not scored_items:
            logger.warning(
                "No candidate embeddings available for audit set (model_id=%s)", model_id
            )
            return {"model_id": model_id, "audit_item_count": 0}

        # Score-stratified bucket sampling — mirrors select_audit_set() but
        # operates on pre-scored lightweight tuples (no raw vectors needed).
        _n_per_bucket = 6
        _n_buckets = 5
        bucket_edges = np.linspace(0.0, 1.0, _n_buckets + 1)
        rng = np.random.default_rng(seed=42)

        probas_arr = np.array([s[2] for s in scored_items], dtype=np.float32)
        audit_samples: list[AuditSample] = []

        for bucket_idx in range(_n_buckets):
            low = float(bucket_edges[bucket_idx])
            high = float(bucket_edges[bucket_idx + 1])

            if bucket_idx == _n_buckets - 1:
                in_bucket = np.where((probas_arr >= low) & (probas_arr <= high))[0]
            else:
                in_bucket = np.where((probas_arr >= low) & (probas_arr < high))[0]

            if len(in_bucket) == 0:
                continue

            n_draw = min(_n_per_bucket, len(in_bucket))
            drawn_local = rng.choice(in_bucket, size=n_draw, replace=False)

            for local_idx in drawn_local:
                eid, rid, proba = scored_items[int(local_idx)]
                audit_samples.append(
                    AuditSample(
                        embedding_id=eid,
                        recording_id=rid,
                        predicted_proba=proba,
                    )
                )

        logger.info(
            "Audit set selected: %d samples (model_id=%s)",
            len(audit_samples),
            model_id,
        )

        if not audit_samples:
            return {"model_id": model_id, "audit_item_count": 0}

        # ------------------------------------------------------------------
        # Step 6: Fetch start_time / end_time for selected embeddings
        # ------------------------------------------------------------------
        sample_embedding_ids = [s.embedding_id for s in audit_samples]

        meta_sql = text("""
            SELECT e.id, e.recording_id, e.start_time, e.end_time
            FROM embeddings e
            WHERE e.id = ANY(:embedding_ids)
        """)

        async with session_factory() as db:
            meta_rows = (
                await db.execute(meta_sql, {"embedding_ids": sample_embedding_ids})
            ).fetchall()

        meta_map = {str(r.id): r for r in meta_rows}

        # ------------------------------------------------------------------
        # Step 7: Create Annotation + AuditSetItem records
        # ------------------------------------------------------------------
        from echoroo.models.annotation import Annotation  # noqa: PLC0415
        from echoroo.models.enums import DetectionSource, DetectionStatus  # noqa: PLC0415
        from echoroo.models.sampling_round import AuditSetItem  # noqa: PLC0415

        now = datetime.now(UTC)
        audit_item_count = 0

        async with session_factory() as db:
            for sample in audit_samples:
                meta = meta_map.get(sample.embedding_id)
                if meta is None:
                    logger.warning(
                        "No metadata found for embedding_id=%s during audit set creation, skipping.",
                        sample.embedding_id,
                    )
                    continue

                annotation = Annotation(
                    recording_id=UUID(sample.recording_id),
                    tag_id=target_tag_id,
                    source=DetectionSource.AUDIT_SET,
                    status=DetectionStatus.UNREVIEWED,
                    start_time=float(meta.start_time),
                    end_time=float(meta.end_time),
                    created_at=now,
                    updated_at=now,
                )
                db.add(annotation)
                await db.flush()
                await db.refresh(annotation)

                audit_item = AuditSetItem(
                    custom_model_id=UUID(model_id),
                    embedding_id=UUID(sample.embedding_id),
                    recording_id=UUID(sample.recording_id),
                    predicted_proba=sample.predicted_proba,
                    annotation_id=annotation.id,
                    created_at=now,
                )
                db.add(audit_item)
                audit_item_count += 1

            await db.commit()

        logger.info(
            "Audit set generation complete: model_id=%s, audit_item_count=%d",
            model_id,
            audit_item_count,
        )

        return {
            "model_id": model_id,
            "audit_item_count": audit_item_count,
        }

    except Exception:
        logger.exception(
            "Audit set generation failed: model_id=%s", model_id
        )
        raise

    finally:
        await engine.dispose()
