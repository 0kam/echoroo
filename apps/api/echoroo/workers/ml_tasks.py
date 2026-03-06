"""Celery worker tasks for ML-based audio species detection.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from echoroo.core.settings import get_settings
from echoroo.models.annotation import Annotation
from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
from echoroo.models.enums import DetectionRunStatus, DetectionSource, DetectionStatus
from echoroo.models.recording import Recording
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.repositories.system import SystemSettingRepository
from echoroo.repositories.tag import TagRepository
from echoroo.repositories.taxon import TaxonRepository
from echoroo.services.audio import AudioService
from echoroo.services.gbif import NON_SPECIES_LABELS
from echoroo.services.h3_utils import h3_to_center
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)

# Number of recordings to process before flushing annotations and updating progress
_COMMIT_BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# Async session factory (same pattern as upload_tasks.py)
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
# Async implementation
# ---------------------------------------------------------------------------


async def _mark_detection_run_failed(run_id: UUID, error: str) -> None:
    """Mark a detection run as FAILED with an error message.

    Args:
        run_id: DetectionRun's UUID.
        error: Error message to store on the run.
    """
    engine, session_factory = _get_engine_and_session_factory()
    try:
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            run = await run_repo.get_by_id(run_id)
            if run is not None:
                run.status = DetectionRunStatus.FAILED
                run.completed_at = datetime.now(UTC)
                run.error_message = error
                await run_repo.update(run)
                await db.commit()
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.ml_tasks.run_birdnet_detection",
    time_limit=7200,  # 2 hour hard limit
    soft_time_limit=7000,  # ~1h 57m soft limit
)
def run_birdnet_detection(
    _self: Any,
    dataset_id: str,
    project_id: str,
    detection_run_id: str,
) -> dict[str, Any]:
    """Run BirdNET species detection on all recordings in a dataset.

    Delegates to ``run_detection`` with ``model_name="birdnet"``. Kept as a
    separate named task for backward compatibility with existing Celery queues.

    Args:
        dataset_id: Dataset UUID string to process.
        project_id: Project UUID string that owns the dataset.
        detection_run_id: Existing DetectionRun UUID string to process.

    Returns:
        Summary dict with detection_run_id, recordings_processed, total_annotations.
    """
    logger.info(
        "Starting BirdNET detection task for dataset %s (project %s, run %s)",
        dataset_id,
        project_id,
        detection_run_id,
    )
    run_id_for_error: UUID = UUID(detection_run_id)

    try:
        result: dict[str, Any] = asyncio.run(
            _run_detection(dataset_id, project_id, detection_run_id, "birdnet")
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "BirdNET detection failed for dataset %s: %s",
            dataset_id,
            exc,
        )
        with contextlib.suppress(Exception):
            asyncio.run(_mark_detection_run_failed(run_id_for_error, str(exc)))
        raise


# ---------------------------------------------------------------------------
# Storage dimension for embedding vectors (max across all supported models)
# ---------------------------------------------------------------------------

_STORAGE_EMBEDDING_DIM = 1536  # Perch V2 dimension; BirdNET (1024) is zero-padded


def _pad_embedding(
    embedding: np.ndarray[Any, np.dtype[np.float32]], target_dim: int
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Zero-pad an embedding vector to the target dimension.

    Args:
        embedding: 1-D float32 array of shape (source_dim,).
        target_dim: Target dimension to pad to.

    Returns:
        1-D float32 array of shape (target_dim,).
        If embedding.shape[0] >= target_dim, returned as-is (truncated if needed).
    """
    source_dim = embedding.shape[0]
    if source_dim == target_dim:
        return embedding
    if source_dim > target_dim:
        return embedding[:target_dim]
    padded: np.ndarray[Any, np.dtype[np.float32]] = np.pad(
        embedding, (0, target_dim - source_dim), mode="constant"
    ).astype(np.float32)
    return padded


# ---------------------------------------------------------------------------
# Shared helper functions for detection and embedding pipelines
# ---------------------------------------------------------------------------


