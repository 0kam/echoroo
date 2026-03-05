"""Celery worker tasks for ML-based audio species detection.

Tasks run outside FastAPI's async event loop, so async database calls
are executed via asyncio.run() in a sync Celery task context.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from echoroo.core.settings import get_settings
from echoroo.models.annotation import Annotation
from echoroo.models.detection_run import DetectionRun
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


def _get_engine_and_session_factory() -> (
    tuple[Any, async_sessionmaker[AsyncSession]]
):
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


async def _run_birdnet_detection(
    dataset_id: str,
    project_id: str,
    detection_run_id: str | None = None,
) -> dict[str, Any]:
    """Async implementation of BirdNET detection for a dataset.

    Creates a DetectionRun (or reuses an existing one), iterates over all
    recordings in the dataset, runs BirdNET analysis on each file, and
    persists the resulting Annotations.

    Args:
        dataset_id: Dataset UUID string.
        project_id: Project UUID string.
        detection_run_id: Optional existing DetectionRun UUID string to reuse
            (used for retry). If None, a new DetectionRun is created.

    Returns:
        Summary dict with detection_run_id, recordings_processed, total_annotations.
    """
    import birdnet

    from echoroo.ml.birdnet_wrapper import BirdNETWrapper

    settings = get_settings()
    engine, session_factory = _get_engine_and_session_factory()

    dataset_uuid = UUID(dataset_id)
    project_uuid = UUID(project_id)

    # Determine birdnet package version for run metadata
    birdnet_version = getattr(birdnet, "__version__", "unknown")

    try:
        # ------------------------------------------------------------------
        # Step 0: Load BirdNET settings from system configuration
        # ------------------------------------------------------------------
        async with session_factory() as db:
            setting_repo = SystemSettingRepository(db)
            birdnet_settings = await setting_repo.get_birdnet_settings()

        species_filter: str = str(birdnet_settings["species_filter"])
        min_conf: float = float(birdnet_settings["min_conf"])  # type: ignore[arg-type]
        logger.info(
            "BirdNET settings loaded: species_filter=%s, min_conf=%.2f",
            species_filter,
            min_conf,
        )

        # ------------------------------------------------------------------
        # Step 1: Create or reuse DetectionRun record
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)

            if detection_run_id is not None:
                # Reuse existing DetectionRun (retry path)
                run_uuid = UUID(detection_run_id)
                detection_run = await run_repo.get_by_id(run_uuid)
                if detection_run is None:
                    raise ValueError(f"DetectionRun not found: {detection_run_id}")
                logger.info(
                    "Reusing DetectionRun %s for dataset %s (retry)",
                    detection_run_id,
                    dataset_id,
                )
            else:
                # Create a new DetectionRun
                detection_run = DetectionRun(
                    project_id=project_uuid,
                    dataset_id=dataset_uuid,
                    model_name="birdnet",
                    model_version=birdnet_version,
                    parameters={"min_conf": min_conf, "species_filter": species_filter},
                    status=DetectionRunStatus.PENDING,
                )
                await run_repo.create(detection_run)
                await db.commit()
                logger.info(
                    "Created DetectionRun %s for dataset %s (birdnet %s)",
                    detection_run.id,
                    dataset_id,
                    birdnet_version,
                )
            run_id: UUID = detection_run.id

        # ------------------------------------------------------------------
        # Step 2: Transition DetectionRun to RUNNING
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            run = await run_repo.get_by_id(run_id)
            if run is None:
                raise ValueError(f"DetectionRun not found: {run_id}")
            run.status = DetectionRunStatus.RUNNING
            run.started_at = datetime.now(UTC)
            await run_repo.update(run)
            await db.commit()

        # ------------------------------------------------------------------
        # Step 3: Load all recordings for the dataset
        # ------------------------------------------------------------------
        async with session_factory() as db:
            result = await db.execute(
                select(Recording).where(Recording.dataset_id == dataset_uuid)
            )
            recordings = list(result.scalars().all())

        logger.info(
            "Starting BirdNET detection on %d recordings in dataset %s",
            len(recordings),
            dataset_id,
        )

        # ------------------------------------------------------------------
        # Step 4: Initialize AudioService and BirdNET wrapper
        # ------------------------------------------------------------------
        audio_service = AudioService(
            audio_root=settings.AUDIO_ROOT,
            s3_audio_cache_dir="/data/s3_audio_cache",
        )
        wrapper = BirdNETWrapper.get_instance()

        # ------------------------------------------------------------------
        # Step 4b: Compute geo species list (once per dataset if enabled)
        # ------------------------------------------------------------------
        custom_species_list: list[str] | None = None
        if species_filter == "birdnet_geo" and recordings:
            # Retrieve site h3_index from the first recording's dataset.site
            # (Recording.dataset is lazy="joined", Dataset.site is lazy="joined")
            first_recording = recordings[0]
            site = getattr(getattr(first_recording, "dataset", None), "site", None)
            h3_index: str | None = getattr(site, "h3_index", None)

            # Find first recording with a valid datetime for week calculation
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
                        "BirdNET geo filter: lat=%.4f, lon=%.4f, week=%d → %d species",
                        lat,
                        lon,
                        week,
                        len(custom_species_list),
                    )
                except Exception as geo_exc:  # noqa: BLE001
                    logger.warning(
                        "BirdNET geo filter failed (skipping filter): %s", geo_exc
                    )
                    custom_species_list = None
            else:
                logger.info(
                    "BirdNET geo filter requested but site h3_index=%s or week=%s unavailable; "
                    "skipping geo filter",
                    h3_index,
                    week,
                )

        total_annotations = 0
        recordings_processed = 0
        recordings_failed = 0
        pending_annotations: list[Annotation] = []

        # ------------------------------------------------------------------
        # Step 5: Process each recording
        # ------------------------------------------------------------------
        for recording in recordings:
            # Cancellation check: abort if run was externally set to FAILED
            async with session_factory() as db:
                run_repo = DetectionRunRepository(db)
                current_run = await run_repo.get_by_id(run_id)
                if current_run is not None and current_run.status == DetectionRunStatus.FAILED:
                    logger.warning("DetectionRun %s was cancelled, stopping processing", run_id)
                    return {
                        "detection_run_id": str(run_id),
                        "recordings_processed": recordings_processed,
                        "recordings_failed": recordings_failed,
                        "total_annotations": total_annotations,
                        "status": "cancelled",
                    }

            try:
                # Download from S3 to local cache if needed
                local_path = audio_service.ensure_file_local(recording.path)

                # Run BirdNET analysis — model-level failures propagate up and
                # abort the whole task (wrapper no longer swallows them).
                detections = wrapper.analyze_file(
                    file_path=local_path,
                    min_conf=min_conf,
                    custom_species_list=custom_species_list,
                )

                if detections:
                    # Resolve or create species tags and build Annotation objects
                    async with session_factory() as db:
                        tag_repo = TagRepository(db)
                        taxon_repo = TaxonRepository(db)
                        for detection in detections:
                            # Determine if this label represents a non-biological sound
                            is_non_bio = detection.common_name in NON_SPECIES_LABELS

                            # Get or create the global taxon record first
                            taxon = await taxon_repo.get_or_create_by_scientific_name(
                                scientific_name=detection.scientific_name,
                                common_name=detection.common_name,
                                is_non_biological=is_non_bio,
                            )

                            tag = await tag_repo.get_or_create_species(
                                project_id=project_uuid,
                                scientific_name=detection.scientific_name,
                                common_name=detection.common_name,
                                taxon_id=taxon.id,
                            )
                            await db.commit()

                            annotation = Annotation(
                                recording_id=recording.id,
                                tag_id=tag.id,
                                detection_run_id=run_id,
                                source=DetectionSource.BIRDNET,
                                status=DetectionStatus.UNREVIEWED,
                                confidence=detection.confidence,
                                start_time=detection.start_time,
                                end_time=detection.end_time,
                            )
                            pending_annotations.append(annotation)

                recordings_processed += 1

            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "BirdNET processing failed for recording %s (%s): %s",
                    recording.id,
                    recording.filename,
                    exc,
                )
                recordings_failed += 1
                recordings_processed += 1
                # Per-recording failure does not abort the whole run

            # ------------------------------------------------------------------
            # Step 6: Flush batch every _COMMIT_BATCH_SIZE recordings
            # ------------------------------------------------------------------
            if recordings_processed % _COMMIT_BATCH_SIZE == 0 and pending_annotations:
                batch_count = len(pending_annotations)
                async with session_factory() as db:
                    annotation_repo = AnnotationRepository(db)
                    await annotation_repo.create_batch(pending_annotations)
                    await db.commit()

                total_annotations += batch_count
                pending_annotations = []

                # Update annotation_count on DetectionRun
                async with session_factory() as db:
                    run_repo = DetectionRunRepository(db)
                    run = await run_repo.get_by_id(run_id)
                    if run is not None:
                        run.annotation_count = total_annotations
                        await run_repo.update(run)
                        await db.commit()

                logger.info(
                    "DetectionRun %s progress: %d/%d recordings, %d annotations so far",
                    run_id,
                    recordings_processed,
                    len(recordings),
                    total_annotations,
                )

        # ------------------------------------------------------------------
        # Step 7: Flush remaining annotations
        # ------------------------------------------------------------------
        if pending_annotations:
            remaining_count = len(pending_annotations)
            async with session_factory() as db:
                annotation_repo = AnnotationRepository(db)
                await annotation_repo.create_batch(pending_annotations)
                await db.commit()
            total_annotations += remaining_count

        # ------------------------------------------------------------------
        # Step 8: Mark DetectionRun as COMPLETED
        # ------------------------------------------------------------------
        async with session_factory() as db:
            run_repo = DetectionRunRepository(db)
            run = await run_repo.get_by_id(run_id)
            if run is not None:
                run.status = DetectionRunStatus.COMPLETED
                run.completed_at = datetime.now(UTC)
                run.annotation_count = total_annotations
                await run_repo.update(run)
                await db.commit()

        logger.info(
            "DetectionRun %s completed: %d recordings processed (%d failed), %d annotations created",
            run_id,
            recordings_processed,
            recordings_failed,
            total_annotations,
        )
        return {
            "detection_run_id": str(run_id),
            "recordings_processed": recordings_processed,
            "recordings_failed": recordings_failed,
            "total_annotations": total_annotations,
            "status": "completed",
        }

    finally:
        # Always release pooled connections when the task finishes (success or
        # failure).  Each task creates a new engine bound to a single-use event
        # loop, so the engine must be disposed here rather than relying on GC.
        await engine.dispose()


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
    time_limit=7200,      # 2 hour hard limit
    soft_time_limit=7000,  # ~1h 57m soft limit
)
def run_birdnet_detection(
    _self: Any,
    dataset_id: str,
    project_id: str,
    detection_run_id: str | None = None,
) -> dict[str, Any]:
    """Run BirdNET species detection on all recordings in a dataset.

    Creates a DetectionRun record (or reuses an existing one for retry),
    processes each recording through the BirdNET model, persists Annotation
    results, and marks the run as COMPLETED or FAILED.

    Per-recording failures are logged but do not abort the entire run. Detection
    is cancelled early if the run's status is externally set to FAILED.

    Args:
        dataset_id: Dataset UUID string to process.
        project_id: Project UUID string that owns the dataset.
        detection_run_id: Optional existing DetectionRun UUID string to reuse
            (used for retry). If None, a new DetectionRun is created.

    Returns:
        Summary dict with detection_run_id, recordings_processed, total_annotations.
    """
    logger.info(
        "Starting BirdNET detection task for dataset %s (project %s)",
        dataset_id,
        project_id,
    )
    # Set run_id_for_error before the try block so it's available in the except handler
    # even if the exception is raised before asyncio.run() returns a result.
    run_id_for_error: UUID | None = UUID(detection_run_id) if detection_run_id else None

    try:
        result: dict[str, Any] = asyncio.run(
            _run_birdnet_detection(dataset_id, project_id, detection_run_id)
        )
        # Update in case a new run was created (detection_run_id was None)
        if "detection_run_id" in result:
            run_id_for_error = UUID(result["detection_run_id"])
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "BirdNET detection failed for dataset %s: %s",
            dataset_id,
            exc,
        )
        if run_id_for_error is not None:
            with contextlib.suppress(Exception):
                asyncio.run(_mark_detection_run_failed(run_id_for_error, str(exc)))
        raise
