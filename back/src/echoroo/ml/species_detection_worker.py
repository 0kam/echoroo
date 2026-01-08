"""Species Detection Worker service for processing automatic species detection jobs.

This module provides a background worker that processes species detection jobs
from the database, runs BirdNET or Perch models, and stores results including
embeddings and predictions.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Generator
from uuid import UUID, uuid4

import numpy as np

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import exceptions, models, schemas
from echoroo.api import (
    clip_embeddings,
    clip_predictions,
    clips,
    datasets,
    model_runs,
    tags,
)
from echoroo.ml.base import InferenceEngine, InferenceResult, ModelLoader
from echoroo.ml.constants import is_non_species_label
from echoroo.ml.registry import ModelNotFoundError, ModelRegistry
from echoroo.ml.species_resolver import SpeciesInfo, SpeciesResolver
from echoroo.system.settings import get_settings

__all__ = [
    "SpeciesDetectionWorker",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Timing utilities for debug mode
# ---------------------------------------------------------------------------


@dataclass
class _TimingStats:
    """Container for timing statistics during job processing."""

    job_start: float = 0.0
    inference_total: float = 0.0
    store_total: float = 0.0
    get_recordings_total: float = 0.0
    recording_count: int = 0

    # Per-recording breakdown
    inference_per_recording: list[float] = field(default_factory=list)
    store_per_recording: list[float] = field(default_factory=list)

    # Detailed store breakdown
    store_clip_create: float = 0.0
    store_embedding_create: float = 0.0
    store_prediction_create: float = 0.0
    store_tag_lookup: float = 0.0
    store_tag_add: float = 0.0

    def log_summary(self, job_uuid: UUID) -> None:
        """Log timing summary for the job."""
        job_total = time.perf_counter() - self.job_start
        if job_total <= 0:
            return

        inference_pct = (self.inference_total / job_total) * 100
        store_pct = (self.store_total / job_total) * 100
        get_recordings_pct = (self.get_recordings_total / job_total) * 100

        logger.info("[TIMING] Job %s summary:", job_uuid)
        logger.info("[TIMING] process_job total: %.1fs", job_total)
        logger.info(
            "[TIMING] _run_inference: %.1fs (%.1f%%)",
            self.inference_total,
            inference_pct,
        )
        logger.info(
            "[TIMING] _store_result: %.1fs (%.1f%%)",
            self.store_total,
            store_pct,
        )
        logger.info(
            "[TIMING] _get_filtered_recordings: %.1fs (%.1f%%)",
            self.get_recordings_total,
            get_recordings_pct,
        )

        if self.recording_count > 0:
            avg_total = job_total / self.recording_count
            avg_inference = self.inference_total / self.recording_count
            avg_store = self.store_total / self.recording_count
            logger.info(
                "[TIMING] Per recording avg: %.2fs (inference: %.2fs, store: %.2fs)",
                avg_total,
                avg_inference,
                avg_store,
            )

        # Detailed store breakdown
        if self.store_total > 0:
            logger.info("[TIMING] _store_result breakdown:")
            logger.info(
                "[TIMING]   clip_create: %.1fs (%.1f%%)",
                self.store_clip_create,
                (self.store_clip_create / self.store_total) * 100,
            )
            logger.info(
                "[TIMING]   embedding_create: %.1fs (%.1f%%)",
                self.store_embedding_create,
                (self.store_embedding_create / self.store_total) * 100,
            )
            logger.info(
                "[TIMING]   prediction_create: %.1fs (%.1f%%)",
                self.store_prediction_create,
                (self.store_prediction_create / self.store_total) * 100,
            )
            logger.info(
                "[TIMING]   tag_lookup: %.1fs (%.1f%%)",
                self.store_tag_lookup,
                (self.store_tag_lookup / self.store_total) * 100,
            )
            logger.info(
                "[TIMING]   tag_add: %.1fs (%.1f%%)",
                self.store_tag_add,
                (self.store_tag_add / self.store_total) * 100,
            )


@contextmanager
def _timing_context(
    stats: _TimingStats | None,
    attr_name: str,
) -> Generator[None, None, None]:
    """Context manager for measuring elapsed time.

    Accumulates time into the specified attribute of the stats object.
    If stats is None (timing disabled), this is a no-op.

    Parameters
    ----------
    stats : _TimingStats | None
        Stats object to accumulate time into, or None if timing disabled.
    attr_name : str
        Name of the attribute to accumulate time into.

    Yields
    ------
    None
    """
    if stats is None:
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        current = getattr(stats, attr_name, 0.0)
        setattr(stats, attr_name, current + elapsed)

        # Also record per-recording times if applicable
        if attr_name == "inference_total":
            stats.inference_per_recording.append(elapsed)
        elif attr_name == "store_total":
            stats.store_per_recording.append(elapsed)


@dataclass
class _SpeciesSummary:
    gbif_taxon_id: str | None
    annotation_tag_id: int | None
    scientific_name: str
    vernacular_name: str | None
    detections: int = 0
    total_confidence: float = 0.0


class SpeciesDetectionWorker:
    """Background worker for processing foundation model runs.

    This worker polls the database for queued foundation model runs,
    processes them using BirdNET or Perch models, and stores results
    including embeddings and predictions.
    """

    def __init__(
        self,
        audio_dir: Path,
        model_dir: Path | None = None,
        poll_interval: float = 5.0,
        batch_size: int = 32,
        use_geo_filter: bool = True,
        gpu_batch_size: int = 16,
        feeders: int = 1,
        workers: int = 1,
    ):
        """Initialize the species detection worker.

        Parameters
        ----------
        audio_dir : Path
            Directory containing audio files.
        model_dir : Path | None, optional
            Directory for model files. Default is None.
        poll_interval : float, optional
            Seconds to wait between polling for new jobs. Default is 5.0.
        batch_size : int, optional
            Number of recordings to process before updating progress.
            Default is 32.
        use_geo_filter : bool, optional
            Deprecated. Species filters are applied explicitly after runs.
        gpu_batch_size : int, optional
            Batch size for GPU inference. Higher values use more GPU memory
            but improve throughput. Default is 16.
        feeders : int, optional
            Number of file reading processes for BirdNET inference.
            Controls parallel I/O for reading and preprocessing audio files.
            Default is 1.
        workers : int, optional
            Number of GPU inference workers for BirdNET.
            Usually 1 is sufficient unless you have multiple GPUs.
            Default is 1.
        """
        self._audio_dir = audio_dir
        self._model_dir = model_dir
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._use_geo_filter = use_geo_filter
        self._gpu_batch_size = gpu_batch_size
        self._feeders = feeders
        self._workers = workers
        self._running = False
        self._current_job: UUID | None = None
        self._cancel_requested = False
        self._task: asyncio.Task | None = None

        # Model loaders and engines (lazy loaded)
        self._loaders: dict[str, ModelLoader] = {}
        self._engines: dict[str, InferenceEngine] = {}

        # Prediction filters are applied explicitly after runs.
        self._run_species_stats: dict[UUID, dict[str, _SpeciesSummary]] = {}
        self._foundation_run_ids: dict[int, int] = {}

        # Species resolver for GBIF lookups
        self._species_resolver = SpeciesResolver()

        # Pending species for batch GBIF resolution at job end
        # Maps job UUID -> set of scientific names that need GBIF lookup
        self._pending_species: dict[UUID, set[str]] = {}
        # Maps scientific_name -> tag_id for updating after GBIF resolution
        self._species_tag_ids: dict[UUID, dict[str, int]] = {}

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running

    @property
    def current_job(self) -> UUID | None:
        """Get the UUID of the currently processing job."""
        return self._current_job

    async def _reset_orphaned_jobs(
        self,
        session: AsyncSession,
    ) -> None:
        """Reset runs that were left in 'running' state after worker restart.

        Runs can become orphaned if the worker was restarted while processing.
        This method:
        - Marks 100% complete runs as completed
        - Resets other running runs back to queued
        """
        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.status
            == models.FoundationModelRunStatus.RUNNING
        )
        result = await session.execute(stmt)
        orphaned_runs = result.scalars().all()

        for db_run in orphaned_runs:
            # Check if run was actually complete (progress=1 and all recordings processed)
            is_complete = (
                db_run.progress == 1.0
                and db_run.total_recordings is not None
                and db_run.processed_recordings == db_run.total_recordings
            )

            if is_complete:
                # Run was complete, just mark it as completed
                db_run.status = models.FoundationModelRunStatus.COMPLETED
                db_run.completed_on = datetime.datetime.now(datetime.UTC)
                logger.info(
                    "Marked orphaned run %s as completed (was 100%% done)",
                    db_run.uuid,
                )
            else:
                # Run was interrupted mid-processing, reset to queued
                db_run.status = models.FoundationModelRunStatus.QUEUED
                db_run.started_on = None
                db_run.progress = 0
                db_run.processed_recordings = 0
                logger.info(
                    "Reset orphaned run %s to queued (was %d%% done)",
                    db_run.uuid,
                    int((db_run.progress or 0) * 100),
                )

    async def start(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Start processing jobs."""
        if self._running:
            logger.warning("Species detection worker is already running")
            return

        self._running = True
        self._cancel_requested = False

        logger.info("Starting species detection worker")

        # Reset orphaned jobs that were interrupted during previous runs
        async with session_factory() as session:
            await self._reset_orphaned_jobs(session)
            await session.commit()

        self._task = asyncio.create_task(
            self._run_loop(session_factory),
            name="species_detection_worker",
        )

    async def stop(self) -> None:
        """Stop processing gracefully."""
        if not self._running:
            logger.warning("Species detection worker is not running")
            return

        logger.info("Stopping species detection worker")
        self._running = False

        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=60.0)
            except asyncio.TimeoutError:
                logger.warning("Worker did not stop in time, cancelling task")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

            self._task = None

        logger.info("Species detection worker stopped")

    async def _run_loop(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Run the main processing loop for jobs."""
        while self._running:
            try:
                async with session_factory() as session:
                    job = await self._get_next_job(session)

                    if job is not None:
                        self._current_job = job.uuid
                        try:
                            await self.process_job(session, job)
                        finally:
                            self._current_job = None
                    else:
                        await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.exception("Error in worker loop: %s", e)
                await asyncio.sleep(self._poll_interval)

    async def _get_next_job(
        self,
        session: AsyncSession,
    ) -> schemas.FoundationModelRun | None:
        """Get the next queued foundation model run from the database."""
        try:
            # Query for queued runs
            stmt = (
                select(models.FoundationModelRun)
                .where(
                    models.FoundationModelRun.status
                    == models.FoundationModelRunStatus.QUEUED
                )
                .order_by(models.FoundationModelRun.id)
                .limit(1)
            )
            result = await session.execute(stmt)
            db_run = result.scalar_one_or_none()

            if db_run is None:
                return None

            # Build schema manually
            return schemas.FoundationModelRun(
                uuid=db_run.uuid,
                id=db_run.id,
                foundation_model_id=db_run.foundation_model_id,
                dataset_id=db_run.dataset_id,
                requested_by_id=db_run.requested_by_id,
                name=db_run.name,
                model_name=db_run.model_name,
                model_version=db_run.model_version,
                overlap=db_run.overlap,
                locale=db_run.locale,
                use_metadata_filter=db_run.use_metadata_filter,
                custom_species_list=db_run.custom_species_list,
                status=db_run.status,
                confidence_threshold=db_run.confidence_threshold,
                scope=db_run.scope,
                progress=db_run.progress,
                total_recordings=db_run.total_recordings,
                processed_recordings=db_run.processed_recordings,
                total_clips=db_run.total_clips,
                total_detections=db_run.total_detections,
                started_on=db_run.started_on,
                completed_on=db_run.completed_on,
            )

        except Exception as e:
            logger.error("Failed to fetch queued runs: %s", e)
            return None

    def _is_timing_enabled(self) -> bool:
        """Check if timing debug mode is enabled via settings."""
        settings = get_settings()
        return settings.ml_debug_timing

    async def _is_job_cancelled(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> bool:
        """Check if the run has been cancelled in the database."""
        if job.id is None:
            return False
        # Refresh from DB to get the latest status
        stmt = select(models.FoundationModelRun.status).where(
            models.FoundationModelRun.id == job.id
        )
        result = await session.execute(stmt)
        status = result.scalar_one_or_none()
        return status == models.FoundationModelRunStatus.CANCELLED

    async def process_job(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> None:
        """Process a single foundation model run."""
        logger.info("Processing foundation model run %s", job.uuid)
        self._cancel_requested = False

        # Initialize timing stats if debug timing is enabled
        timing_stats: _TimingStats | None = None
        if self._is_timing_enabled():
            timing_stats = _TimingStats(job_start=time.perf_counter())
            logger.info("[TIMING] Debug timing enabled for run %s", job.uuid)

        # Initialize pending species collection for this run
        self._pending_species[job.uuid] = set()
        self._species_tag_ids[job.uuid] = {}

        if job.id is not None:
            self._foundation_run_ids[job.id] = job.id
            self._run_species_stats[job.uuid] = {}

        try:
            # Get or create model run
            model_run = await self._get_or_create_model_run(session, job)

            # Mark run as running
            await self._update_job_status(
                session,
                job,
                status=models.FoundationModelRunStatus.RUNNING,
                started_on=datetime.datetime.now(datetime.UTC),
                model_run_id=model_run.id,
            )
            await session.commit()

            # Get filtered recordings (with timing)
            with _timing_context(timing_stats, "get_recordings_total"):
                recording_list = await self._get_filtered_recordings(session, job)

            if not recording_list:
                logger.warning("No recordings found for job %s", job.uuid)
                await self._persist_species_summary(session, job)
                await self._update_job_status(
                    session,
                    job,
                    status=models.FoundationModelRunStatus.COMPLETED,
                    completed_on=datetime.datetime.now(datetime.UTC),
                )
                await session.commit()
                # Log timing summary even for empty runs
                if timing_stats is not None:
                    timing_stats.log_summary(job.uuid)
                return

            # Update total recordings
            await self._update_job_progress(
                session,
                job,
                total_recordings=len(recording_list),
            )
            await session.commit()

            # Track recording count for timing stats
            if timing_stats is not None:
                timing_stats.recording_count = len(recording_list)

            # Ensure model is loaded
            engine = self._ensure_model_loaded(job)

            # Two-phase batch processing to reduce GPU memory usage:
            # Phase 1: Generate embeddings for ALL files in one batch
            # Phase 2: Generate predictions for ALL files in one batch
            # This reduces TensorFlow initialization from (N files × 2) to just 2 times total
            total_clips = 0
            total_detections = 0

            # Collect all valid audio file paths
            recording_paths: list[tuple[schemas.Recording, Path]] = []
            for recording in recording_list:
                audio_path = self._audio_dir / recording.path
                if audio_path.exists():
                    recording_paths.append((recording, audio_path))
                else:
                    logger.warning(
                        "Audio file not found for recording %s: %s",
                        recording.uuid,
                        audio_path,
                    )

            if not recording_paths:
                logger.warning("No valid audio files found for run %s", job.uuid)
                return

            # CRITICAL: Sort recording_paths by file path to match BirdNET's internal sorting.
            # BirdNET sorts input files alphabetically before processing, so we must ensure
            # our file_index mapping matches BirdNET's order to avoid mismatched predictions.
            # See: https://github.com/your-org/echoroo/issues/XXX
            recording_paths.sort(key=lambda x: str(x[1]))
            logger.debug(
                "Sorted %d recordings by file path to match BirdNET processing order",
                len(recording_paths),
            )

            # Phase 1: Generate embeddings for all recordings in batch
            if job.run_embeddings:
                logger.info(
                    "Phase 1: Generating embeddings for %d recordings",
                    len(recording_paths),
                )

                # Collect file paths for batch processing
                file_paths = [str(path) for _, path in recording_paths]

                try:
                    # Run batch encode
                    embeddings_result = engine._model.encode(
                        file_paths,
                        device=self._get_device_setting(),
                        batch_size=self._gpu_batch_size,
                        n_feeders=self._feeders,
                        n_workers=self._workers,
                    )

                    # Store embeddings for each recording
                    for i, (recording, _) in enumerate(recording_paths):
                        # Check for cancellation
                        if self._cancel_requested or await self._is_job_cancelled(
                            session, job
                        ):
                            logger.info(
                                "Run %s cancelled during embeddings storage", job.uuid
                            )
                            await self._update_job_status(
                                session,
                                job,
                                status=models.FoundationModelRunStatus.CANCELLED,
                            )
                            await session.commit()
                            if timing_stats is not None:
                                timing_stats.recording_count = i
                                timing_stats.log_summary(job.uuid)
                            return

                        try:
                            # Store embeddings for this recording
                            clips_added = await self._store_embeddings_batch(
                                session,
                                recording,
                                model_run,
                                embeddings_result,
                                i,
                                job,
                            )
                            total_clips += clips_added
                        except Exception as e:
                            logger.error(
                                "Error storing embeddings for recording %s: %s",
                                recording.uuid,
                                e,
                                exc_info=True,
                            )
                            await session.rollback()

                        # Update progress (0-50% for embeddings phase)
                        progress = (i + 1) / len(recording_paths) * 0.5
                        await self._update_job_progress(
                            session,
                            job,
                            processed_recordings=i + 1,
                            total_clips=total_clips,
                            progress=progress,
                        )
                        await session.commit()

                except Exception as e:
                    logger.error(
                        "Error during batch embedding generation: %s", e, exc_info=True
                    )
                    await session.rollback()

            # Phase 2: Generate predictions for all recordings in batch
            if job.run_predictions:
                logger.info(
                    "Phase 2: Generating predictions for %d recordings",
                    len(recording_paths),
                )

                # Collect file paths for batch processing
                file_paths = [str(path) for _, path in recording_paths]

                try:
                    # Run batch predict
                    predictions_result = engine._model.predict(
                        file_paths,
                        device=self._get_device_setting(),
                        batch_size=self._gpu_batch_size,
                        n_feeders=self._feeders,
                        n_workers=self._workers,
                        top_k=10,
                        default_confidence_threshold=job.confidence_threshold,
                    )

                    # Store predictions for each recording
                    for i, (recording, _) in enumerate(recording_paths):
                        # Check for cancellation
                        if self._cancel_requested or await self._is_job_cancelled(
                            session, job
                        ):
                            logger.info(
                                "Run %s cancelled during predictions storage", job.uuid
                            )
                            await self._update_job_status(
                                session,
                                job,
                                status=models.FoundationModelRunStatus.CANCELLED,
                            )
                            await session.commit()
                            if timing_stats is not None:
                                timing_stats.recording_count = i
                                timing_stats.log_summary(job.uuid)
                            return

                        try:
                            # Store predictions for this recording
                            detections = await self._store_predictions_batch(
                                session,
                                recording,
                                model_run,
                                predictions_result,
                                i,
                                job,
                            )
                            total_detections += detections
                        except Exception as e:
                            logger.error(
                                "Error storing predictions for recording %s: %s",
                                recording.uuid,
                                e,
                                exc_info=True,
                            )
                            await session.rollback()

                        # Update progress (50-100% for predictions phase)
                        base_progress = 0.5 if job.run_embeddings else 0.0
                        progress = base_progress + (i + 1) / len(recording_paths) * 0.5
                        await self._update_job_progress(
                            session,
                            job,
                            processed_recordings=i + 1,
                            total_detections=total_detections,
                            progress=progress,
                        )
                        await session.commit()

                except Exception as e:
                    logger.error(
                        "Error during batch prediction generation: %s", e, exc_info=True
                    )
                    await session.rollback()

            # Resolve pending species via GBIF in batch
            await self._resolve_pending_species_batch(session, job)

            # Mark complete
            await self._persist_species_summary(session, job)
            await self._update_job_status(
                session,
                job,
                status=models.FoundationModelRunStatus.COMPLETED,
                completed_on=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()

            logger.info(
                "Run %s completed: %d clips, %d detections from %d recordings",
                job.uuid,
                total_clips,
                total_detections,
                len(recording_list),
            )

            # Log timing summary on successful completion
            if timing_stats is not None:
                timing_stats.log_summary(job.uuid)

        except Exception as e:
            logger.exception("Run %s failed: %s", job.uuid, e)
            try:
                # Rollback any failed transaction before updating status
                await session.rollback()
                await self._update_job_status(
                    session,
                    job,
                    status=models.FoundationModelRunStatus.FAILED,
                    error_message=str(e),
                )
                await session.commit()
            except Exception as commit_error:
                logger.error("Failed to update run status: %s", commit_error)
            # Log timing summary on failure
            if timing_stats is not None:
                timing_stats.log_summary(job.uuid)
        finally:
            if job.id is not None:
                self._foundation_run_ids.pop(job.id, None)
            self._run_species_stats.pop(job.uuid, None)
            self._pending_species.pop(job.uuid, None)
            self._species_tag_ids.pop(job.uuid, None)

    async def _get_or_create_model_run(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> schemas.ModelRun:
        """Get existing model run or create a new one for the foundation run."""
        # Include run UUID in version to ensure uniqueness per run
        # ModelRun has a unique constraint on (name, version)
        version_with_job = f"{job.model_version}-{job.uuid}"

        # Try to get existing model run first
        from sqlalchemy import select
        stmt = select(models.ModelRun).where(
            models.ModelRun.name == job.model_name,
            models.ModelRun.version == version_with_job,
        )
        result = await session.execute(stmt)
        existing = result.scalars().first()

        if existing:
            return schemas.ModelRun.model_validate(existing)

        # Create new model run
        description_parts = [
            f"Foundation model run {job.uuid}",
            f"threshold={job.confidence_threshold}",
            f"overlap={job.overlap}",
        ]
        if job.use_metadata_filter:
            description_parts.append("metadata_filter=deferred")
        if job.custom_species_list:
            description_parts.append(f"custom_species={len(job.custom_species_list)}")

        description = ", ".join(description_parts)

        return await model_runs.create(
            session,
            name=job.model_name,
            version=version_with_job,
            description=description,
        )

    async def _get_filtered_recordings(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> list[schemas.Recording]:
        """Get recordings based on run filters."""
        from sqlalchemy.orm import joinedload

        # Get dataset with relationships loaded
        stmt = (
            select(models.Dataset)
            .options(
                joinedload(models.Dataset.project),
                joinedload(models.Dataset.primary_site),
                joinedload(models.Dataset.primary_recorder),
                joinedload(models.Dataset.license),
            )
            .where(models.Dataset.id == job.dataset_id)
        )
        dataset_obj = await session.scalar(stmt)
        if dataset_obj is None:
            return []

        # Create a minimal dataset schema for get_recordings
        # We only need uuid and id for the recordings query
        # Note: recording_count is a computed column property, use getattr for type safety
        dataset_schema = schemas.Dataset(
            uuid=dataset_obj.uuid,
            id=dataset_obj.id,
            audio_dir=dataset_obj.audio_dir,
            name=dataset_obj.name,
            description=dataset_obj.description,
            recording_count=getattr(dataset_obj, "recording_count", 0),
            visibility=dataset_obj.visibility,
            created_by_id=dataset_obj.created_by_id,
            project_id=dataset_obj.project_id,
            primary_site_id=dataset_obj.primary_site_id,
            primary_recorder_id=dataset_obj.primary_recorder_id,
            license_id=dataset_obj.license_id,
        )

        # Get all recordings for the dataset first
        all_recordings, _ = await datasets.get_recordings(
            session,
            dataset_schema,
            limit=-1,
        )

        recording_list = list(all_recordings)

        # Apply filters if specified from scope
        filters = job.scope
        if filters:
            # Date filters
            date_from = filters.get("date_from")
            date_to = filters.get("date_to")
            if date_from or date_to:
                from datetime import date

                filtered = []
                for rec in recording_list:
                    if rec.date is None:
                        continue
                    if date_from and rec.date < date.fromisoformat(date_from):
                        continue
                    if date_to and rec.date > date.fromisoformat(date_to):
                        continue
                    filtered.append(rec)
                recording_list = filtered

            # H3 index filters
            h3_indices = filters.get("h3_indices")
            if h3_indices:
                recording_list = [
                    rec
                    for rec in recording_list
                    if rec.h3_index and rec.h3_index in h3_indices
                ]

            # Specific recording UUIDs
            recording_uuids = filters.get("recording_uuids")
            if recording_uuids:
                uuid_set = set(
                    UUID(u) if isinstance(u, str) else u for u in recording_uuids
                )
                recording_list = [
                    rec for rec in recording_list if rec.uuid in uuid_set
                ]

        return recording_list

    def _get_device_setting(self) -> str:
        """Get the device setting from application configuration.

        Returns
        -------
        str
            Device to use for inference ("GPU" or "CPU").
        """
        settings = get_settings()
        if not settings.ml_use_gpu:
            return "CPU"
        return settings.ml_gpu_device

    def _ensure_model_loaded(
        self,
        job: schemas.FoundationModelRun,
    ) -> InferenceEngine:
        """Ensure the required model is loaded.

        Models are cached by name only. Locale-specific vernacular names
        are now handled by SpeciesResolver after inference.
        """
        model_name = job.model_name
        cache_key = model_name

        if cache_key in self._engines:
            engine = self._engines[cache_key]
            if hasattr(engine, "confidence_threshold"):
                engine.confidence_threshold = job.confidence_threshold  # type: ignore[attr-defined]
            return engine

        try:
            loader_class = ModelRegistry.get_loader_class(model_name)
            engine_class = ModelRegistry.get_engine_class(model_name)
        except ModelNotFoundError as e:
            available = ModelRegistry.available_models()
            raise ValueError(
                f"Unknown model: {model_name}. "
                f"Available models: {', '.join(available) if available else 'none'}"
            ) from e

        # Get device setting from configuration
        device = self._get_device_setting()
        logger.info(
            "Loading %s model (device: %s, gpu_batch_size: %d, feeders: %d, workers: %d)",
            model_name,
            device,
            self._gpu_batch_size,
            self._feeders,
            self._workers,
        )

        # Create loader with device parameter
        loader = loader_class(model_dir=self._model_dir, device=device)  # type: ignore[call-arg]
        loader.load()
        self._loaders[cache_key] = loader

        engine = engine_class(
            loader,
            confidence_threshold=job.confidence_threshold,  # type: ignore[call-arg]
            device=device,  # type: ignore[call-arg]
            batch_size=self._gpu_batch_size,  # type: ignore[call-arg]
            feeders=self._feeders,  # type: ignore[call-arg]
            workers=self._workers,  # type: ignore[call-arg]
        )
        self._engines[cache_key] = engine

        return engine

    async def _process_recording_timed(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        engine: InferenceEngine,
        job: schemas.FoundationModelRun,
        timing_stats: _TimingStats | None,
    ) -> tuple[int, int]:
        """Process a single recording with optional timing measurement.

        This wrapper adds timing measurement around inference and storage
        operations when timing_stats is provided.

        Parameters
        ----------
        session
            Database session.
        recording
            Recording to process.
        model_run
            Model run for this job.
        engine
            Inference engine to use.
        job
            Species detection job configuration.
        timing_stats
            Timing stats object for accumulation, or None if timing disabled.

        Returns
        -------
        tuple[int, int]
            (clips_count, detections_count)
        """
        logger.debug("Processing recording %s", recording.uuid)

        audio_path = self._audio_dir / recording.path

        if not audio_path.exists():
            logger.warning("Audio file not found: %s", audio_path)
            return 0, 0

        # Run inference (with timing)
        try:
            with _timing_context(timing_stats, "inference_total"):
                results = await self._run_inference(engine, audio_path, job.overlap)
        except Exception as e:
            logger.error("Inference failed for %s: %s", recording.uuid, e)
            return 0, 0

        if not results:
            return 0, 0

        # Check for cancellation before storage
        if self._cancel_requested:
            return 0, 0

        # Store all results in bulk for better performance (with timing)
        with _timing_context(timing_stats, "store_total"):
            clips_count, detections_count = await self._store_results_bulk(
                session,
                recording,
                model_run,
                results,
                job,
            )

        return clips_count, detections_count

    async def _process_recording(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        engine: InferenceEngine,
        job: schemas.FoundationModelRun,
    ) -> tuple[int, int]:
        """Process a single recording. Returns (clips_count, detections_count).

        Note: This method is kept for backwards compatibility.
        For timed processing, use _process_recording_timed instead.
        """
        return await self._process_recording_timed(
            session,
            recording,
            model_run,
            engine,
            job,
            timing_stats=None,
        )

    async def _store_results_bulk(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        results: list[InferenceResult],
        job: schemas.FoundationModelRun,
    ) -> tuple[int, int]:
        """Store inference results in bulk for better performance.

        This method batches all DB operations to minimize round trips:
        1. Create all clips in bulk
        2. Insert all embeddings in bulk
        3. Create predictions and tags in bulk

        Parameters
        ----------
        session
            Database session.
        recording
            Recording being processed.
        model_run
            Model run for this job.
        results
            List of inference results from the model.
        job
            Species detection job configuration.

        Returns
        -------
        tuple[int, int]
            (clips_count, detections_count)
        """
        if not results:
            return 0, 0

        # Step 1: Create all clips in bulk using pg_insert
        now = datetime.datetime.now(datetime.timezone.utc)
        clips_data = [
            dict(
                uuid=uuid4(),
                recording_id=recording.id,
                start_time=r.start_time,
                end_time=r.end_time,
                created_on=now,
            )
            for r in results
        ]

        # Insert clips with ON CONFLICT DO NOTHING
        stmt = pg_insert(models.Clip).values(clips_data)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["recording_id", "start_time", "end_time"]
        )
        await session.execute(stmt)
        await session.flush()

        # Fetch clip IDs for all time ranges (including pre-existing ones)
        time_ranges = [(r.start_time, r.end_time) for r in results]
        clip_query = select(
            models.Clip.id,
            models.Clip.start_time,
            models.Clip.end_time,
        ).where(
            models.Clip.recording_id == recording.id,
            tuple_(models.Clip.start_time, models.Clip.end_time).in_(time_ranges),
        )
        clip_rows = await session.execute(clip_query)

        # Build a mapping from (start_time, end_time) -> clip_id
        clip_map: dict[tuple[float, float], int] = {
            (row.start_time, row.end_time): row.id for row in clip_rows
        }

        # Step 2: Bulk insert embeddings
        now = datetime.datetime.now(datetime.timezone.utc)
        embeddings_data = []
        for result in results:
            clip_id = clip_map.get((result.start_time, result.end_time))
            if clip_id is None:
                continue

            # Pass numpy array directly to pgvector (49x faster than .tolist())
            embeddings_data.append(
                dict(
                    uuid=uuid4(),
                    clip_id=clip_id,
                    model_run_id=model_run.id,
                    embedding=result.embedding,  # numpy array → pgvector handles it
                    created_on=now,
                )
            )

        if embeddings_data:
            # Use ON CONFLICT DO NOTHING to handle duplicates gracefully
            stmt = pg_insert(models.ClipEmbedding).values(embeddings_data)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["clip_id", "model_run_id"]
            )
            await session.execute(stmt)
            await session.flush()

        # Step 3: Prepare species tags in batch (N+1 prevention)
        # Collect all unique species labels first
        all_species_labels: set[str] = set()
        for result in results:
            if result.predictions:
                for species_label, _ in result.predictions:
                    all_species_labels.add(species_label)

        # Pre-resolve/create all species tags in batch
        species_tag_cache: dict[str, tuple[schemas.Tag, str, str | None, str | None]] = {}

        # Parse all species labels first
        label_to_parsed: dict[str, tuple[str, str | None]] = {}
        for species_label in all_species_labels:
            scientific_name, common_name = self._parse_species_label(species_label)
            label_to_parsed[species_label] = (scientific_name, common_name)

        # Collect all unique (key, value) pairs for batch lookup
        tag_keys_values: list[tuple[str, str]] = [
            ("species", scientific_name)
            for scientific_name, _ in label_to_parsed.values()
        ]

        # Batch fetch existing tags
        if tag_keys_values:
            tag_query = select(models.Tag).where(
                tuple_(models.Tag.key, models.Tag.value).in_(tag_keys_values)
            )
            tag_rows = await session.execute(tag_query)
            existing_tags = {
                (tag.key, tag.value): schemas.Tag.model_validate(tag)
                for tag in tag_rows.scalars().all()
            }
        else:
            existing_tags = {}

        # Create missing tags in batch
        tags_to_create: list[dict] = []
        for _species_label, (scientific_name, common_name) in label_to_parsed.items():
            tag_key = ("species", scientific_name)

            # Collect all species (not just new ones) for batch GBIF resolution at job end
            # This ensures vernacular names are resolved even for existing tags
            if not is_non_species_label(scientific_name, common_name):
                if job.uuid in self._pending_species:
                    self._pending_species[job.uuid].add(scientific_name)

            if tag_key not in existing_tags:
                canonical = common_name or scientific_name
                tags_to_create.append({
                    "key": "species",
                    "value": scientific_name,
                    "canonical_name": canonical,
                    "created_on": now,
                })

        # Bulk insert missing tags
        if tags_to_create:
            stmt = pg_insert(models.Tag).values(tags_to_create)
            stmt = stmt.on_conflict_do_nothing(index_elements=["key", "value"])
            stmt = stmt.returning(models.Tag)
            result = await session.execute(stmt)
            await session.flush()

            # Add newly created tags to cache
            for tag in result.scalars().all():
                existing_tags[("species", tag.value)] = schemas.Tag.model_validate(tag)

        # Build final cache
        for species_label, (scientific_name, common_name) in label_to_parsed.items():
            tag = existing_tags.get(("species", scientific_name))
            if tag:
                gbif_taxon_id = None  # Deferred to batch resolution
                species_tag_cache[species_label] = (tag, scientific_name, common_name, gbif_taxon_id)

        # Step 4: Create predictions and prediction tags in bulk
        detections_count = 0
        predictions_to_create: list[dict] = []
        prediction_tags_to_create: list[tuple[int, int, float, str]] = []
        model_run_predictions_to_create: list[dict] = []

        # First pass: create clip predictions
        clip_to_filtered_predictions: dict[int, list[tuple[str, float]]] = {}

        for result in results:
            if not result.predictions:
                continue

            clip_id = clip_map.get((result.start_time, result.end_time))
            if clip_id is None:
                continue

            # Filter predictions by custom species list if configured
            filtered_predictions = result.predictions
            if job.custom_species_list:
                filtered_predictions = [
                    (species, conf)
                    for species, conf in filtered_predictions
                    if self._matches_custom_species(species, job.custom_species_list)
                ]

            if filtered_predictions:
                predictions_to_create.append(dict(uuid=uuid4(), clip_id=clip_id, created_on=now))
                clip_to_filtered_predictions[clip_id] = filtered_predictions

        # Bulk insert clip predictions
        if predictions_to_create:
            # Insert and get back the created predictions
            stmt = (
                pg_insert(models.ClipPrediction)
                .values(predictions_to_create)
                .returning(models.ClipPrediction.id, models.ClipPrediction.clip_id)
            )
            result_rows = await session.execute(stmt)
            created_predictions = result_rows.fetchall()

            # Map clip_id -> prediction_id
            clip_to_prediction_id: dict[int, int] = {
                row.clip_id: row.id for row in created_predictions
            }

            # Prepare prediction tags and model run predictions
            for clip_id, filtered_predictions in clip_to_filtered_predictions.items():
                prediction_id = clip_to_prediction_id.get(clip_id)
                if prediction_id is None:
                    continue

                model_run_predictions_to_create.append(
                    dict(model_run_id=model_run.id, clip_prediction_id=prediction_id, created_on=now)
                )

                for species_label, confidence in filtered_predictions:
                    cached = species_tag_cache.get(species_label)
                    if cached is None:
                        continue

                    tag, scientific_name, common_name, gbif_taxon_id = cached
                    if tag.id is None:
                        continue

                    prediction_tags_to_create.append(
                        (prediction_id, tag.id, confidence, species_label)
                    )

                    # Record species summary for foundation model tracking
                    self._record_species_summary(
                        job,
                        tag,
                        scientific_name,
                        common_name,
                        gbif_taxon_id,
                        confidence,
                    )
                    detections_count += 1

            # Bulk insert model run predictions
            if model_run_predictions_to_create:
                stmt = pg_insert(models.ModelRunPrediction).values(
                    model_run_predictions_to_create
                )
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

            # Bulk insert prediction tags
            if prediction_tags_to_create:
                tags_data = [
                    dict(
                        clip_prediction_id=pred_id,
                        tag_id=tag_id,
                        score=score,
                        created_on=now,
                    )
                    for pred_id, tag_id, score, _ in prediction_tags_to_create
                ]
                stmt = pg_insert(models.ClipPredictionTag).values(tags_data)
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

            await session.flush()

        clips_count = len(clip_map)
        return clips_count, detections_count

    async def _run_inference(
        self,
        engine: InferenceEngine,
        audio_path: Path,
        overlap: float,
    ) -> list[InferenceResult]:
        """Run inference on an audio file.

        Note: We run inference in a thread pool to avoid blocking the asyncio
        event loop, especially for Perch which can take a long time.
        BirdNET/Perch handles internal parallelism via multiprocessing.
        """
        spec = engine.specification
        overlap_seconds = overlap * spec.segment_duration

        logger.info("Starting inference on %s (overlap=%.2f)", audio_path, overlap_seconds)

        start_time = time.time()

        # Run in thread pool to avoid blocking asyncio event loop
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,  # Use default ThreadPoolExecutor
            engine.predict_file,
            audio_path,
            overlap_seconds,
        )

        elapsed = time.time() - start_time
        logger.info("Inference completed in %.2fs, got %d results", elapsed, len(results))

        return results

    async def _store_result(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        result: InferenceResult,
        job: schemas.FoundationModelRun,
        timing_stats: _TimingStats | None = None,
    ) -> tuple[int, int]:
        """Store inference result using API-based approach.

        Returns (clips_count, detections_count).
        """
        # Get or create clip
        t0 = time.perf_counter()
        clip = await self._get_or_create_clip(
            session,
            recording,
            result.start_time,
            result.end_time,
        )
        if timing_stats:
            timing_stats.store_clip_create += time.perf_counter() - t0

        # Store embedding
        t0 = time.perf_counter()
        embedding_list = result.embedding.tolist()
        await clip_embeddings.create(
            session,
            clip=clip,
            model_run=model_run,
            embedding=embedding_list,
        )
        if timing_stats:
            timing_stats.store_embedding_create += time.perf_counter() - t0

        clips_created = 1
        detections_created = 0

        # Store predictions if available
        if result.predictions:
            filtered_predictions = result.predictions
            if job.custom_species_list:
                filtered_predictions = [
                    (species, conf)
                    for species, conf in filtered_predictions
                    if self._matches_custom_species(species, job.custom_species_list)
                ]

            if filtered_predictions:
                # Create clip prediction
                t0 = time.perf_counter()
                clip_pred = await clip_predictions.create(session, clip=clip)

                # Link to model run
                await model_runs.add_clip_prediction(session, model_run, clip_pred)
                if timing_stats:
                    timing_stats.store_prediction_create += time.perf_counter() - t0

                # Add tags for each species prediction
                for species_label, confidence in filtered_predictions:
                    t0 = time.perf_counter()
                    tag, scientific_name, common_name, gbif_taxon_id = (
                        await self._get_or_create_species_tag(
                            session,
                            species_label,
                            job.uuid,
                        )
                    )
                    if timing_stats:
                        timing_stats.store_tag_lookup += time.perf_counter() - t0

                    t0 = time.perf_counter()
                    try:
                        clip_pred = await clip_predictions.add_tag(
                            session,
                            clip_pred,
                            tag,
                            score=confidence,
                        )
                    except exceptions.DuplicateObjectError:
                        # Tag already exists on this prediction, skip
                        pass
                    if timing_stats:
                        timing_stats.store_tag_add += time.perf_counter() - t0

                    self._record_species_summary(
                        job,
                        tag,
                        scientific_name,
                        common_name,
                        gbif_taxon_id,
                        confidence,
                    )
                    detections_created += 1

        return clips_created, detections_created

    def _matches_custom_species(
        self,
        species_label: str,
        custom_list: list[str],
    ) -> bool:
        """Check if species matches custom list."""
        scientific_name = (
            species_label.split("_")[0] if "_" in species_label else species_label
        )
        return species_label in custom_list or scientific_name in custom_list

    async def _get_or_create_species_tag(
        self,
        session: AsyncSession,
        species_label: str,
        job_uuid: UUID,
    ) -> tuple[schemas.Tag, str, str | None, str | None]:
        """Get or create a species tag.

        During inference, GBIF lookup is deferred. Species names are collected
        and resolved in batch at job completion for better performance.

        Non-species labels (e.g., "Engine_Engine", "Dog_Dog") are detected
        and excluded from GBIF resolution to prevent false matches.
        """
        scientific_name, common_name = self._parse_species_label(species_label)

        # Skip GBIF resolution for non-species labels (environmental sounds)
        if is_non_species_label(scientific_name, common_name):
            logger.debug(
                "Skipping GBIF resolution for non-species label: %s",
                species_label,
            )
            tag = await tags.get_or_create(
                session,
                key="species",
                value=scientific_name,
                canonical_name=common_name or scientific_name,
            )
            return tag, scientific_name, common_name, None

        # Defer GBIF lookup - use scientific name as temporary tag value
        # GBIF resolution with vernacular name is done in batch at job completion
        resolved_name = scientific_name
        tag_value = scientific_name
        gbif_taxon_id = None

        # Collect for batch resolution at job end
        if job_uuid in self._pending_species:
            self._pending_species[job_uuid].add(scientific_name)

        tag = await tags.get_or_create(
            session,
            key="species",
            value=tag_value,
            canonical_name=resolved_name,
        )

        return tag, resolved_name, common_name, gbif_taxon_id

    def _parse_species_label(self, label: str) -> tuple[str, str | None]:
        """Split BirdNET label into scientific and common names."""
        parts = label.split("_", 1)
        scientific = parts[0] if parts else label
        scientific = scientific.replace("_", " ").strip()
        common = parts[1].replace("_", " ").strip() if len(parts) > 1 else None
        return scientific, common or None

    async def _resolve_gbif_taxon(
        self,
        session: AsyncSession,
        scientific_name: str,
        locale: str = "ja",
    ) -> tuple[str | None, str | None, str | None]:
        """Resolve GBIF taxon id and vernacular name for a scientific name.

        Parameters
        ----------
        session : AsyncSession
            Database session for cache operations.
        scientific_name : str
            The scientific name to resolve.
        locale : str, optional
            Locale for vernacular name (e.g., "ja", "en"). Default is "ja".

        Returns
        -------
        tuple[str | None, str | None, str | None]
            Tuple of (usage_key, canonical_name, vernacular_name).
        """
        # Delegate to SpeciesResolver
        info: SpeciesInfo = await self._species_resolver.resolve(
            session,
            scientific_name,
            locale=locale,
        )
        return info.gbif_taxon_id, info.canonical_name, info.vernacular_name

    async def _resolve_pending_species_batch(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> None:
        """Resolve pending species names via GBIF API in batch.

        This is called at job completion to resolve all species names
        that were deferred during inference for better performance.
        Also fetches vernacular names from GBIF and updates species stats.
        """
        pending = self._pending_species.get(job.uuid, set())
        if not pending:
            logger.debug("No pending species to resolve for job %s", job.uuid)
            return

        # Extract base locale (e.g., "en_us" -> "en", "ja" -> "ja")
        locale = job.locale.split("_")[0] if job.locale else "ja"

        logger.info(
            "Resolving %d species via GBIF for job %s (locale=%s)",
            len(pending),
            job.uuid,
            locale,
        )

        # Use SpeciesResolver batch resolution
        results: dict[str, SpeciesInfo] = await self._species_resolver.resolve_batch(
            session,
            list(pending),
            locale=locale,
        )

        # Update tags with GBIF information
        for scientific_name, info in results.items():
            try:
                # Update existing tag with GBIF info (including vernacular name)
                if info.gbif_taxon_id and info.gbif_taxon_id != scientific_name:
                    # GBIF ID differs from scientific name - update tag value
                    await self._update_species_tag(
                        session,
                        old_value=scientific_name,
                        new_value=info.gbif_taxon_id,
                        canonical_name=info.canonical_name,
                        vernacular_name=info.vernacular_name,
                    )
                else:
                    # GBIF ID matches scientific name - only update vernacular name if present
                    await self._update_tag_vernacular_name(
                        session,
                        tag_value=scientific_name,
                        vernacular_name=info.vernacular_name,
                    )

            except Exception as e:
                logger.warning(
                    "Failed to update tag for %s: %s",
                    scientific_name,
                    e,
                )
                # Rollback the failed transaction before continuing
                await session.rollback()

        # Update species stats with vernacular names
        await self._update_species_stats_with_vernacular(job, locale, results)

        await session.commit()
        logger.info("GBIF resolution completed for job %s", job.uuid)

    async def _update_species_tag(
        self,
        session: AsyncSession,
        old_value: str,
        new_value: str,
        canonical_name: str,
        vernacular_name: str | None = None,
    ) -> None:
        """Update a species tag with resolved GBIF information."""
        # Find the tag with the old value
        stmt = select(models.Tag).where(
            models.Tag.key == "species",
            models.Tag.value == old_value,
        )
        result = await session.execute(stmt)
        tag = result.scalar_one_or_none()

        if tag is None:
            return

        # Check if a tag with the new value already exists
        stmt_new = select(models.Tag).where(
            models.Tag.key == "species",
            models.Tag.value == new_value,
        )
        result_new = await session.execute(stmt_new)
        existing_tag = result_new.scalar_one_or_none()

        if existing_tag is not None:
            # Tag with GBIF ID already exists, merge references
            # Update all clip_prediction_tags to point to the existing tag
            from sqlalchemy import update
            await session.execute(
                update(models.ClipPredictionTag)
                .where(models.ClipPredictionTag.tag_id == tag.id)
                .values(tag_id=existing_tag.id)
            )
            # Update vernacular_name on existing tag if we have a new one
            if vernacular_name and not existing_tag.vernacular_name:
                existing_tag.vernacular_name = vernacular_name
            # Delete the old tag
            await session.delete(tag)
        else:
            # Update the existing tag with GBIF info
            tag.value = new_value
            tag.canonical_name = canonical_name
            tag.vernacular_name = vernacular_name

        await session.flush()

    async def _update_tag_vernacular_name(
        self,
        session: AsyncSession,
        tag_value: str,
        vernacular_name: str | None,
    ) -> None:
        """Update only the vernacular_name of an existing tag.

        This is used when the GBIF taxon ID matches the scientific name,
        but we still want to update the vernacular name.
        """
        if not vernacular_name:
            return

        # Find the tag with this value
        stmt = select(models.Tag).where(
            models.Tag.key == "species",
            models.Tag.value == tag_value,
        )
        result = await session.execute(stmt)
        tag = result.scalar_one_or_none()

        if tag is None:
            return

        # Update vernacular name if not already set or if different
        if not tag.vernacular_name or tag.vernacular_name != vernacular_name:
            tag.vernacular_name = vernacular_name
            logger.debug(
                "Updated vernacular name for tag '%s': %s",
                tag_value,
                vernacular_name,
            )

        await session.flush()

    async def _update_species_stats_with_vernacular(
        self,
        job: schemas.FoundationModelRun,
        locale: str,
        resolved_species: dict[str, SpeciesInfo],
    ) -> None:
        """Update species stats with vernacular names from resolved species.

        This is called after GBIF resolution to update the common_name_ja
        field in species stats with the vernacular names fetched from GBIF.
        """
        stats_map = self._run_species_stats.get(job.uuid)
        if stats_map is None:
            return

        for summary in stats_map.values():
            # Look up vernacular name in resolved species results
            info = resolved_species.get(summary.scientific_name)
            if info and info.vernacular_name:
                summary.vernacular_name = info.vernacular_name

    def _record_species_summary(
        self,
        job: schemas.FoundationModelRun,
        tag: schemas.Tag,
        scientific_name: str,
        common_name: str | None,
        gbif_taxon_id: str | None,
        confidence: float,
    ) -> None:
        """Track per-species stats for foundation model runs."""
        stats_map = self._run_species_stats.get(job.uuid)
        if stats_map is None:
            return

        key = str(tag.id or tag.value)
        summary = stats_map.get(key)
        if summary is None:
            summary = _SpeciesSummary(
                gbif_taxon_id=gbif_taxon_id or tag.value,
                annotation_tag_id=tag.id,
                scientific_name=scientific_name,
                vernacular_name=common_name,
            )
            stats_map[key] = summary

        summary.detections += 1
        summary.total_confidence += confidence

    async def _persist_species_summary(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> None:
        """Write aggregated species stats to foundation model tables."""
        stats_map = self._run_species_stats.get(job.uuid)
        if not stats_map:
            return

        run = await self._load_tracked_run(session, job)
        if run is None:
            return

        await session.execute(
            delete(models.FoundationModelRunSpecies).where(
                models.FoundationModelRunSpecies.foundation_model_run_id == run.id,
            )
        )

        # Collect all tag IDs that we want to reference
        tag_ids_to_check = [
            s.annotation_tag_id for s in stats_map.values()
            if s.annotation_tag_id is not None
        ]

        # Verify which tag IDs still exist (some may have been deleted during GBIF merge)
        valid_tag_ids: set[int] = set()
        if tag_ids_to_check:
            stmt = select(models.Tag.id).where(models.Tag.id.in_(tag_ids_to_check))
            result = await session.execute(stmt)
            valid_tag_ids = {row[0] for row in result.fetchall()}

        total_detections = 0
        for summary in stats_map.values():
            if summary.detections == 0:
                continue
            avg_conf = summary.total_confidence / summary.detections

            # Only use annotation_tag_id if it still exists in the database
            tag_id = summary.annotation_tag_id
            if tag_id is not None and tag_id not in valid_tag_ids:
                tag_id = None

            session.add(
                models.FoundationModelRunSpecies(
                    foundation_model_run_id=run.id,
                    gbif_taxon_id=summary.gbif_taxon_id,
                    annotation_tag_id=tag_id,
                    scientific_name=summary.scientific_name,
                    vernacular_name=summary.vernacular_name,
                    detection_count=summary.detections,
                    avg_confidence=avg_conf,
                )
            )
            total_detections += summary.detections

        run.summary = {
            "unique_species": len(stats_map),
            "total_detections": total_detections,
        }

        await session.flush()

    async def _load_tracked_run(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
    ) -> models.FoundationModelRun | None:
        """Load the foundation model run for this job."""
        if job.id is None:
            return None
        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.id == job.id,
        )
        return await session.scalar(stmt)

    async def _update_job_status(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
        *,
        status: models.FoundationModelRunStatus | None = None,
        started_on: datetime.datetime | None = None,
        completed_on: datetime.datetime | None = None,
        error_message: str | None = None,
        model_run_id: int | None = None,
    ) -> None:
        """Update run status in database."""
        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.uuid == job.uuid
        )
        result = await session.execute(stmt)
        db_run = result.scalar_one()

        if status is not None:
            db_run.status = status
        if started_on is not None:
            db_run.started_on = started_on
        if completed_on is not None:
            db_run.completed_on = completed_on
        if error_message is not None:
            db_run.error = {"message": error_message}
        if model_run_id is not None:
            db_run.model_run_id = model_run_id

        await session.flush()

    async def _update_job_progress(
        self,
        session: AsyncSession,
        job: schemas.FoundationModelRun,
        *,
        total_recordings: int | None = None,
        processed_recordings: int | None = None,
        total_clips: int | None = None,
        total_detections: int | None = None,
        progress: float | None = None,
    ) -> None:
        """Update run progress in database."""
        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.uuid == job.uuid
        )
        result = await session.execute(stmt)
        db_run = result.scalar_one()

        if total_recordings is not None:
            db_run.total_recordings = total_recordings
        if processed_recordings is not None:
            db_run.processed_recordings = processed_recordings
        if total_clips is not None:
            db_run.total_clips = total_clips
        if total_detections is not None:
            db_run.total_detections = total_detections
        if progress is not None:
            db_run.progress = progress

        await session.flush()

    async def cancel_current_job(self) -> None:
        """Request cancellation of the current job."""
        if self._current_job is not None:
            logger.info("Cancellation requested for job %s", self._current_job)
            self._cancel_requested = True
        else:
            logger.warning("No job currently running to cancel")

    async def _get_or_create_clip(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        start_time: float,
        end_time: float,
    ) -> schemas.Clip:
        """Get existing clip or create a new one."""
        try:
            return await clips.create(
                session,
                recording=recording,
                start_time=start_time,
                end_time=end_time,
            )
        except exceptions.DuplicateObjectError:
            # Clip already exists, fetch it
            from sqlalchemy.orm import joinedload

            stmt = (
                select(models.Clip)
                .options(
                    joinedload(models.Clip.recording),
                    joinedload(models.Clip.features).joinedload(
                        models.ClipFeature.feature_name
                    ),
                )
                .where(
                    models.Clip.recording_id == recording.id,
                    models.Clip.start_time == start_time,
                    models.Clip.end_time == end_time,
                )
            )
            result = await session.execute(stmt)
            db_clip = result.unique().scalar_one()
            return schemas.Clip.model_validate(db_clip)

    async def _store_embeddings_batch(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        embeddings_result: Any,
        file_index: int,
        job: schemas.FoundationModelRun,
    ) -> int:
        """Store embeddings from batch encode result for a specific recording.

        Uses bulk insert for better performance compared to individual inserts.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        recording : schemas.Recording
            Recording being processed.
        model_run : schemas.ModelRun
            Model run for this job.
        embeddings_result : Any
            Result from batch encode() containing embeddings for multiple files.
        file_index : int
            Index of this recording in the batch results.
        job : schemas.FoundationModelRun
            Foundation model run configuration.

        Returns
        -------
        int
            Number of clips created.
        """
        # Extract embeddings for this specific file from batch result
        if hasattr(embeddings_result, "embeddings"):
            all_embeddings = embeddings_result.embeddings
            if hasattr(all_embeddings, "numpy"):
                all_embeddings = all_embeddings.numpy()
            all_embeddings = np.asarray(all_embeddings, dtype=np.float32)

            # Get embeddings for this file (batch results are indexed by file)
            if all_embeddings.ndim == 4:
                # Shape: (n_files, 1, n_segments, embedding_dim)
                embeddings = all_embeddings[file_index, 0]
            elif all_embeddings.ndim == 3:
                # Shape: (n_files, n_segments, embedding_dim)
                embeddings = all_embeddings[file_index]
            else:
                logger.warning(
                    "Unexpected embeddings shape %s for recording %s",
                    all_embeddings.shape,
                    recording.uuid,
                )
                return 0
        else:
            logger.warning(
                "Embeddings result has no 'embeddings' attribute for recording %s",
                recording.uuid,
            )
            return 0

        if embeddings.size == 0:
            return 0

        # Get segment duration from model specification
        engine = self._engines[self._get_cache_key(job.model_name)]
        spec = engine.specification
        segment_duration = spec.segment_duration

        # Calculate overlap
        overlap = job.overlap * segment_duration
        hop_duration = segment_duration - overlap

        # Step 1: Prepare clip data for bulk insert
        now = datetime.datetime.now(datetime.timezone.utc)
        clips_data = []
        for seg_idx in range(len(embeddings)):
            start_time = seg_idx * hop_duration
            end_time = start_time + segment_duration
            clips_data.append(dict(
                uuid=uuid4(),
                recording_id=recording.id,
                start_time=start_time,
                end_time=end_time,
                created_on=now,
            ))

        # Step 2: Bulk insert clips with ON CONFLICT DO NOTHING
        stmt = pg_insert(models.Clip).values(clips_data)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["recording_id", "start_time", "end_time"]
        )
        await session.execute(stmt)
        await session.flush()

        # Step 3: Fetch clip IDs for all time ranges (including pre-existing ones)
        time_ranges = [(c["start_time"], c["end_time"]) for c in clips_data]
        clip_query = select(
            models.Clip.id,
            models.Clip.start_time,
            models.Clip.end_time,
        ).where(
            models.Clip.recording_id == recording.id,
            tuple_(models.Clip.start_time, models.Clip.end_time).in_(time_ranges),
        )
        clip_rows = await session.execute(clip_query)

        # Build a mapping from (start_time, end_time) -> clip_id
        clip_map: dict[tuple[float, float], int] = {
            (row.start_time, row.end_time): row.id for row in clip_rows
        }

        # Step 4: Prepare embedding data for bulk insert
        embeddings_data = []
        for seg_idx, embedding in enumerate(embeddings):
            start_time = seg_idx * hop_duration
            end_time = start_time + segment_duration
            clip_id = clip_map.get((start_time, end_time))
            if clip_id is None:
                continue

            # Pass numpy array directly to pgvector (49x faster than .tolist())
            embeddings_data.append(dict(
                uuid=uuid4(),
                clip_id=clip_id,
                model_run_id=model_run.id,
                embedding=embedding,  # numpy array → pgvector handles it
                created_on=now,
            ))

        # Step 5: Bulk insert embeddings with ON CONFLICT DO NOTHING
        if embeddings_data:
            stmt = pg_insert(models.ClipEmbedding).values(embeddings_data)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["clip_id", "model_run_id"]
            )
            await session.execute(stmt)
            await session.flush()

        return len(clip_map)

    async def _store_embeddings(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        embeddings_result: Any,
        job: schemas.FoundationModelRun,
    ) -> int:
        """Store embeddings from encode session result.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        recording : schemas.Recording
            Recording being processed.
        model_run : schemas.ModelRun
            Model run for this job.
        embeddings_result : Any
            Result from encode_session.run() containing embeddings.
        job : schemas.FoundationModelRun
            Foundation model run configuration.

        Returns
        -------
        int
            Number of clips created.
        """
        # Extract embeddings from result
        if hasattr(embeddings_result, "embeddings"):
            embeddings = embeddings_result.embeddings
            if hasattr(embeddings, "numpy"):
                embeddings = embeddings.numpy()
            embeddings = np.asarray(embeddings, dtype=np.float32)
        else:
            logger.warning(
                "Embeddings result has no 'embeddings' attribute for recording %s",
                recording.uuid,
            )
            return 0

        # Normalize to (n_segments, embedding_dim)
        if embeddings.ndim == 3:
            embeddings = embeddings[0]
        elif embeddings.ndim == 1:
            embeddings = embeddings.reshape(1, -1)

        if embeddings.size == 0:
            return 0

        # Get segment duration from model specification
        engine = self._engines[self._get_cache_key(job.model_name)]
        spec = engine.specification
        segment_duration = spec.segment_duration

        # Calculate overlap
        overlap = job.overlap * segment_duration

        # Create clips and embeddings
        clips_created = 0

        for seg_idx, embedding in enumerate(embeddings):
            # Calculate segment times with overlap
            hop_duration = segment_duration - overlap
            start_time = seg_idx * hop_duration
            end_time = start_time + segment_duration

            # Get or create clip
            clip = await self._get_or_create_clip(
                session, recording, start_time, end_time
            )

            # Store embedding
            try:
                await clip_embeddings.create(
                    session,
                    clip=clip,
                    model_run=model_run,
                    embedding=embedding.tolist(),
                )
                clips_created += 1
            except exceptions.DuplicateObjectError:
                # Embedding already exists, skip
                pass

        return clips_created

    async def _store_predictions_batch(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        predictions_result: Any,
        file_index: int,
        job: schemas.FoundationModelRun,
    ) -> int:
        """Store predictions from batch predict result for a specific recording.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        recording : schemas.Recording
            Recording being processed.
        model_run : schemas.ModelRun
            Model run for this job.
        predictions_result : Any
            Result from batch predict() containing predictions for multiple files.
        file_index : int
            Index of this recording in the batch results.
        job : schemas.FoundationModelRun
            Foundation model run configuration.

        Returns
        -------
        int
            Number of detections created.
        """
        # Extract predictions for this specific file from batch result
        if not hasattr(predictions_result, "species_probs"):
            logger.warning(
                "Predictions result has no 'species_probs' attribute for recording %s",
                recording.uuid,
            )
            return 0

        all_probs = predictions_result.species_probs
        all_ids = predictions_result.species_ids

        if all_probs is None or all_probs.size == 0:
            return 0

        # Get predictions for this file (batch results are indexed by file)
        if all_probs.ndim == 4:
            # Shape: (n_files, 1, n_segments, n_species)
            probs = all_probs[file_index, 0]
            ids = all_ids[file_index, 0]
        elif all_probs.ndim == 3:
            # Shape: (n_files, n_segments, n_species)
            probs = all_probs[file_index]
            ids = all_ids[file_index]
        else:
            logger.warning(
                "Unexpected predictions shape %s for recording %s",
                all_probs.shape,
                recording.uuid,
            )
            return 0

        # Get model specification
        engine = self._engines[self._get_cache_key(job.model_name)]
        spec = engine.specification
        segment_duration = spec.segment_duration
        species_list = engine._model.species_list

        # Calculate overlap
        overlap = job.overlap * segment_duration
        hop_duration = segment_duration - overlap

        # Step 1: Collect all predictions by segment
        segment_predictions: list[tuple[float, float, list[tuple[str, float]]]] = []

        for seg_idx, (seg_probs, seg_ids) in enumerate(zip(probs, ids, strict=False)):
            # Calculate segment times
            start_time = seg_idx * hop_duration
            end_time = start_time + segment_duration

            # Filter predictions by confidence threshold and top_k
            top_k = min(10, seg_probs.size)
            top_indices = np.argsort(seg_probs)[-top_k:][::-1]

            predictions: list[tuple[str, float]] = []
            for idx in top_indices:
                conf = float(seg_probs[idx])
                if conf >= job.confidence_threshold:
                    actual_idx = int(seg_ids[idx])
                    species_label = species_list[actual_idx]
                    predictions.append((species_label, conf))

            if not predictions:
                continue

            # Apply custom species filter if configured
            if job.custom_species_list:
                predictions = [
                    (species, conf)
                    for species, conf in predictions
                    if self._matches_custom_species(species, job.custom_species_list)
                ]

            if predictions:
                segment_predictions.append((start_time, end_time, predictions))

        if not segment_predictions:
            return 0

        # Step 2: Bulk create clips
        now = datetime.datetime.now(datetime.timezone.utc)
        clips_data = [
            dict(
                uuid=uuid4(),
                recording_id=recording.id,
                start_time=start_time,
                end_time=end_time,
                created_on=now,
            )
            for start_time, end_time, _ in segment_predictions
        ]

        stmt = pg_insert(models.Clip).values(clips_data)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["recording_id", "start_time", "end_time"]
        )
        await session.execute(stmt)
        await session.flush()

        # Step 3: Fetch clip IDs
        time_ranges = [(start_time, end_time) for start_time, end_time, _ in segment_predictions]
        clip_query = select(
            models.Clip.id,
            models.Clip.start_time,
            models.Clip.end_time,
        ).where(
            models.Clip.recording_id == recording.id,
            tuple_(models.Clip.start_time, models.Clip.end_time).in_(time_ranges),
        )
        clip_rows = await session.execute(clip_query)
        clip_map: dict[tuple[float, float], int] = {
            (row.start_time, row.end_time): row.id for row in clip_rows
        }

        # Step 4: Prepare species tags in batch
        all_species_labels: set[str] = set()
        for _, _, predictions in segment_predictions:
            for species_label, _ in predictions:
                all_species_labels.add(species_label)

        # Parse all species labels
        label_to_parsed: dict[str, tuple[str, str | None]] = {}
        for species_label in all_species_labels:
            scientific_name, common_name = self._parse_species_label(species_label)
            label_to_parsed[species_label] = (scientific_name, common_name)

        # Batch fetch existing tags
        tag_keys_values: list[tuple[str, str]] = [
            ("species", scientific_name)
            for scientific_name, _ in label_to_parsed.values()
        ]

        if tag_keys_values:
            tag_query = select(models.Tag).where(
                tuple_(models.Tag.key, models.Tag.value).in_(tag_keys_values)
            )
            tag_rows = await session.execute(tag_query)
            existing_tags = {
                (tag.key, tag.value): schemas.Tag.model_validate(tag)
                for tag in tag_rows.scalars().all()
            }
        else:
            existing_tags = {}

        # Create missing tags in batch
        tags_to_create: list[dict] = []
        for species_label, (scientific_name, common_name) in label_to_parsed.items():
            tag_key = ("species", scientific_name)

            # Collect all species (not just new ones) for batch GBIF resolution at job end
            # This ensures vernacular names are resolved even for existing tags
            if not is_non_species_label(scientific_name, common_name):
                if job.uuid in self._pending_species:
                    self._pending_species[job.uuid].add(scientific_name)

            if tag_key not in existing_tags:
                canonical = common_name or scientific_name
                tags_to_create.append({
                    "key": "species",
                    "value": scientific_name,
                    "canonical_name": canonical,
                    "created_on": now,
                })

        if tags_to_create:
            stmt = pg_insert(models.Tag).values(tags_to_create)
            stmt = stmt.on_conflict_do_nothing(index_elements=["key", "value"])
            stmt = stmt.returning(models.Tag)
            result = await session.execute(stmt)
            await session.flush()

            for tag in result.scalars().all():
                existing_tags[("species", tag.value)] = schemas.Tag.model_validate(tag)

        # Build final species cache
        species_tag_cache: dict[str, tuple[schemas.Tag, str, str | None, str | None]] = {}
        for species_label, (scientific_name, common_name) in label_to_parsed.items():
            tag = existing_tags.get(("species", scientific_name))
            if tag:
                gbif_taxon_id = None
                species_tag_cache[species_label] = (tag, scientific_name, common_name, gbif_taxon_id)

        # Step 5: Create predictions and tags in bulk
        detections_count = 0
        predictions_to_create: list[dict] = []
        clip_to_predictions: dict[int, list[tuple[str, float]]] = {}

        for start_time, end_time, predictions in segment_predictions:
            clip_id = clip_map.get((start_time, end_time))
            if clip_id is None:
                continue

            predictions_to_create.append(dict(uuid=uuid4(), clip_id=clip_id, created_on=now))
            clip_to_predictions[clip_id] = predictions

        # Bulk insert clip predictions
        if predictions_to_create:
            stmt = (
                pg_insert(models.ClipPrediction)
                .values(predictions_to_create)
                .returning(models.ClipPrediction.id, models.ClipPrediction.clip_id)
            )
            result_rows = await session.execute(stmt)
            created_predictions = result_rows.fetchall()

            clip_to_prediction_id: dict[int, int] = {
                row.clip_id: row.id for row in created_predictions
            }

            # Prepare model run predictions and prediction tags
            model_run_predictions_to_create: list[dict] = []
            prediction_tags_to_create: list[dict] = []

            for clip_id, predictions in clip_to_predictions.items():
                prediction_id = clip_to_prediction_id.get(clip_id)
                if prediction_id is None:
                    continue

                model_run_predictions_to_create.append(
                    dict(model_run_id=model_run.id, clip_prediction_id=prediction_id, created_on=now)
                )

                for species_label, confidence in predictions:
                    cached = species_tag_cache.get(species_label)
                    if cached is None:
                        continue

                    tag, scientific_name, common_name, gbif_taxon_id = cached
                    if tag.id is None:
                        continue

                    prediction_tags_to_create.append(
                        dict(
                            clip_prediction_id=prediction_id,
                            tag_id=tag.id,
                            score=confidence,
                            created_on=now,
                        )
                    )

                    self._record_species_summary(
                        job,
                        tag,
                        scientific_name,
                        common_name,
                        gbif_taxon_id,
                        confidence,
                    )
                    detections_count += 1

            # Bulk insert model run predictions
            if model_run_predictions_to_create:
                stmt = pg_insert(models.ModelRunPrediction).values(
                    model_run_predictions_to_create
                )
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

            # Bulk insert prediction tags
            if prediction_tags_to_create:
                stmt = pg_insert(models.ClipPredictionTag).values(prediction_tags_to_create)
                stmt = stmt.on_conflict_do_nothing()
                await session.execute(stmt)

            await session.flush()

        return detections_count

    async def _store_predictions(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        predictions_result: Any,
        job: schemas.FoundationModelRun,
    ) -> int:
        """Store predictions from predict session result.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        recording : schemas.Recording
            Recording being processed.
        model_run : schemas.ModelRun
            Model run for this job.
        predictions_result : Any
            Result from predict_session.run() containing predictions.
        job : schemas.FoundationModelRun
            Foundation model run configuration.

        Returns
        -------
        int
            Number of detections created.
        """
        # Extract predictions from result
        if not hasattr(predictions_result, "species_probs"):
            logger.warning(
                "Predictions result has no 'species_probs' attribute for recording %s",
                recording.uuid,
            )
            return 0

        species_probs = predictions_result.species_probs
        species_ids = predictions_result.species_ids

        if species_probs is None or species_probs.size == 0:
            return 0

        # Normalize to (n_segments, n_species)
        if species_probs.ndim == 3:
            probs = species_probs[0]
            ids = species_ids[0]
        elif species_probs.ndim == 2:
            probs = species_probs
            ids = species_ids
        else:
            probs = species_probs.reshape(1, -1)
            ids = species_ids.reshape(1, -1)

        # Get model specification
        engine = self._engines[self._get_cache_key(job.model_name)]
        spec = engine.specification
        segment_duration = spec.segment_duration
        species_list = engine._model.species_list

        # Calculate overlap
        overlap = job.overlap * segment_duration

        detections_count = 0

        # Process each segment
        for seg_idx, (seg_probs, seg_ids) in enumerate(zip(probs, ids, strict=False)):
            # Calculate segment times
            hop_duration = segment_duration - overlap
            start_time = seg_idx * hop_duration
            end_time = start_time + segment_duration

            # Filter predictions by confidence threshold and top_k
            top_k = min(10, seg_probs.size)
            top_indices = np.argsort(seg_probs)[-top_k:][::-1]

            predictions: list[tuple[str, float]] = []
            for idx in top_indices:
                conf = float(seg_probs[idx])
                if conf >= job.confidence_threshold:
                    actual_idx = int(seg_ids[idx])
                    species_label = species_list[actual_idx]
                    predictions.append((species_label, conf))

            if not predictions:
                continue

            # Apply custom species filter if configured
            if job.custom_species_list:
                predictions = [
                    (species, conf)
                    for species, conf in predictions
                    if self._matches_custom_species(species, job.custom_species_list)
                ]

            if not predictions:
                continue

            # Get or create clip
            clip = await self._get_or_create_clip(
                session, recording, start_time, end_time
            )

            # Create clip prediction
            try:
                clip_pred = await clip_predictions.create(session, clip=clip)
                # Link to model run
                await model_runs.add_clip_prediction(session, model_run, clip_pred)
            except exceptions.DuplicateObjectError:
                # Prediction already exists, fetch it
                stmt = select(models.ClipPrediction).where(
                    models.ClipPrediction.clip_id == clip.id
                )
                result = await session.execute(stmt)
                db_pred = result.scalar_one_or_none()
                if db_pred:
                    clip_pred = schemas.ClipPrediction.model_validate(db_pred)
                else:
                    continue

            # Add tags for each species prediction
            for species_label, confidence in predictions:
                tag, scientific_name, common_name, gbif_taxon_id = (
                    await self._get_or_create_species_tag(
                        session,
                        species_label,
                        job.uuid,
                    )
                )

                try:
                    clip_pred = await clip_predictions.add_tag(
                        session,
                        clip_pred,
                        tag,
                        score=confidence,
                    )
                except exceptions.DuplicateObjectError:
                    # Tag already exists on this prediction, skip
                    pass

                # Record species summary
                self._record_species_summary(
                    job,
                    tag,
                    scientific_name,
                    common_name,
                    gbif_taxon_id,
                    confidence,
                )
                detections_count += 1

        return detections_count

    def _get_cache_key(self, model_name: str) -> str:
        """Get cache key for a model."""
        return model_name

    def unload_models(self) -> None:
        """Unload all loaded models."""
        for _model_name, engine in self._engines.items():
            if hasattr(engine, "close_sessions"):
                engine.close_sessions()  # type: ignore[attr-defined]

        for model_name, loader in self._loaders.items():
            loader.unload()
            logger.info("%s model unloaded", model_name)

        self._loaders.clear()
        self._engines.clear()
