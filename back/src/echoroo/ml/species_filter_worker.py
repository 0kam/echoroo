"""Species Filter Worker service for applying species filters to foundation model runs.

This module provides a background worker that processes species filter applications
from the database, applies geographic/occurrence filters to clip predictions,
and stores the resulting mask records.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from echoroo import models
from echoroo.ml.filters import BirdNETGeoFilter, FilterContext, SpeciesFilter

__all__ = [
    "SpeciesFilterWorker",
]

logger = logging.getLogger(__name__)

# Registry mapping filter slugs/providers to filter classes
_FILTER_REGISTRY: dict[str, type[SpeciesFilter]] = {
    "birdnet-geo": BirdNETGeoFilter,
    "birdnet": BirdNETGeoFilter,
}


def get_filter_instance(slug: str) -> SpeciesFilter | None:
    """Get a filter instance based on the slug.

    Parameters
    ----------
    slug : str
        The filter slug (e.g., "birdnet-geo-v2-4") or provider key.

    Returns
    -------
    SpeciesFilter | None
        The filter instance, or None if not found.
    """
    # Try exact match first
    if slug in _FILTER_REGISTRY:
        return _FILTER_REGISTRY[slug]()

    # Try prefix match (e.g., "birdnet-geo-v2-4" -> "birdnet-geo")
    for prefix, filter_class in _FILTER_REGISTRY.items():
        if slug.startswith(prefix):
            return filter_class()

    # Try by provider
    provider = slug.split("-")[0] if "-" in slug else slug
    if provider in _FILTER_REGISTRY:
        return _FILTER_REGISTRY[provider]()

    logger.warning("Unknown filter slug: %s", slug)
    return None


class SpeciesFilterWorker:
    """Background worker for processing species filter applications.

    This worker polls the database for pending species filter applications,
    processes them by applying the filter to clip predictions, and stores
    the resulting mask records.
    """

    def __init__(
        self,
        poll_interval: float = 5.0,
        batch_size: int = 100,
    ):
        """Initialize the species filter worker.

        Parameters
        ----------
        poll_interval : float
            Seconds between polling for new applications.
        batch_size : int
            Number of predictions to process at a time.
        """
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._running = False
        self._current_application: UUID | None = None
        self._cancel_requested = False
        self._task: asyncio.Task | None = None

        # Lazy-loaded filter instances
        self._filters: dict[str, SpeciesFilter] = {}

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running

    @property
    def current_application(self) -> UUID | None:
        """Get the UUID of the currently processing application."""
        return self._current_application

    def _get_filter(self, slug: str) -> SpeciesFilter | None:
        """Get or create a filter instance for the given slug.

        Parameters
        ----------
        slug : str
            The filter slug.

        Returns
        -------
        SpeciesFilter | None
            The filter instance, or None if not found.
        """
        if slug not in self._filters:
            filter_instance = get_filter_instance(slug)
            if filter_instance is not None:
                self._filters[slug] = filter_instance
            else:
                return None

        return self._filters[slug]

    async def start(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Start processing filter applications.

        Parameters
        ----------
        session_factory : Callable[[], AsyncSession]
            Factory function that creates new database sessions.
        """
        if self._running:
            logger.warning("Species filter worker is already running")
            return

        self._running = True
        self._cancel_requested = False

        logger.info("Starting species filter worker")

        self._task = asyncio.create_task(
            self._run_loop(session_factory),
            name="species_filter_worker",
        )

    async def stop(self) -> None:
        """Stop processing gracefully."""
        if not self._running:
            logger.warning("Species filter worker is not running")
            return

        logger.info("Stopping species filter worker")
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

        logger.info("Species filter worker stopped")

    async def _run_loop(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Main processing loop."""
        while self._running:
            try:
                async with session_factory() as session:
                    application = await self._get_next_application(session)

                    if application is not None:
                        self._current_application = application.uuid
                        try:
                            await self.process_application(session, application)
                        finally:
                            self._current_application = None
                    else:
                        await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.exception("Error in worker loop: %s", e)
                await asyncio.sleep(self._poll_interval)

    async def _get_next_application(
        self,
        session: AsyncSession,
    ) -> models.SpeciesFilterApplication | None:
        """Get the next pending filter application from the database.

        Parameters
        ----------
        session : AsyncSession
            Database session.

        Returns
        -------
        models.SpeciesFilterApplication | None
            The next pending application, or None if none available.
        """
        try:
            stmt = (
                select(models.SpeciesFilterApplication)
                .options(
                    joinedload(models.SpeciesFilterApplication.species_filter),
                    joinedload(models.SpeciesFilterApplication.foundation_model_run),
                )
                .where(
                    models.SpeciesFilterApplication.status
                    == models.SpeciesFilterApplicationStatus.PENDING
                )
                .order_by(models.SpeciesFilterApplication.id)
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.unique().scalar_one_or_none()

        except Exception as e:
            logger.error("Failed to fetch pending applications: %s", e)
            return None

    async def process_application(
        self,
        session: AsyncSession,
        application: models.SpeciesFilterApplication,
    ) -> None:
        """Process a single species filter application.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        application : models.SpeciesFilterApplication
            The filter application to process.
        """
        logger.info("Processing species filter application %s", application.uuid)
        self._cancel_requested = False

        try:
            # Update status to running
            await self._update_application_status(
                session,
                application,
                status=models.SpeciesFilterApplicationStatus.RUNNING,
                started_on=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()

            # Get the filter instance
            species_filter = application.species_filter
            filter_instance = self._get_filter(species_filter.slug)

            if filter_instance is None:
                raise ValueError(f"Unknown filter: {species_filter.slug}")

            # Get all clip predictions for the foundation model run
            foundation_run = application.foundation_model_run
            model_run_id = foundation_run.model_run_id

            if model_run_id is None:
                raise ValueError(
                    f"Foundation model run {foundation_run.uuid} has no model_run_id"
                )

            # Get predictions with their clips and recordings
            predictions = await self._get_predictions(session, model_run_id)

            if not predictions:
                logger.warning(
                    "No predictions found for foundation model run %s",
                    foundation_run.uuid,
                )
                await self._update_application_status(
                    session,
                    application,
                    status=models.SpeciesFilterApplicationStatus.COMPLETED,
                    completed_on=datetime.datetime.now(datetime.UTC),
                )
                await session.commit()
                return

            # Update total detections
            total_detections = sum(len(pred.tags) for pred in predictions)
            application.total_detections = total_detections
            await session.flush()

            # Process each prediction
            filtered_count = 0
            excluded_count = 0
            processed = 0

            for prediction in predictions:
                if self._cancel_requested:
                    logger.info(
                        "Application %s cancelled by user", application.uuid
                    )
                    await self._update_application_status(
                        session,
                        application,
                        status=models.SpeciesFilterApplicationStatus.CANCELLED,
                    )
                    await session.commit()
                    return

                # Get recording metadata for filter context
                recording = prediction.clip.recording
                filter_context = FilterContext.from_recording(
                    latitude=recording.latitude,
                    longitude=recording.longitude,
                    recording_date=recording.date,
                )

                # Get occurrence probabilities
                occurrence_probs = await filter_instance.get_species_probabilities(
                    filter_context, session
                )

                # Process each tag in the prediction
                for pred_tag in prediction.tags:
                    tag = pred_tag.tag

                    # Determine if species should be included
                    occurrence_prob = None
                    is_included = True
                    exclusion_reason = None

                    if occurrence_probs is not None:
                        # Try to match by tag value (GBIF taxon key)
                        occurrence_prob = occurrence_probs.get(tag.value)

                        if occurrence_prob is None:
                            # Species not in occurrence data - include by default
                            is_included = True
                        elif occurrence_prob < application.threshold:
                            is_included = False
                            exclusion_reason = (
                                f"Occurrence probability {occurrence_prob:.2%} "
                                f"below threshold {application.threshold:.2%}"
                            )
                    else:
                        # No filter context available - include by default
                        if not filter_context.is_valid:
                            exclusion_reason = "Invalid filter context (missing location/date)"

                    # Create mask record
                    mask = models.SpeciesFilterMask(
                        species_filter_application_id=application.id,
                        clip_prediction_id=prediction.id,
                        tag_id=tag.id,
                        is_included=is_included,
                        occurrence_probability=occurrence_prob,
                        exclusion_reason=exclusion_reason,
                    )
                    session.add(mask)

                    if is_included:
                        filtered_count += 1
                    else:
                        excluded_count += 1

                processed += 1

                # Update progress periodically
                if processed % self._batch_size == 0:
                    progress = processed / len(predictions)
                    application.progress = progress
                    application.filtered_detections = filtered_count
                    application.excluded_detections = excluded_count
                    await session.commit()

            # Mark complete
            await self._update_application_status(
                session,
                application,
                status=models.SpeciesFilterApplicationStatus.COMPLETED,
                completed_on=datetime.datetime.now(datetime.UTC),
                progress=1.0,
                filtered_detections=filtered_count,
                excluded_detections=excluded_count,
            )
            await session.commit()

            logger.info(
                "Application %s completed: %d filtered, %d excluded from %d total",
                application.uuid,
                filtered_count,
                excluded_count,
                total_detections,
            )

        except Exception as e:
            logger.exception("Application %s failed: %s", application.uuid, e)
            try:
                await self._update_application_status(
                    session,
                    application,
                    status=models.SpeciesFilterApplicationStatus.FAILED,
                    error={"message": str(e)},
                )
                await session.commit()
            except Exception as commit_error:
                logger.error("Failed to update application status: %s", commit_error)

    async def _get_predictions(
        self,
        session: AsyncSession,
        model_run_id: int,
    ) -> list[models.ClipPrediction]:
        """Get all clip predictions for a model run.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        model_run_id : int
            The model run ID.

        Returns
        -------
        list[models.ClipPrediction]
            List of clip predictions with their clips, recordings, and tags.
        """
        stmt = (
            select(models.ClipPrediction)
            .join(models.ModelRunPrediction)
            .options(
                joinedload(models.ClipPrediction.clip).joinedload(
                    models.Clip.recording
                ),
                joinedload(models.ClipPrediction.tags).joinedload(
                    models.ClipPredictionTag.tag
                ),
            )
            .where(models.ModelRunPrediction.model_run_id == model_run_id)
        )
        result = await session.execute(stmt)
        return list(result.unique().scalars().all())

    async def _update_application_status(
        self,
        session: AsyncSession,
        application: models.SpeciesFilterApplication,
        *,
        status: models.SpeciesFilterApplicationStatus | None = None,
        started_on: datetime.datetime | None = None,
        completed_on: datetime.datetime | None = None,
        error: dict | None = None,
        progress: float | None = None,
        filtered_detections: int | None = None,
        excluded_detections: int | None = None,
    ) -> None:
        """Update filter application status in database.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        application : models.SpeciesFilterApplication
            The application to update.
        status : models.SpeciesFilterApplicationStatus | None
            New status.
        started_on : datetime.datetime | None
            Start timestamp.
        completed_on : datetime.datetime | None
            Completion timestamp.
        error : dict | None
            Error details.
        progress : float | None
            Progress value (0.0-1.0).
        filtered_detections : int | None
            Count of detections that passed the filter.
        excluded_detections : int | None
            Count of detections excluded by the filter.
        """
        if status is not None:
            application.status = status
        if started_on is not None:
            application.started_on = started_on
        if completed_on is not None:
            application.completed_on = completed_on
        if error is not None:
            application.error = error
        if progress is not None:
            application.progress = progress
        if filtered_detections is not None:
            application.filtered_detections = filtered_detections
        if excluded_detections is not None:
            application.excluded_detections = excluded_detections

        await session.flush()

    async def cancel_current_application(self) -> None:
        """Request cancellation of the current application."""
        if self._current_application is not None:
            logger.info(
                "Cancellation requested for application %s",
                self._current_application,
            )
            self._cancel_requested = True
        else:
            logger.warning("No application currently running to cancel")
