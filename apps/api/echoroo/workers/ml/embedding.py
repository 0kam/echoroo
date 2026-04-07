"""Celery worker tasks for ML-based embedding generation.

Contains the embedding pipeline: generate and store embedding vectors
without creating detection annotation records.
Task names are preserved as ``echoroo.workers.ml_tasks.*`` for backward
compatibility with existing Celery queue routing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
from echoroo.models.enums import DetectionRunStatus
from echoroo.models.recording import Recording
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.services.audio import AudioService
from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory
from echoroo.workers.ml.utils import (
    _STORAGE_EMBEDDING_DIM,
    _apply_embedding_mask,
    _download_recordings_to_local,
    _extract_batch_embeddings,
    _extract_file_embeddings,
    _mark_detection_run_failed,
    _pad_embedding,
)

logger = logging.getLogger(__name__)

# Number of recordings to process before updating progress
_COMMIT_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Embedding-only async implementation
# ---------------------------------------------------------------------------


async def _run_embedding_generation(
    dataset_id: str,
    project_id: str,
    detection_run_id: str,
    model_name: str,
) -> dict[str, Any]:
    """Async implementation of embedding-only generation.

    Generates and stores embedding vectors without creating annotation records.
    Useful for building a searchable embedding index.

    Args:
        dataset_id: Dataset UUID string.
        project_id: Project UUID string.
        detection_run_id: Existing DetectionRun UUID string.
        model_name: Name of the registered model.

    Returns:
        Summary dict with detection_run_id, recordings_processed,
        total_embeddings, status.
    """
    settings = get_settings()
    engine, session_factory = get_worker_engine_and_session_factory()

    dataset_uuid = UUID(dataset_id)
    project_uuid = UUID(project_id)
    run_uuid = UUID(detection_run_id)

    try:
        # ------------------------------------------------------------------
        # Step 1: Load the DetectionRun and set to RUNNING
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            detection_run = await run_repo.get_by_id(run_uuid)
            if detection_run is None:
                raise ValueError(f"DetectionRun not found: {detection_run_id}")

            # Check if the run was cancelled before we start
            if detection_run.status == DetectionRunStatus.FAILED:
                logger.info("DetectionRun %s was cancelled before processing started", run_uuid)
                return {"detection_run_id": detection_run_id, "status": "cancelled"}

            detection_run.status = DetectionRunStatus.RUNNING
            detection_run.started_at = datetime.now(UTC)
            await run_repo.update(detection_run)
            await db.commit()

        model_version: str = detection_run.model_version or "unknown"

        # ------------------------------------------------------------------
        # Step 2: Load all recordings for the dataset
        # Join against Dataset to enforce project_id ownership (defense-in-depth).
        # ------------------------------------------------------------------
        async with session_factory() as db:
            result = await db.execute(
                select(Recording)
                .join(Dataset, Recording.dataset_id == Dataset.id)
                .where(
                    Recording.dataset_id == dataset_uuid,
                    Dataset.project_id == project_uuid,
                )
            )
            recordings = list(result.scalars().all())

        logger.info(
            "Starting %s embedding generation on %d recordings in dataset %s",
            model_name,
            len(recordings),
            dataset_id,
        )

        # ------------------------------------------------------------------
        # Step 3: Initialize AudioService and load the inference engine
        # ------------------------------------------------------------------
        audio_service = AudioService(
            audio_root=settings.AUDIO_ROOT,
            s3_audio_cache_dir="/data/s3_audio_cache",
        )

        from echoroo.workers.model_preloader import get_model

        loader, inference_engine = get_model(model_name)

        total_embeddings = 0
        recordings_processed = 0
        recordings_failed = 0

        # ------------------------------------------------------------------
        # Step 4: Download all files from S3 and collect local paths
        # ------------------------------------------------------------------
        recording_paths, download_failures = _download_recordings_to_local(
            recordings, audio_service
        )
        recordings_failed += download_failures

        if not recording_paths:
            logger.warning("No audio files available to process for run %s", run_uuid)
        else:
            # Sort by file path to match BirdNET's internal alphabetical sorting.
            # The file_index in the batch output corresponds to sorted order.
            recording_paths.sort(key=lambda x: str(x[1]))
            file_paths = [str(p) for _, p in recording_paths]

            logger.info(
                "Batch encoding %d files for run %s",
                len(file_paths),
                run_uuid,
            )

            # ------------------------------------------------------------------
            # Step 5: Batch encode -- call model.encode() ONCE with ALL file paths
            # ------------------------------------------------------------------
            try:
                batch_result = inference_engine.encode_batch(file_paths)
            except Exception as exc:
                logger.exception("Batch encode failed for run %s: %s", run_uuid, exc)
                raise

            all_embeddings, all_mask = _extract_batch_embeddings(batch_result)

            spec = inference_engine.specification
            segment_duration: float = spec.segment_duration
            hop_duration = segment_duration  # overlap is always 0.0 here

            # ------------------------------------------------------------------
            # Step 6: Extract per-file embeddings and store with bulk insert
            # ------------------------------------------------------------------
            for file_index, (recording, _) in enumerate(recording_paths):
                # Cancellation check before processing each file
                async with session_factory() as db:
                    run_repo = DetectionRunRepository(db)
                    current_run = await run_repo.get_by_id(run_uuid)
                    if current_run is not None and current_run.status == DetectionRunStatus.FAILED:
                        logger.warning(
                            "DetectionRun %s was cancelled, stopping processing", run_uuid
                        )
                        return {
                            "detection_run_id": detection_run_id,
                            "recordings_processed": recordings_processed,
                            "recordings_failed": recordings_failed,
                            "total_embeddings": total_embeddings,
                            "status": "cancelled",
                        }

                try:
                    file_embeddings, file_mask = _extract_file_embeddings(
                        all_embeddings, all_mask, file_index
                    )
                    file_embeddings = _apply_embedding_mask(file_embeddings, file_mask)

                    # Skip file if all embeddings are NaN
                    if np.isnan(file_embeddings).all():
                        logger.error(
                            "All embeddings NaN for recording %s (%s) -- skipping",
                            recording.id,
                            recording.filename,
                        )
                        recordings_failed += 1
                        recordings_processed += 1
                        continue

                    # Build bulk insert values for this file's segments
                    embedding_values: list[dict[str, Any]] = []
                    for seg_idx in range(len(file_embeddings)):
                        embedding_vec = file_embeddings[seg_idx]
                        if np.isnan(embedding_vec).any():
                            continue
                        padded_vec = _pad_embedding(
                            embedding_vec.astype(np.float32), _STORAGE_EMBEDDING_DIM
                        )
                        start_time = seg_idx * hop_duration
                        end_time = start_time + segment_duration
                        embedding_values.append(
                            {
                                "id": uuid4(),
                                "recording_id": recording.id,
                                "detection_run_id": run_uuid,
                                "model_name": model_name,
                                "model_version": model_version,
                                "start_time": start_time,
                                "end_time": end_time,
                                "vector": padded_vec,  # numpy array accepted by pgvector directly
                            }
                        )

                    if embedding_values:
                        # PostgreSQL limits query parameters to 32767. Each embedding
                        # has 8 columns (including the vector), so chunk conservatively
                        # to 500 rows per batch to avoid hitting the parameter limit.
                        EMBED_CHUNK_SIZE = 500
                        async with session_factory() as db:
                            for j in range(0, len(embedding_values), EMBED_CHUNK_SIZE):
                                chunk = embedding_values[j : j + EMBED_CHUNK_SIZE]
                                stmt = pg_insert(Embedding).values(chunk)
                                stmt = stmt.on_conflict_do_nothing()
                                await db.execute(stmt)
                            await db.commit()
                        total_embeddings += len(embedding_values)

                    recordings_processed += 1

                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s embedding failed for recording %s (%s): %s",
                        model_name,
                        recording.id,
                        recording.filename,
                        exc,
                    )
                    recordings_failed += 1
                    recordings_processed += 1

                # ------------------------------------------------------------------
                # Step 7: Update progress every _COMMIT_BATCH_SIZE recordings
                # ------------------------------------------------------------------
                if recordings_processed % _COMMIT_BATCH_SIZE == 0:
                    # Update annotation_count on DetectionRun (stores embedding count
                    # for embedding-only runs so the UI can display progress)
                    async with session_factory() as db:
                        run_repo = DetectionRunRepository(db)
                        run = await run_repo.get_by_id(run_uuid)
                        if run is not None:
                            run.annotation_count = total_embeddings
                            await run_repo.update(run)
                            await db.commit()

                    logger.info(
                        "DetectionRun %s embedding progress: %d/%d recordings, "
                        "%d embeddings so far",
                        run_uuid,
                        recordings_processed,
                        len(recordings),
                        total_embeddings,
                    )

        # ------------------------------------------------------------------
        # Step 8: Mark DetectionRun as COMPLETED
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            run = await run_repo.get_by_id(run_uuid)
            if run is not None:
                run.status = DetectionRunStatus.COMPLETED
                run.completed_at = datetime.now(UTC)
                run.annotation_count = total_embeddings
                await run_repo.update(run)
                await db.commit()

        logger.info(
            "Embedding generation %s completed: %d recordings processed (%d failed), "
            "%d embeddings created",
            run_uuid,
            recordings_processed,
            recordings_failed,
            total_embeddings,
        )
        return {
            "detection_run_id": detection_run_id,
            "recordings_processed": recordings_processed,
            "recordings_failed": recordings_failed,
            "total_embeddings": total_embeddings,
            "status": "completed",
        }

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Embedding-only Celery task
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.ml_tasks.run_embedding_generation",
    time_limit=7200,
    soft_time_limit=7000,
)
def run_embedding_generation(
    _self: Any,
    dataset_id: str,
    project_id: str,
    detection_run_id: str,
    model_name: str = "perch",
) -> dict[str, Any]:
    """Generate embeddings (without annotations) for all recordings in a dataset.

    Useful for building a searchable embedding index without creating detection
    annotations. Uses the ML abstraction layer for model-agnostic inference.

    Per-recording failures are logged but do not abort the entire run. Processing
    is cancelled early if the run's status is externally set to FAILED.

    Args:
        dataset_id: Dataset UUID string to process.
        project_id: Project UUID string that owns the dataset.
        detection_run_id: Existing DetectionRun UUID string to process.
        model_name: Name of the registered model (default: "perch").

    Returns:
        Summary dict with detection_run_id, recordings_processed, total_embeddings.
    """
    logger.info(
        "Starting %s embedding generation task for dataset %s (project %s, run %s)",
        model_name,
        dataset_id,
        project_id,
        detection_run_id,
    )
    run_id_for_error: UUID = UUID(detection_run_id)

    try:
        result: dict[str, Any] = asyncio.run(
            _run_embedding_generation(dataset_id, project_id, detection_run_id, model_name)
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "%s embedding generation failed for dataset %s: %s",
            model_name,
            dataset_id,
            exc,
        )
        with contextlib.suppress(Exception):
            asyncio.run(_mark_detection_run_failed(run_id_for_error, str(exc)))
        raise