def _extract_batch_embeddings(
    batch_result: Any,
) -> tuple[np.ndarray[Any, np.dtype[np.float32]], np.ndarray[Any, Any] | None]:
    """Extract embeddings array and optional mask from a batch encode/predict result.

    Converts the ``embeddings`` attribute (which may be a torch Tensor or
    numpy array) to a float32 numpy array.  Also extracts the
    ``embeddings_masked`` attribute if present (Perch only).

    Args:
        batch_result: Result object from ``encode_batch()`` or
            ``predict_files_batch()`` that carries ``.embeddings`` and
            optionally ``.embeddings_masked``.

    Returns:
        Tuple of (embeddings_array, mask_or_None).
    """
    raw = batch_result.embeddings
    if hasattr(raw, "numpy"):
        raw = raw.numpy()
    embeddings: np.ndarray[Any, np.dtype[np.float32]] = np.asarray(raw, dtype=np.float32)

    mask: np.ndarray[Any, Any] | None = None
    if hasattr(batch_result, "embeddings_masked"):
        raw_masked = batch_result.embeddings_masked
        if hasattr(raw_masked, "numpy"):
            raw_masked = raw_masked.numpy()
        mask = np.asarray(raw_masked)

    return embeddings, mask


def _extract_file_embeddings(
    all_embeddings: np.ndarray[Any, np.dtype[np.float32]],
    all_mask: np.ndarray[Any, Any] | None,
    file_index: int,
) -> tuple[np.ndarray[Any, np.dtype[np.float32]], np.ndarray[Any, Any] | None]:
    """Extract a single file's embeddings and mask from batch result arrays.

    Handles both 4-D ``(n_files, 1, n_segments, dim)`` and 3-D
    ``(n_files, n_segments, dim)`` shapes produced by different model versions.

    Args:
        all_embeddings: Full batch embeddings array.
        all_mask: Full batch mask array, or *None*.
        file_index: Index of the file within the batch.

    Returns:
        Tuple of (file_embeddings, file_mask_or_None) where
        ``file_embeddings`` has shape ``(n_segments, dim)``.
    """
    file_mask: np.ndarray[Any, Any] | None = None

    if all_embeddings.ndim == 4:
        file_embeddings = all_embeddings[file_index, 0]
        if all_mask is not None:
            file_mask = all_mask[file_index, 0]
    elif all_embeddings.ndim == 3:
        file_embeddings = all_embeddings[file_index]
        if all_mask is not None:
            file_mask = all_mask[file_index]
    else:
        # Single-file fallback (should not occur in batch mode)
        file_embeddings = all_embeddings
        file_mask = all_mask

    return file_embeddings, file_mask


