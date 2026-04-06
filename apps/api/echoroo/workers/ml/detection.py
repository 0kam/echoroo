"""Celery worker tasks for ML-based species detection.

Contains the detection pipeline: BirdNET and generic model detection tasks.
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
from sqlalchemy.orm import selectinload

from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DetectionRunStatus, DetectionSource, DetectionStatus
from echoroo.models.recording import Recording
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.repositories.system import SystemSettingRepository
from echoroo.repositories.tag import TagRepository
from echoroo.repositories.taxon import TaxonRepository
from echoroo.services.audio import AudioService
from echoroo.services.gbif import NON_SPECIES_LABELS
from echoroo.services.h3_utils import h3_to_center
from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory
from echoroo.workers.ml.utils import (
    _build_taxon_tag_caches,
    _bulk_insert_annotations,
    _collect_unique_species_from_batch,
    _download_recordings_to_local,
    _mark_detection_run_failed,
)

logger = logging.getLogger(__name__)

# Number of recordings to process before flushing annotations and updating progress
_COMMIT_BATCH_SIZE = 50


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
    settings = get_settings()
    engine, session_factory = get_worker_engine_and_session_factory()

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

        from echoroo.workers.model_preloader import get_model

        loader, inference_engine = get_model(model_name)
        # Update the confidence threshold for this task invocation.
        # BirdNETInference exposes a writable property; other engines ignore this.
        if hasattr(inference_engine, "confidence_threshold"):
            inference_engine.confidence_threshold = min_conf

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
        # Pending annotation dicts for bulk insert (avoids ORM refresh overhead)
        pending_annotation_dicts: list[dict[str, Any]] = []

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
                    file_paths,
                    custom_species_list=custom_species_list,
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

            # ------------------------------------------------------------------
            # Pre-fetch taxon and tag caches to avoid per-annotation DB lookups.
            # Collect all unique species across the entire batch first, then
            # issue a single batch query for taxons and tags.
            # ------------------------------------------------------------------
            from echoroo.models.tag import Tag
            from echoroo.models.taxon import Taxon

            taxon_cache: dict[str, Taxon] = {}
            tag_cache: dict[str, Tag] = {}

            if supports_classification:
                unique_species = _collect_unique_species_from_batch(
                    predictions_result, inference_engine
                )
                logger.info(
                    "Pre-fetching taxon/tag cache for %d unique species (run %s)",
                    len(unique_species),
                    run_uuid,
                )
                if unique_species:
                    async with session_factory() as db:
                        taxon_cache, tag_cache = await _build_taxon_tag_caches(
                            db, project_uuid, unique_species
                        )
                        await db.commit()

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

                    # Build annotation dicts per segment using pre-fetched caches
                    if supports_classification:
                        now = datetime.now(UTC)
                        for seg_idx in range(n_segments):
                            start_time = seg_idx * hop_duration
                            end_time = start_time + segment_duration

                            seg_probs = file_probs[seg_idx]
                            seg_ids = file_ids[seg_idx]

                            # Use the inference engine's filter logic
                            if hasattr(inference_engine, "_filter_predictions"):
                                preds = inference_engine._filter_predictions(
                                    seg_probs.astype(np.float32),
                                    seg_ids,
                                    inference_engine._model.species_list,
                                )
                            else:
                                preds = []

                            for species_name, confidence in preds:
                                parts = species_name.split("_", 1)
                                scientific_name = parts[0] if parts else species_name

                                # Cache lookup (fallback to DB only for genuinely new species)
                                tag = tag_cache.get(scientific_name)
                                if tag is None:
                                    common_name = parts[1] if len(parts) > 1 else ""
                                    is_non_bio = common_name in NON_SPECIES_LABELS
                                    async with session_factory() as db:
                                        taxon_repo = TaxonRepository(db)
                                        tag_repo = TagRepository(db)
                                        miss_taxon = await taxon_repo.get_or_create_by_scientific_name(
                                            scientific_name=scientific_name,
                                            common_name=common_name,
                                            is_non_biological=is_non_bio,
                                        )
                                        miss_tag = await tag_repo.get_or_create_species(
                                            project_id=project_uuid,
                                            scientific_name=scientific_name,
                                            common_name=common_name,
                                            taxon_id=miss_taxon.id,
                                        )
                                        await db.commit()
                                    taxon_cache[scientific_name] = miss_taxon
                                    tag_cache[scientific_name] = miss_tag
                                    tag = miss_tag

                                pending_annotation_dicts.append(
                                    {
                                        "id": uuid4(),
                                        "recording_id": recording.id,
                                        "tag_id": tag.id,
                                        "detection_run_id": run_uuid,
                                        "source": detection_source,
                                        "status": DetectionStatus.UNREVIEWED,
                                        "confidence": confidence,
                                        "start_time": start_time,
                                        "end_time": end_time,
                                        "created_at": now,
                                        "updated_at": now,
                                    }
                                )

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
                if recordings_processed % _COMMIT_BATCH_SIZE == 0 and pending_annotation_dicts:
                    batch_count = len(pending_annotation_dicts)
                    async with session_factory() as db:
                        inserted = await _bulk_insert_annotations(db, pending_annotation_dicts)
                        await db.commit()

                    total_annotations += inserted
                    pending_annotation_dicts = []

                    # Update annotation_count on DetectionRun
                    async with session_factory() as db:
                        run_repo = DetectionRunRepository(db)
                        run = await run_repo.get_by_id(run_uuid)
                        if run is not None:
                            run.annotation_count = total_annotations
                            await run_repo.update(run)
                            await db.commit()

                    logger.debug(
                        "Flushed %d annotation dicts (%d inserted) for run %s",
                        batch_count,
                        total_annotations,
                        run_uuid,
                    )

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
                            now = datetime.now(UTC)

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

                                        pending_annotation_dicts.append(
                                            {
                                                "id": uuid4(),
                                                "recording_id": recording.id,
                                                "tag_id": tag.id,
                                                "detection_run_id": run_uuid,
                                                "source": detection_source,
                                                "status": DetectionStatus.UNREVIEWED,
                                                "confidence": confidence,
                                                "start_time": inference_result.start_time,
                                                "end_time": inference_result.end_time,
                                                "created_at": now,
                                                "updated_at": now,
                                            }
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
                if recordings_processed % _COMMIT_BATCH_SIZE == 0 and pending_annotation_dicts:
                    batch_count = len(pending_annotation_dicts)
                    async with session_factory() as db:
                        inserted = await _bulk_insert_annotations(db, pending_annotation_dicts)
                        await db.commit()

                    total_annotations += inserted
                    pending_annotation_dicts = []

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
        if pending_annotation_dicts:
            async with session_factory() as db:
                inserted = await _bulk_insert_annotations(db, pending_annotation_dicts)
                await db.commit()
            total_annotations += inserted

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
# Celery task definitions
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
