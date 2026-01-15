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

import h3
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

    def _get_location_bucket(
        self, context: FilterContext
    ) -> tuple[int, int, int] | None:
        """Get location bucket key for caching (1-degree grid).

        Parameters
        ----------
        context : FilterContext
            Location and time context.

        Returns
        -------
        tuple[int, int, int] | None
            (lat_bucket, lon_bucket, week) for cache key,
            or None if context is invalid.
        """
        if not context.is_valid:
            return None

        # 1-degree grid resolution
        lat_bucket = int(context.latitude // 1)  # type: ignore[operator]
        lon_bucket = int(context.longitude // 1)  # type: ignore[operator]
        return (lat_bucket, lon_bucket, context.week)  # type: ignore[return-value]

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
        """Process a single species filter application using batch processing.

        This method uses a 4-step batch processing approach to minimize
        redundant GBIF lookups and geo model calls:

        1. Data Collection: Scan all predictions and collect unique (bucket, taxon_key) pairs
        2. Batch Probability Fetch: Get probabilities for each unique bucket once
        3. Filter Result Calculation: Compute filter results for unique combinations
        4. Mask Creation: Create mask records using lookup from pre-computed results

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
            logger.info("Fetching predictions for model run %d", model_run_id)
            predictions = await self._get_predictions(session, model_run_id)
            logger.info("Fetched %d predictions", len(predictions))

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

            # Check for cancellation (either via flag or database status)
            await session.refresh(application)
            if self._cancel_requested or application.status == models.SpeciesFilterApplicationStatus.CANCELLED:
                logger.info("Application %s cancelled by user", application.uuid)
                await self._update_application_status(
                    session,
                    application,
                    status=models.SpeciesFilterApplicationStatus.CANCELLED,
                )
                await session.commit()
                return

            # ============================================================
            # Step 1: Data Collection
            # Scan all predictions and collect unique (bucket, taxon_key) pairs
            # ============================================================
            logger.info("Step 1: Collecting prediction data and unique buckets")

            # Type aliases for clarity
            # Bucket = (lat_bucket, lon_bucket, week)
            prediction_data_list: list[
                tuple[
                    models.ClipPrediction,
                    tuple[int, int, int] | None,
                    list[models.ClipPredictionTag],
                ]
            ] = []
            bucket_taxon_keys: dict[tuple[int, int, int], set[str]] = {}
            # Cache taxon_key -> canonical_name mapping from existing Tags
            # to avoid GBIF API reverse lookups
            taxon_key_to_scientific_name: dict[str, str] = {}

            for prediction in predictions:
                # Get recording metadata for filter context
                recording = prediction.clip.recording

                # Use direct lat/lng if available, otherwise convert from h3_index
                latitude = recording.latitude
                longitude = recording.longitude
                if latitude is None and longitude is None and recording.h3_index:
                    try:
                        latitude, longitude = h3.cell_to_latlng(recording.h3_index)
                    except Exception as e:
                        logger.debug(
                            "Failed to convert h3_index %s to lat/lng: %s",
                            recording.h3_index,
                            e,
                        )

                # Use date if available, otherwise extract date from datetime
                recording_date = recording.date
                if recording_date is None and recording.datetime is not None:
                    recording_date = recording.datetime.date()

                filter_context = FilterContext.from_recording(
                    latitude=latitude,
                    longitude=longitude,
                    recording_date=recording_date,
                )

                # Get bucket for this context
                bucket = self._get_location_bucket(filter_context)

                # Collect tags for this prediction
                tags = list(prediction.tags)

                # Store prediction data
                prediction_data_list.append((prediction, bucket, tags))

                # Collect unique taxon keys per bucket
                if bucket is not None:
                    if bucket not in bucket_taxon_keys:
                        bucket_taxon_keys[bucket] = set()
                    for pred_tag in tags:
                        taxon_key = pred_tag.tag.value
                        bucket_taxon_keys[bucket].add(taxon_key)

                        # Cache the canonical_name from Tag to avoid GBIF API lookups
                        if taxon_key not in taxon_key_to_scientific_name:
                            # Use lowercase for matching with BirdNET raw probabilities
                            taxon_key_to_scientific_name[taxon_key] = (
                                pred_tag.tag.canonical_name.lower()
                            )

            logger.info(
                "Collected %d predictions with %d unique buckets",
                len(prediction_data_list),
                len(bucket_taxon_keys),
            )

            # Check for cancellation (either via flag or database status)
            await session.refresh(application)
            if self._cancel_requested or application.status == models.SpeciesFilterApplicationStatus.CANCELLED:
                logger.info("Application %s cancelled by user", application.uuid)
                await self._update_application_status(
                    session,
                    application,
                    status=models.SpeciesFilterApplicationStatus.CANCELLED,
                )
                await session.commit()
                return

            # ============================================================
            # Step 2: Batch Probability Fetch
            # Get probabilities for each unique bucket once
            # ============================================================
            logger.info("Step 2: Fetching probabilities for %d unique buckets", len(bucket_taxon_keys))

            # Check if filter supports batch probability fetching
            use_batch_probs = hasattr(filter_instance, "get_probabilities_for_taxon_keys")

            # bucket -> {taxon_key: probability}
            bucket_probs: dict[tuple[int, int, int], dict[str, float]] = {}

            for idx, (bucket, taxon_keys) in enumerate(bucket_taxon_keys.items()):
                # Check for cancellation periodically (either via flag or database status)
                if idx % 10 == 0:
                    await session.refresh(application)
                if self._cancel_requested or application.status == models.SpeciesFilterApplicationStatus.CANCELLED:
                    logger.info("Application %s cancelled by user", application.uuid)
                    await self._update_application_status(
                        session,
                        application,
                        status=models.SpeciesFilterApplicationStatus.CANCELLED,
                    )
                    await session.commit()
                    return

                # Create a context for this bucket (use bucket center coordinates)
                lat_bucket, lon_bucket, week = bucket
                bucket_context = FilterContext(
                    latitude=float(lat_bucket) + 0.5,
                    longitude=float(lon_bucket) + 0.5,
                    week=week,
                )

                if use_batch_probs:
                    # Use efficient batch method with pre-resolved scientific names
                    probs = await filter_instance.get_probabilities_for_taxon_keys(  # type: ignore[attr-defined]
                        bucket_context, taxon_keys, taxon_key_to_scientific_name
                    )
                    bucket_probs[bucket] = probs
                else:
                    # Fallback: get all probabilities (less efficient)
                    raw_probs = await filter_instance.get_raw_species_probabilities(  # type: ignore[attr-defined]
                        bucket_context
                    )
                    bucket_probs[bucket] = raw_probs if raw_probs else {}

                # Update progress
                if (idx + 1) % 10 == 0 or idx == len(bucket_taxon_keys) - 1:
                    progress = 0.3 * (idx + 1) / len(bucket_taxon_keys)
                    application.progress = progress
                    await session.commit()
                    logger.debug(
                        "Fetched probabilities for %d/%d buckets",
                        idx + 1,
                        len(bucket_taxon_keys),
                    )

            logger.info("Completed probability fetching for all buckets")

            # ============================================================
            # Step 3: Filter Result Calculation
            # Compute filter results for unique (bucket, taxon_key) combinations
            # ============================================================
            logger.info("Step 3: Computing filter results")

            # (bucket, taxon_key) -> (is_included, occurrence_prob, exclusion_reason)
            filter_results: dict[
                tuple[tuple[int, int, int], str],
                tuple[bool, float | None, str | None],
            ] = {}

            threshold = application.threshold

            for bucket, taxon_keys in bucket_taxon_keys.items():
                probs = bucket_probs.get(bucket, {})

                for taxon_key in taxon_keys:
                    occurrence_prob = probs.get(taxon_key)

                    if occurrence_prob is None:
                        # Species not in occurrence data - include by default
                        is_included = True
                        exclusion_reason = None
                    elif occurrence_prob >= threshold:
                        is_included = True
                        exclusion_reason = None
                    else:
                        is_included = False
                        exclusion_reason = (
                            f"Occurrence probability {occurrence_prob:.2%} "
                            f"below threshold {threshold:.2%}"
                        )

                    filter_results[(bucket, taxon_key)] = (
                        is_included,
                        occurrence_prob,
                        exclusion_reason,
                    )

            logger.info(
                "Computed filter results for %d unique (bucket, taxon_key) combinations",
                len(filter_results),
            )

            # ============================================================
            # Step 4: Mask Creation
            # Create mask records using lookup from pre-computed results
            # ============================================================
            logger.info("Step 4: Creating mask records")

            filtered_count = 0
            excluded_count = 0
            processed = 0

            for prediction, bucket, tags in prediction_data_list:
                # Check for cancellation periodically (either via flag or database status)
                if processed % self._batch_size == 0:
                    await session.refresh(application)
                    if self._cancel_requested or application.status == models.SpeciesFilterApplicationStatus.CANCELLED:
                        logger.info("Application %s cancelled by user", application.uuid)
                        await self._update_application_status(
                            session,
                            application,
                            status=models.SpeciesFilterApplicationStatus.CANCELLED,
                        )
                        await session.commit()
                        return

                for pred_tag in tags:
                    tag = pred_tag.tag
                    taxon_key = tag.value

                    if bucket is None:
                        # Invalid context - include by default
                        is_included = True
                        occurrence_prob = None
                        exclusion_reason = (
                            "Invalid filter context (missing location/date)"
                        )
                    else:
                        # Look up pre-computed result
                        result = filter_results.get((bucket, taxon_key))
                        if result is not None:
                            is_included, occurrence_prob, exclusion_reason = result
                        else:
                            # Should not happen, but handle gracefully
                            is_included = True
                            occurrence_prob = None
                            exclusion_reason = None

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
                    progress = 0.3 + 0.7 * (processed / len(prediction_data_list))
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
                "Application %s completed: %d filtered, %d excluded from %d total "
                "(processed %d unique buckets)",
                application.uuid,
                filtered_count,
                excluded_count,
                total_detections,
                len(bucket_taxon_keys),
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
