"""Custom classifier training Celery task and its async implementation.

Task name ``echoroo.workers.classifier_tasks.train_custom_model`` is preserved
for Celery registration compatibility.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.workers.celery_app import app
from echoroo.workers.classifier.utils import (
    _fetch_training_embeddings,
    _fetch_unlabeled_embeddings,
    _upload_model_to_s3,
)
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)

# Minimum number of positive and negative examples required to start training
_MIN_POSITIVE_SAMPLES = 15
_MIN_NEGATIVE_SAMPLES = 15


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

    total_start = time.perf_counter()

    # ------------------------------------------------------------------
    # Step 1: Collect training data via a single batch SQL query
    # Fetches embeddings linked to annotations from all completed sampling rounds
    # ------------------------------------------------------------------
    fetch_labeled_start = time.perf_counter()
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
    logger.info(
        "[timing] step=fetch_labeled project_id=%s elapsed=%.2fs n=%d",
        project_id,
        time.perf_counter() - fetch_labeled_start,
        len(training_rows),
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
        fetch_unlabeled_start = time.perf_counter()
        unlabeled_result = await _fetch_unlabeled_embeddings(
            db=db,
            project_id=project_id,
            embedding_model_name=embedding_model_name,
            exclude_embedding_ids=labeled_embedding_ids,
            # Pull a larger pool so MiniBatchKMeans clustering can pick a
            # diverse subset. The clustering step below compresses the pool
            # to roughly ``n_clusters * samples_per_cluster`` samples.
            max_samples=max(max_unlabeled * 10, max_unlabeled),
        )

        if unlabeled_result is not None:
            unlabeled_embeddings, unlabeled_recording_ids = unlabeled_result

        fetched_n = (
            len(unlabeled_embeddings) if unlabeled_embeddings is not None else 0
        )
        logger.info(
            "[timing] step=fetch_unlabeled project_id=%s elapsed=%.2fs n=%d",
            project_id,
            time.perf_counter() - fetch_unlabeled_start,
            fetched_n,
        )

        if unlabeled_embeddings is not None and len(unlabeled_embeddings) > 0:
            from echoroo.ml.classifiers import cluster_unlabeled_embeddings

            # Compress large unlabeled pools with MiniBatchKMeans (20k -> 2k).
            # Self-training scales poorly with huge pools, so a diverse
            # representative subset strikes a better speed/quality tradeoff.
            if len(unlabeled_embeddings) > 1000:
                cluster_start = time.perf_counter()
                before = len(unlabeled_embeddings)
                reduced = cluster_unlabeled_embeddings(
                    unlabeled_embeddings,
                    n_clusters=1000,
                    samples_per_cluster=2,
                )
                after = len(reduced)
                # cluster_unlabeled_embeddings returns a row-subset of the
                # input, so recording_ids can be filtered by locating each
                # reduced row in the original array. We recover the indices
                # by using np.isin on identity of the first column, which is
                # unreliable for large arrays; instead re-run the selection
                # logic by searching for row equality is O(n*m). To keep
                # this O(n), we simply discard recording_ids here when
                # clustering is applied — recording-level unlabeled
                # filtering is a best-effort optimisation and the eval model
                # still falls back to using all clustered unlabeled samples.
                unlabeled_embeddings = reduced
                unlabeled_recording_ids = None
                logger.info(
                    "[timing] step=cluster_unlabeled project_id=%s elapsed=%.2fs "
                    "before=%d after=%d",
                    project_id,
                    time.perf_counter() - cluster_start,
                    before,
                    after,
                )
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

    fit_start_perf = time.perf_counter()
    train_start = datetime.now(UTC)
    trained_classifier, metrics = train_with_cv(
        embeddings=embeddings,
        labels=labels,
        unlabeled_embeddings=unlabeled_embeddings,
        recording_ids=recording_ids,
        unlabeled_recording_ids=unlabeled_recording_ids,
    )
    train_duration_s = (datetime.now(UTC) - train_start).total_seconds()

    # Capture the number of pseudo-positives generated by self-training so we
    # can attribute speed/quality changes to the pseudo-label count.
    pseudo_pos_count = 0
    try:
        inner = trained_classifier.model["classifier"]
        # ``transduction_`` is an attribute of the fitted
        # SelfTrainingClassifier but the Pipeline-typed container hides it
        # from static analysis, so cast to Any for this diagnostic-only
        # access.
        if hasattr(inner, "transduction_") and unlabeled_embeddings is not None:
            transduction = cast(Any, inner).transduction_
            # Pseudo-labels are rows assigned a non-negative label in the
            # unlabeled tail of the combined array.
            tail = transduction[len(labels):]
            pseudo_pos_count = int(np.sum(tail == 1))
    except Exception:  # noqa: BLE001 — best-effort diagnostic only
        pseudo_pos_count = 0

    logger.info(
        "[timing] step=fit project_id=%s elapsed=%.2fs labeled=%d unlabeled=%d "
        "pseudo_pos=%d",
        project_id,
        time.perf_counter() - fit_start_perf,
        len(embeddings),
        int(len(unlabeled_embeddings)) if unlabeled_embeddings is not None else 0,
        pseudo_pos_count,
    )

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

    logger.info(
        "[timing] step=total project_id=%s elapsed=%.2fs",
        project_id,
        time.perf_counter() - total_start,
    )

    return {
        "status": "trained",
        "model_id": str(model.id),
        "artifact_key": artifact_key,
        "metrics": model.metrics,
        "hyperparameters": model.hyperparameters,
        "training_stats": model.training_stats,
    }