def _apply_embedding_mask(
    file_embeddings: np.ndarray[Any, np.dtype[np.float32]],
    file_mask: np.ndarray[Any, Any] | None,
) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Apply per-element mask to filter valid segments.

    Reduces a per-element boolean mask to a per-segment boolean and
    removes masked (invalid) segments from the embeddings array.

    Args:
        file_embeddings: Embeddings for one file, shape ``(n_segments, dim)``.
        file_mask: Per-element mask for the same file, or *None*.

    Returns:
        Filtered embeddings array containing only valid segments.
    """
    if file_mask is None:
        return file_embeddings

    seg_masked = file_mask.all(axis=1) if file_mask.ndim == 2 else file_mask.flatten()
    keep = ~seg_masked
    return file_embeddings[keep]


def _download_recordings_to_local(
    recordings: list[Any],
    audio_service: AudioService,
) -> tuple[list[tuple[Any, Path]], int]:
    """Download recording files from S3 and return list of (recording, local_path) tuples.

    Skips recordings whose files cannot be downloaded, logging warnings for
    each failure.

    Args:
        recordings: List of Recording ORM objects.
        audio_service: AudioService instance for file access.

    Returns:
        Tuple of (recording_paths, failed_count) where *recording_paths* is
        a list of ``(recording_orm, local_path)`` pairs and *failed_count*
        is the number of recordings that could not be downloaded.
    """
    recording_paths: list[tuple[Any, Path]] = []
    failed = 0
    for recording in recordings:
        try:
            local_path = audio_service.ensure_file_local(recording.path)
            if local_path:
                recording_paths.append((recording, Path(local_path)))
            else:
                logger.warning(
                    "Audio file not found for recording %s (%s)",
                    recording.id,
                    recording.filename,
                )
                failed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to download audio for recording %s (%s): %s",
                recording.id,
                recording.filename,
                exc,
            )
            failed += 1
    return recording_paths, failed


# ---------------------------------------------------------------------------
# Detection-only async implementation (annotations only, no embeddings)
# ---------------------------------------------------------------------------


async def _run_detection(
    dataset_id: str,
    project_id: str,
    detection_run_id: str,
    model_name: str,
) -> dict[str, Any]:
    """Async implementation of the detection pipeline (annotations only).

    Uses the ML abstraction layer (ModelRegistry, InferenceEngine) to run
    inference for any registered model. Generates annotations for models
    that support classification. Embedding generation is handled separately
    by ``_run_embedding_generation()``.

    Args:
        dataset_id: Dataset UUID string.
        project_id: Project UUID string.
        detection_run_id: Existing DetectionRun UUID string to process.
        model_name: Name of the model to use (e.g. "birdnet", "perch").

    Returns:
        Summary dict with detection_run_id, recordings_processed,
        total_annotations, status.
    """
    # Import here to trigger model __init__.py registration side-effects
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.ml.registry import ModelRegistry

    settings = get_settings()
    engine, session_factory = _get_engine_and_session_factory()

    dataset_uuid = UUID(dataset_id)
    project_uuid = UUID(project_id)
    run_uuid = UUID(detection_run_id)

    try:
        # ------------------------------------------------------------------
        # Step 1: Load model-specific settings (only birdnet uses system settings)
        # ------------------------------------------------------------------
        min_conf: float = 0.1
        custom_species_list: list[str] | None = None

        if model_name == "birdnet":
            async with session_factory() as db:
                setting_repo = SystemSettingRepository(db)
                birdnet_settings = await setting_repo.get_birdnet_settings()
            min_conf = float(birdnet_settings["min_conf"])  # type: ignore[arg-type]
            species_filter = str(birdnet_settings["species_filter"])
            logger.info(
                "BirdNET settings: species_filter=%s, min_conf=%.2f",
                species_filter,
                min_conf,
            )
        else:
            species_filter = "none"

        # ------------------------------------------------------------------
        # Step 2: Load the DetectionRun and set to RUNNING
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

        # ------------------------------------------------------------------
        # Step 3: Load all recordings for the dataset
        # Eagerly load dataset -> site so that geo-filter code can access
        # first_recording.dataset.site.h3_index after the session is closed
        # without raising DetachedInstanceError.
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
                .options(selectinload(Recording.dataset).selectinload(Dataset.site))
            )
            recordings = list(result.scalars().all())

        logger.info(
            "Starting %s detection on %d recordings in dataset %s",
            model_name,
            len(recordings),
            dataset_id,
        )

        # ------------------------------------------------------------------
        # Step 4: Initialize AudioService and load the inference engine
        # ------------------------------------------------------------------
        audio_service = AudioService(
            audio_root=settings.AUDIO_ROOT,
            s3_audio_cache_dir="/data/s3_audio_cache",
        )

        loader_cls = ModelRegistry.get_loader_class(model_name)
        engine_cls = ModelRegistry.get_engine_class(model_name)

        loader = loader_cls()
        loader.load()
        inference_engine = engine_cls(loader, confidence_threshold=min_conf)  # type: ignore[call-arg]

        spec = inference_engine.specification
        supports_classification = spec.supports_classification

        # ------------------------------------------------------------------
        # Step 4b: Compute geo species list for BirdNET (once per dataset)
        # ------------------------------------------------------------------
        if model_name == "birdnet" and species_filter == "birdnet_geo" and recordings:
            from echoroo.ml.birdnet_wrapper import BirdNETWrapper

            wrapper = BirdNETWrapper.get_instance()
            first_recording = recordings[0]
            site = getattr(getattr(first_recording, "dataset", None), "site", None)
            h3_index: str | None = getattr(site, "h3_index", None)

            week: int | None = None
            for rec in recordings:
                if rec.datetime is not None:
                    week = rec.datetime.isocalendar()[1]
                    break

            if h3_index is not None and week is not None:
                try:
                    lat, lon = h3_to_center(h3_index)
                    custom_species_list = wrapper.get_species_for_location(lat, lon, week)
                    logger.info(
                        "Geo filter: lat=%.4f, lon=%.4f, week=%d -> %d species",
                        lat,
                        lon,
                        week,
                        len(custom_species_list),
                    )
                except Exception as geo_exc:  # noqa: BLE001
                    logger.warning("Geo filter failed (skipping filter): %s", geo_exc)
                    custom_species_list = None

        total_annotations = 0
        recordings_processed = 0
        recordings_failed = 0
        pending_annotations: list[Annotation] = []

        # ------------------------------------------------------------------
        # Step 5: Download all files from S3 and collect local paths
        # ------------------------------------------------------------------
        recording_paths, download_failures = _download_recordings_to_local(
            recordings, audio_service
        )
        recordings_failed += download_failures

        if not recording_paths:
            logger.warning("No audio files available to process for run %s", run_uuid)
        elif hasattr(inference_engine, "predict_files_batch"):
            # ------------------------------------------------------------------
            # Batch path: predict ALL files in one call
            # ------------------------------------------------------------------
            # Sort by file path to match BirdNET's internal alphabetical sorting.
            recording_paths.sort(key=lambda x: str(x[1]))
            file_paths = [str(p) for _, p in recording_paths]

            logger.info(
                "Batch predict %d files for run %s",
                len(file_paths),
                run_uuid,
            )

            try:
                _embeddings_result, predictions_result = inference_engine.predict_files_batch(
                    file_paths
                )
            except Exception as exc:
                logger.exception("Batch predict failed for run %s: %s", run_uuid, exc)
                raise

            spec = inference_engine.specification
            segment_duration: float = spec.segment_duration
            hop_duration = segment_duration  # overlap is always 0.0 here

            # Determine DetectionSource enum value once
            try:
                detection_source = DetectionSource(model_name)
            except ValueError:
                detection_source = DetectionSource.BIRDNET

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
                            "total_annotations": total_annotations,
                            "status": "cancelled",
                        }

                try:
                    # Extract this file's predictions based on array dimensions.
                    # Batch predict result shape: (n_files, 1, n_segments, n_species) or
                    # (n_files, n_segments, n_species) depending on model version.
                    all_probs = predictions_result.species_probs
                    all_ids = predictions_result.species_ids
                    if all_probs.ndim == 4:
                        file_probs = all_probs[file_index, 0]
                        file_ids = all_ids[file_index, 0]
                    elif all_probs.ndim == 3:
                        file_probs = all_probs[file_index]
                        file_ids = all_ids[file_index]
                    else:
                        file_probs = all_probs
                        file_ids = all_ids

                    n_segments = len(file_probs)

                    # Build annotations per segment
                    if supports_classification:
                        async with session_factory() as db:
                            tag_repo = TagRepository(db)
                            taxon_repo = TaxonRepository(db)

                            for seg_idx in range(n_segments):
                                start_time = seg_idx * hop_duration
                                end_time = start_time + segment_duration

                                # Build annotations from predictions for this segment
                                seg_probs = file_probs[seg_idx]
                                seg_ids = file_ids[seg_idx]

                                # Use the inference engine's filter logic if available,
                                # otherwise apply threshold manually
                                if hasattr(inference_engine, "_collect_predictions_by_segment"):
                                    if hasattr(inference_engine, "_filter_predictions"):
                                        preds = inference_engine._filter_predictions(
                                            seg_probs.astype(np.float32),
                                            seg_ids,
                                            inference_engine._model.species_list,
                                        )
                                    else:
                                        preds = []
                                else:
                                    preds = []

                                for species_name, confidence in preds:
                                    # Species name format: "Scientific Name_Common Name"
                                    parts = species_name.split("_", 1)
                                    scientific_name = parts[0] if parts else species_name
                                    common_name = parts[1] if len(parts) > 1 else ""
                                    is_non_bio = common_name in NON_SPECIES_LABELS

                                    taxon = await taxon_repo.get_or_create_by_scientific_name(
                                        scientific_name=scientific_name,
                                        common_name=common_name,
                                        is_non_biological=is_non_bio,
                                    )
                                    tag = await tag_repo.get_or_create_species(
                                        project_id=project_uuid,
                                        scientific_name=scientific_name,
                                        common_name=common_name,
                                        taxon_id=taxon.id,
                                    )

                                    pending_annotations.append(
                                        Annotation(
                                            recording_id=recording.id,
                                            tag_id=tag.id,
                                            detection_run_id=run_uuid,
                                            source=detection_source,
                                            status=DetectionStatus.UNREVIEWED,
                                            confidence=confidence,
                                            start_time=start_time,
                                            end_time=end_time,
                                        )
                                    )

                            # Commit tag/taxon get_or_create operations once per recording
                            await db.commit()

                    recordings_processed += 1

                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s processing failed for recording %s (%s): %s",
                        model_name,
                        recording.id,
                        recording.filename,
                        exc,
                    )
                    recordings_failed += 1
                    recordings_processed += 1

                # ------------------------------------------------------------------
                # Step 6: Flush batch every _COMMIT_BATCH_SIZE recordings
                # ------------------------------------------------------------------
                if recordings_processed % _COMMIT_BATCH_SIZE == 0 and pending_annotations:
                    batch_annotations = len(pending_annotations)
                    async with session_factory() as db:
                        annotation_repo = AnnotationRepository(db)
                        await annotation_repo.create_batch(pending_annotations)
                        await db.commit()

                    total_annotations += batch_annotations
                    pending_annotations = []

                    # Update annotation_count on DetectionRun
                    async with session_factory() as db:
                        run_repo = DetectionRunRepository(db)
                        run = await run_repo.get_by_id(run_uuid)
                        if run is not None:
                            run.annotation_count = total_annotations
                            await run_repo.update(run)
                            await db.commit()

                    logger.info(
                        "DetectionRun %s progress: %d/%d recordings, "
                        "%d annotations so far",
                        run_uuid,
                        recordings_processed,
                        len(recordings),
                        total_annotations,
                    )

        else:
            # ------------------------------------------------------------------
            # Fallback path: per-file inference (for engines without batch support)
            # ------------------------------------------------------------------
            logger.info(
                "Engine %s does not support predict_files_batch(); falling back to per-file "
                "inference for run %s",
                type(inference_engine).__name__,
                run_uuid,
            )

            # Determine DetectionSource enum value once
            try:
                detection_source = DetectionSource(model_name)
            except ValueError:
                detection_source = DetectionSource.BIRDNET

            for recording, local_path in recording_paths:
                # Cancellation check: abort if run was externally set to FAILED
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
                            "total_annotations": total_annotations,
                            "status": "cancelled",
                        }

                try:
                    results = inference_engine.predict_file(
                        local_path, custom_species_list=custom_species_list
                    )

                    if results:
                        async with session_factory() as db:
                            tag_repo = TagRepository(db)
                            taxon_repo = TaxonRepository(db)

                            for inference_result in results:
                                if supports_classification and inference_result.has_detection:
                                    for species_name, confidence in inference_result.predictions:
                                        parts = species_name.split("_", 1)
                                        scientific_name = parts[0] if parts else species_name
                                        common_name = parts[1] if len(parts) > 1 else ""
                                        is_non_bio = common_name in NON_SPECIES_LABELS

                                        taxon = await taxon_repo.get_or_create_by_scientific_name(
                                            scientific_name=scientific_name,
                                            common_name=common_name,
                                            is_non_biological=is_non_bio,
                                        )
                                        tag = await tag_repo.get_or_create_species(
                                            project_id=project_uuid,
                                            scientific_name=scientific_name,
                                            common_name=common_name,
                                            taxon_id=taxon.id,
                                        )

                                        pending_annotations.append(
                                            Annotation(
                                                recording_id=recording.id,
                                                tag_id=tag.id,
                                                detection_run_id=run_uuid,
                                                source=detection_source,
                                                status=DetectionStatus.UNREVIEWED,
                                                confidence=confidence,
                                                start_time=inference_result.start_time,
                                                end_time=inference_result.end_time,
                                            )
                                        )

                            await db.commit()

                    recordings_processed += 1

                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s processing failed for recording %s (%s): %s",
                        model_name,
                        recording.id,
                        recording.filename,
                        exc,
                    )
                    recordings_failed += 1
                    recordings_processed += 1

                # Flush batch every _COMMIT_BATCH_SIZE recordings
                if recordings_processed % _COMMIT_BATCH_SIZE == 0 and pending_annotations:
                    batch_annotations = len(pending_annotations)
                    async with session_factory() as db:
                        annotation_repo = AnnotationRepository(db)
                        await annotation_repo.create_batch(pending_annotations)
                        await db.commit()

                    total_annotations += batch_annotations
                    pending_annotations = []

                    async with session_factory() as db:
                        run_repo = DetectionRunRepository(db)
                        run = await run_repo.get_by_id(run_uuid)
                        if run is not None:
                            run.annotation_count = total_annotations
                            await run_repo.update(run)
                            await db.commit()

                    logger.info(
                        "DetectionRun %s progress: %d/%d recordings, "
                        "%d annotations so far",
                        run_uuid,
                        recordings_processed,
                        len(recordings),
                        total_annotations,
                    )

        # ------------------------------------------------------------------
        # Step 7: Flush remaining batch
        # ------------------------------------------------------------------
        if pending_annotations:
            remaining_annotations = len(pending_annotations)
            async with session_factory() as db:
                annotation_repo = AnnotationRepository(db)
                await annotation_repo.create_batch(pending_annotations)
                await db.commit()
            total_annotations += remaining_annotations

        # ------------------------------------------------------------------
        # Step 8: Mark DetectionRun as COMPLETED
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            run = await run_repo.get_by_id(run_uuid)
            if run is not None:
                run.status = DetectionRunStatus.COMPLETED
                run.completed_at = datetime.now(UTC)
                run.annotation_count = total_annotations
                await run_repo.update(run)
                await db.commit()

        logger.info(
            "DetectionRun %s completed: %d recordings processed (%d failed), "
            "%d annotations created",
            run_uuid,
            recordings_processed,
            recordings_failed,
            total_annotations,
        )
        return {
            "detection_run_id": detection_run_id,
            "recordings_processed": recordings_processed,
            "recordings_failed": recordings_failed,
            "total_annotations": total_annotations,
            "status": "completed",
        }

    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Generic detection Celery task
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.ml_tasks.run_detection",
    time_limit=7200,
    soft_time_limit=7000,
)
def run_detection(
    _self: Any,
    dataset_id: str,
    project_id: str,
    detection_run_id: str,
    model_name: str = "birdnet",
) -> dict[str, Any]:
    """Run species detection on all recordings in a dataset.

    Generic task that uses the ML abstraction layer (ModelRegistry) to run
    inference for any registered model. Only annotations are persisted;
    embedding generation is handled by ``run_embedding_generation()``.

    Per-recording failures are logged but do not abort the entire run. Detection
    is cancelled early if the run's status is externally set to FAILED.

    Args:
        dataset_id: Dataset UUID string to process.
        project_id: Project UUID string that owns the dataset.
        detection_run_id: Existing DetectionRun UUID string to process.
        model_name: Name of the registered model (e.g. "birdnet", "perch").

    Returns:
        Summary dict with detection_run_id, recordings_processed,
        total_annotations.
    """
    logger.info(
        "Starting %s detection task for dataset %s (project %s, run %s)",
        model_name,
        dataset_id,
        project_id,
        detection_run_id,
    )
    run_id_for_error: UUID = UUID(detection_run_id)

    try:
        result: dict[str, Any] = asyncio.run(
            _run_detection(dataset_id, project_id, detection_run_id, model_name)
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "%s detection failed for dataset %s: %s",
            model_name,
            dataset_id,
            exc,
        )
        with contextlib.suppress(Exception):
            asyncio.run(_mark_detection_run_failed(run_id_for_error, str(exc)))
        raise


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
    # Import here to trigger model __init__.py registration side-effects
    import echoroo.ml.birdnet  # noqa: F401
    import echoroo.ml.perch  # noqa: F401
    from echoroo.ml.registry import ModelRegistry

    settings = get_settings()
    engine, session_factory = _get_engine_and_session_factory()

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

        loader_cls = ModelRegistry.get_loader_class(model_name)
        engine_cls = ModelRegistry.get_engine_class(model_name)

        loader = loader_cls()
        loader.load()
        inference_engine = engine_cls(loader)

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
                        async with session_factory() as db:
                            stmt = pg_insert(Embedding).values(embedding_values)
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
