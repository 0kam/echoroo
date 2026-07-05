"""Custom classifier inference Celery task and its async implementation.

Task name ``echoroo.workers.classifier_tasks.run_custom_model_inference`` is
preserved for Celery registration compatibility.
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
from sqlalchemy import text

from echoroo.workers.celery_app import app
from echoroo.workers.classifier.utils import _download_model_from_s3
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)

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

            from echoroo.models.recording_annotation import (
                CUSTOM_SVM_DEDUP_INDEX_ELEMENTS,
                CUSTOM_SVM_DEDUP_INDEX_WHERE,
                RecordingAnnotation,
            )

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
                        # Target the partial unique index
                        # ``uq_recording_annotations_custom_svm`` (migration 0031)
                        # as the ON CONFLICT arbiter. The columns + predicate come
                        # from the shared constants in
                        # ``models.recording_annotation`` so they can never drift
                        # from the migration's index definition; a re-run of the
                        # same custom_svm detection_run thus skips the duplicate
                        # rows.
                        stmt = (
                            pg_insert(RecordingAnnotation)
                            .values(pending_annotation_dicts)
                            .on_conflict_do_nothing(
                                index_elements=list(
                                    CUSTOM_SVM_DEDUP_INDEX_ELEMENTS
                                ),
                                index_where=text(CUSTOM_SVM_DEDUP_INDEX_WHERE),
                            )
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
                        # Same partial-index arbiter as the large-buffer branch
                        # above (migration 0031); columns + predicate come from
                        # the shared constants in ``models.recording_annotation``.
                        stmt = (
                            pg_insert(RecordingAnnotation)
                            .values(pending_annotation_dicts)
                            .on_conflict_do_nothing(
                                index_elements=list(
                                    CUSTOM_SVM_DEDUP_INDEX_ELEMENTS
                                ),
                                index_where=text(CUSTOM_SVM_DEDUP_INDEX_WHERE),
                            )
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

