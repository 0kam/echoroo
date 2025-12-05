"""Inference worker service for processing ML jobs.

This module provides a background worker that processes inference jobs from
the database, runs ML models (BirdNET), and stores results including
embeddings and predictions.

The worker has been updated to use the new ML architecture with:
- InferenceEngine interface for model-agnostic inference
- InferenceResult for unified result handling
- OccurrenceFilter for location/time-based filtering
- Full backward compatibility with existing code
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import models, schemas
from echoroo.api import (
    clips,
    clip_embeddings,
    clip_predictions,
    datasets,
    inference_jobs,
    model_runs,
    recordings,
    tags,
)
from echoroo.filters.inference_jobs import StatusFilter
from echoroo.ml.base import InferenceEngine, InferenceResult, ModelLoader
from echoroo.ml.filters import (
    EBirdOccurrenceFilter,
    FilterContext,
    PassThroughFilter,
    PredictionFilter,
)
from echoroo.ml.registry import ModelRegistry, ModelNotFoundError

__all__ = [
    "InferenceWorker",
]

logger = logging.getLogger(__name__)


class InferenceWorker:
    """Background worker for processing inference jobs.

    This worker polls the database for pending inference jobs, processes them
    using the BirdNET ML model, and stores results including embeddings and
    predictions.

    The worker has been updated to use the new ML architecture:
    - InferenceEngine interface for model-agnostic inference
    - InferenceResult for unified result handling
    - OccurrenceFilter for location/time-based filtering

    Parameters
    ----------
    audio_dir
        Root directory containing audio files.
    model_dir
        Directory containing ML model files. If None, uses default locations.
    poll_interval
        Interval in seconds between polling for new jobs.
    batch_size
        Number of audio segments to process in a single batch.
    occurrence_data_path
        Path to eBird occurrence data (NPZ file) for filtering predictions.
        If None, no occurrence-based filtering is applied.

    Examples
    --------
    >>> worker = InferenceWorker(
    ...     audio_dir=Path("/audio"),
    ...     occurrence_data_path=Path("/data/species_presence.npz"),
    ... )
    >>> await worker.start(session_factory)
    >>> # Worker runs in background, processing jobs
    >>> await worker.stop()
    """

    def __init__(
        self,
        audio_dir: Path,
        model_dir: Path | None = None,
        poll_interval: float = 5.0,
        batch_size: int = 32,
        occurrence_data_path: Path | None = None,
    ):
        self._audio_dir = audio_dir
        self._model_dir = model_dir
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._occurrence_data_path = occurrence_data_path
        self._running = False
        self._current_job: UUID | None = None
        self._cancel_requested = False
        self._task: asyncio.Task | None = None

        # Model loaders and engines (lazy loaded, keyed by model name)
        self._loaders: dict[str, ModelLoader] = {}
        self._engines: dict[str, InferenceEngine] = {}

        # Prediction filters
        self._occurrence_filter: PredictionFilter = self._create_occurrence_filter()
        self._passthrough_filter: PredictionFilter = PassThroughFilter()

    def _create_occurrence_filter(self) -> PredictionFilter:
        """Create occurrence filter if data is available.

        Returns
        -------
        PredictionFilter
            EBirdOccurrenceFilter if data path is provided and valid,
            PassThroughFilter otherwise.
        """
        if self._occurrence_data_path is None:
            logger.info("No occurrence data path provided, filtering disabled")
            return PassThroughFilter()

        try:
            filter_instance = EBirdOccurrenceFilter(self._occurrence_data_path)
            if filter_instance.is_loaded:
                logger.info(
                    "Occurrence filter loaded: %d species",
                    filter_instance.num_species,
                )
                return filter_instance
            else:
                logger.warning(
                    "Occurrence filter failed to load, filtering disabled"
                )
                return PassThroughFilter()
        except Exception as e:
            logger.warning(
                "Failed to create occurrence filter: %s. Filtering disabled.", e
            )
            return PassThroughFilter()

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running

    @property
    def current_job(self) -> UUID | None:
        """Get the UUID of the currently processing job, if any."""
        return self._current_job

    async def start(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Start processing jobs.

        Begins the background loop that polls for pending jobs and processes
        them. This method returns immediately after starting the loop.

        Parameters
        ----------
        session_factory
            Callable that creates new database sessions.
        """
        if self._running:
            logger.warning("Worker is already running")
            return

        self._running = True
        self._cancel_requested = False

        logger.info("Starting inference worker")

        # Start the background processing loop
        self._task = asyncio.create_task(
            self._run_loop(session_factory),
            name="inference_worker",
        )

    async def stop(self) -> None:
        """Stop processing gracefully.

        Signals the worker to stop after completing the current job (if any).
        Waits for the worker to finish before returning.
        """
        if not self._running:
            logger.warning("Worker is not running")
            return

        logger.info("Stopping inference worker")
        self._running = False

        if self._task is not None:
            # Wait for the task to complete
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

        logger.info("Inference worker stopped")

    async def _run_loop(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Main processing loop that polls for and processes jobs."""
        while self._running:
            try:
                async with session_factory() as session:
                    # Find the next pending job
                    job = await self._get_next_job(session)

                    if job is not None:
                        self._current_job = job.uuid
                        try:
                            await self.process_job(session, job)
                        finally:
                            self._current_job = None
                    else:
                        # No pending jobs, wait before polling again
                        await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.exception("Error in worker loop: %s", e)
                await asyncio.sleep(self._poll_interval)

    async def _get_next_job(
        self,
        session: AsyncSession,
    ) -> schemas.InferenceJob | None:
        """Get the next pending job from the database."""
        try:
            jobs, count = await inference_jobs.get_many(
                session,
                limit=1,
                offset=0,
                filters=[StatusFilter(eq="pending")],
                sort_by="created_on",
            )

            if count > 0 and jobs:
                return jobs[0]

            return None

        except Exception as e:
            logger.error("Failed to fetch pending jobs: %s", e)
            return None

    async def process_job(
        self,
        session: AsyncSession,
        job: schemas.InferenceJob,
    ) -> None:
        """Process a single inference job.

        Parameters
        ----------
        session
            Database session for operations.
        job
            The inference job to process.

        Notes
        -----
        This method handles the full job lifecycle:
        1. Mark job as running and create model run
        2. Get recordings to process (from dataset or single recording)
        3. For each recording:
           - Create filter context from recording metadata
           - Run inference using appropriate engine
           - Apply occurrence filtering if configured
           - Store embeddings (if configured)
           - Store predictions (if configured)
           - Update progress
        4. Mark job complete or failed
        """
        logger.info("Processing job %s", job.uuid)
        self._cancel_requested = False

        try:
            # Create model run for this job
            model_run = await self._create_model_run(session, job)

            # Mark job as running
            job = await inference_jobs.start(
                session,
                job,
                model_run_id=model_run.id,
            )
            await session.commit()

            # Get recordings to process
            recording_list = await self._get_recordings(session, job)

            if not recording_list:
                logger.warning("No recordings found for job %s", job.uuid)
                job = await inference_jobs.complete(session, job)
                await session.commit()
                return

            # Update total items
            job = await inference_jobs.set_total_items(
                session,
                job,
                total_items=len(recording_list),
            )
            await session.commit()

            # Ensure the model is loaded
            engine = self._ensure_model_loaded(job.config)

            # Get the appropriate filter
            filter_instance = self._get_filter(job.config)

            # Process each recording
            total_predictions = 0
            for i, recording in enumerate(recording_list):
                if self._cancel_requested:
                    logger.info("Job %s cancelled by user", job.uuid)
                    job = await inference_jobs.cancel(session, job)
                    await session.commit()
                    return

                try:
                    predictions = await self._process_recording(
                        session,
                        recording,
                        model_run,
                        engine,
                        filter_instance,
                        job.config,
                    )
                    total_predictions += predictions

                except Exception as e:
                    logger.error(
                        "Error processing recording %s: %s",
                        recording.uuid,
                        e,
                    )
                    # Continue with other recordings

                # Update progress
                job = await inference_jobs.update_progress(
                    session,
                    job,
                    processed_items=i + 1,
                )
                await session.commit()

            # Mark job as complete
            job = await inference_jobs.complete(session, job)
            await session.commit()

            logger.info(
                "Job %s completed: %d predictions from %d recordings",
                job.uuid,
                total_predictions,
                len(recording_list),
            )

        except Exception as e:
            logger.exception("Job %s failed: %s", job.uuid, e)
            try:
                job = await inference_jobs.fail(
                    session,
                    job,
                    error_message=str(e),
                )
                await session.commit()
            except Exception as commit_error:
                logger.error(
                    "Failed to update job status: %s",
                    commit_error,
                )

    async def _create_model_run(
        self,
        session: AsyncSession,
        job: schemas.InferenceJob,
    ) -> schemas.ModelRun:
        """Create a model run for the inference job."""
        config = job.config
        model_name = config.model_name
        model_version = config.model_version

        # Build description from job configuration
        description_parts = [
            f"Inference job {job.uuid}",
            f"threshold={config.confidence_threshold}",
            f"overlap={config.overlap}",
        ]
        if config.use_metadata_filter:
            description_parts.append("metadata_filter=true")
        if config.custom_species_list:
            description_parts.append(
                f"custom_species={len(config.custom_species_list)}"
            )

        description = ", ".join(description_parts)

        return await model_runs.create(
            session,
            name=model_name,
            version=model_version,
            description=description,
        )

    async def _get_recordings(
        self,
        session: AsyncSession,
        job: schemas.InferenceJob,
    ) -> list[schemas.Recording]:
        """Get the list of recordings to process for a job."""
        recording_list: list[schemas.Recording] = []

        # Single recording mode
        if job.recording is not None:
            return [job.recording]

        # Dataset mode
        if job.dataset is not None:
            recs, _ = await datasets.get_recordings(
                session,
                job.dataset,
                limit=-1,  # Get all recordings
            )
            recording_list = list(recs)

        return recording_list

    def _ensure_model_loaded(
        self, config: schemas.InferenceConfig
    ) -> InferenceEngine:
        """Ensure the required model is loaded and return the inference engine.

        Uses the ModelRegistry pattern to dynamically load models based on
        their registered name. This allows adding new models without modifying
        this method.

        Parameters
        ----------
        config
            Inference configuration specifying which model to use.

        Returns
        -------
        InferenceEngine
            The loaded inference engine.

        Raises
        ------
        ValueError
            If the model name is not recognized/registered.
        RuntimeError
            If model loading fails.
        """
        model_name = config.model_name

        # Check if engine already exists and update threshold
        if model_name in self._engines:
            engine = self._engines[model_name]
            # Update threshold if the engine has this property
            # (Most engines like BirdNETInference and PerchInference have this)
            if hasattr(engine, "confidence_threshold"):
                engine.confidence_threshold = config.confidence_threshold  # type: ignore[attr-defined]
            return engine

        # Try to get model classes from registry
        try:
            loader_class = ModelRegistry.get_loader_class(model_name)
            engine_class = ModelRegistry.get_engine_class(model_name)
        except ModelNotFoundError as e:
            available = ModelRegistry.available_models()
            raise ValueError(
                f"Unknown model: {model_name}. "
                f"Available models: {', '.join(available) if available else 'none'}"
            ) from e

        # Create and load the model
        logger.info("Loading %s model via ModelRegistry", model_name)

        loader = loader_class(model_dir=self._model_dir)
        loader.load()
        self._loaders[model_name] = loader

        # Create inference engine
        # Note: confidence_threshold is accepted by BirdNETInference and PerchInference
        # but not defined in the base class signature
        engine = engine_class(
            loader,
            confidence_threshold=config.confidence_threshold,  # type: ignore[call-arg]
        )
        self._engines[model_name] = engine

        return engine

    def _get_filter(self, config: schemas.InferenceConfig) -> PredictionFilter:
        """Get the appropriate prediction filter based on configuration.

        Parameters
        ----------
        config
            Inference configuration.

        Returns
        -------
        PredictionFilter
            Occurrence filter if metadata filtering is enabled and available,
            PassThroughFilter otherwise.
        """
        if config.use_metadata_filter and isinstance(
            self._occurrence_filter, EBirdOccurrenceFilter
        ):
            logger.debug("Using occurrence-based filtering")
            return self._occurrence_filter
        else:
            logger.debug("Using pass-through filter (no filtering)")
            return self._passthrough_filter

    def _create_filter_context(
        self, recording: schemas.Recording
    ) -> FilterContext:
        """Create filter context from recording metadata.

        Parameters
        ----------
        recording
            Recording with metadata.

        Returns
        -------
        FilterContext
            Filter context for prediction filtering.
        """
        return FilterContext(
            latitude=recording.latitude,
            longitude=recording.longitude,
            date=recording.date,
            # time_of_day could be derived from recording.time if available
            # For now, we don't set it
        )

    async def _process_recording(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        engine: InferenceEngine,
        filter_instance: PredictionFilter,
        config: schemas.InferenceConfig,
    ) -> int:
        """Process a single recording and return number of predictions.

        This is the main method that ties together the new ML architecture:
        1. Run inference using InferenceEngine
        2. Apply filtering using PredictionFilter
        3. Store results in database

        Parameters
        ----------
        session
            Database session.
        recording
            Recording to process.
        model_run
            Model run to associate results with.
        engine
            Inference engine to use.
        filter_instance
            Prediction filter to apply.
        config
            Inference configuration.

        Returns
        -------
        int
            Number of predictions created.
        """
        logger.debug("Processing recording %s", recording.uuid)

        # Build full path to audio file
        audio_path = self._audio_dir / recording.path

        if not audio_path.exists():
            logger.warning("Audio file not found: %s", audio_path)
            return 0

        # Create filter context from recording metadata
        filter_context = self._create_filter_context(recording)

        # Run inference on entire file using the engine
        try:
            results = await self._run_inference(
                engine, audio_path, config.overlap
            )
        except Exception as e:
            logger.error("Inference failed for %s: %s", recording.uuid, e)
            return 0

        if not results:
            logger.warning("No segments extracted from %s", recording.uuid)
            return 0

        # Process and store results
        total_predictions = 0
        for result in results:
            if self._cancel_requested:
                break

            predictions_count = await self._store_result(
                session,
                recording,
                model_run,
                result,
                filter_instance,
                filter_context,
                config,
            )
            total_predictions += predictions_count

        return total_predictions

    async def _run_inference(
        self,
        engine: InferenceEngine,
        audio_path: Path,
        overlap: float,
    ) -> list[InferenceResult]:
        """Run inference on an audio file.

        This method wraps the InferenceEngine.predict_file() call in an
        executor to avoid blocking the async event loop.

        Parameters
        ----------
        engine
            Inference engine to use.
        audio_path
            Path to audio file.
        overlap
            Overlap between segments (0.0 to 1.0).

        Returns
        -------
        list[InferenceResult]
            List of inference results for each segment.
        """
        # Convert overlap from ratio to seconds
        spec = engine.specification
        overlap_seconds = overlap * spec.segment_duration

        # Run inference in executor (CPU-bound operation)
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            engine.predict_file,
            audio_path,
            overlap_seconds,
        )

        return results

    async def _store_result(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        result: InferenceResult,
        filter_instance: PredictionFilter,
        filter_context: FilterContext,
        config: schemas.InferenceConfig,
    ) -> int:
        """Store inference result in the database.

        This method handles both embeddings and predictions for all models.

        Parameters
        ----------
        session
            Database session.
        recording
            Source recording.
        model_run
            Model run to associate with.
        result
            Inference result from the engine.
        filter_instance
            Prediction filter to apply.
        filter_context
            Filter context for prediction filtering.
        config
            Inference configuration.

        Returns
        -------
        int
            Number of predictions stored.
        """
        predictions_stored = 0

        # Create clip for this segment
        clip = await clips.create(
            session,
            recording=recording,
            start_time=result.start_time,
            end_time=result.end_time,
        )

        # Store embedding if configured
        if config.store_embeddings:
            embedding_list = result.embedding.tolist()
            await clip_embeddings.create(
                session,
                clip=clip,
                model_run=model_run,
                embedding=embedding_list,
            )

        # Store predictions if configured and available
        if config.store_predictions and result.predictions:
            # Apply filtering to predictions
            filtered_predictions = filter_instance.filter_predictions(
                result.predictions, filter_context
            )

            # Apply custom species list if configured
            if config.custom_species_list:
                filtered_predictions = [
                    (species, conf)
                    for species, conf in filtered_predictions
                    if self._matches_custom_species(
                        species, config.custom_species_list
                    )
                ]

            if not filtered_predictions:
                logger.debug(
                    "No predictions remaining after filtering for segment at %.2fs",
                    result.start_time,
                )
                return 0

            # Create clip prediction
            clip_pred = await clip_predictions.create(
                session,
                clip=clip,
            )

            # Add to model run
            await model_runs.add_clip_prediction(
                session,
                model_run,
                clip_pred,
            )

            # Add predicted tags for each species
            for species_label, confidence in filtered_predictions:
                # Parse species label format (may vary by model)
                tag = await self._get_or_create_species_tag(
                    session,
                    species_label,
                )

                clip_pred = await clip_predictions.add_tag(
                    session,
                    clip_pred,
                    tag,
                    score=confidence,
                )

                predictions_stored += 1

        return predictions_stored

    def _matches_custom_species(
        self, species_label: str, custom_list: list[str]
    ) -> bool:
        """Check if species label matches any in the custom species list.

        This method handles different label formats:
        - BirdNET: "Scientific name_Common name"
        - Perch: Species code or label

        Parameters
        ----------
        species_label
            Species label from the model.
        custom_list
            List of species to match against.

        Returns
        -------
        bool
            True if species matches any in the custom list.
        """
        # Extract scientific name if in BirdNET format
        scientific_name = species_label.split("_")[0] if "_" in species_label else species_label

        # Check for exact match or scientific name match
        return (
            species_label in custom_list
            or scientific_name in custom_list
        )

    async def _get_or_create_species_tag(
        self,
        session: AsyncSession,
        species_label: str,
    ) -> schemas.Tag:
        """Get or create a tag for a species from model label.

        This method handles different label formats:
        - BirdNET: "Scientific name_Common name"
        - Perch: Species code or label

        Parameters
        ----------
        session
            Database session.
        species_label
            Species label from the model.

        Returns
        -------
        schemas.Tag
            The species tag.
        """
        # Parse label format (BirdNET uses "Scientific_Common" format)
        parts = species_label.split("_", 1)
        scientific_name = parts[0] if parts else species_label
        common_name = parts[1] if len(parts) > 1 else None

        return await tags.get_or_create(
            session,
            key="species",
            value=scientific_name,
            canonical_name=common_name,
        )

    async def cancel_current_job(self) -> None:
        """Request cancellation of the current job.

        The job will be cancelled after completing the current batch.
        This method returns immediately; the actual cancellation is
        handled asynchronously.
        """
        if self._current_job is not None:
            logger.info("Cancellation requested for job %s", self._current_job)
            self._cancel_requested = True
        else:
            logger.warning("No job currently running to cancel")

    def unload_models(self) -> None:
        """Unload all loaded models to free memory."""
        for model_name, loader in self._loaders.items():
            loader.unload()
            logger.info("%s model unloaded", model_name)

        self._loaders.clear()
        self._engines.clear()
