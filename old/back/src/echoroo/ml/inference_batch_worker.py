"""Inference Batch Worker service for processing batch inference jobs.

This module provides a background worker that processes inference batch jobs
from the database, runs trained custom models on audio clip embeddings, and
stores predictions as InferencePrediction records.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from echoroo import models
from echoroo.ml.classifiers import UnifiedClassifier

__all__ = [
    "InferenceBatchWorker",
]

logger = logging.getLogger(__name__)


class InferenceBatchWorker:
    """Background worker for processing inference batches.

    This worker polls the database for pending inference batches,
    processes them by running trained custom models on clip embeddings,
    and stores predictions with confidence scores.
    """

    def __init__(
        self,
        model_dir: Path,
        poll_interval: float = 5.0,
        batch_size: int = 1000,
    ):
        """Initialize the inference batch worker.

        Parameters
        ----------
        model_dir : Path
            Directory containing trained model files.
        poll_interval : float
            Seconds between polling for new batches.
        batch_size : int
            Number of clips to process per batch iteration.
        """
        self._model_dir = model_dir
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._running = False
        self._current_batch: UUID | None = None
        self._cancel_requested = False
        self._task: asyncio.Task | None = None

        # Lazy-loaded models cache
        self._models: dict[int, object] = {}

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running

    @property
    def current_batch(self) -> UUID | None:
        """Get the UUID of the currently processing batch."""
        return self._current_batch

    async def start(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Start processing inference batches.

        Parameters
        ----------
        session_factory : Callable[[], AsyncSession]
            Factory function that creates new database sessions.
        """
        if self._running:
            logger.warning("Inference batch worker is already running")
            return

        self._running = True
        self._cancel_requested = False

        logger.info("Starting inference batch worker")

        self._task = asyncio.create_task(
            self._run_loop(session_factory),
            name="inference_batch_worker",
        )

    async def stop(self) -> None:
        """Stop processing gracefully."""
        if not self._running:
            logger.warning("Inference batch worker is not running")
            return

        logger.info("Stopping inference batch worker")
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

        # Clear model cache
        self._models.clear()

        logger.info("Inference batch worker stopped")

    async def _run_loop(
        self,
        session_factory: Callable[[], AsyncSession],
    ) -> None:
        """Main processing loop."""
        while self._running:
            try:
                async with session_factory() as session:
                    batch = await self._get_next_batch(session)

                    if batch is not None:
                        self._current_batch = batch.uuid
                        try:
                            await self.process_batch(session, batch)
                        finally:
                            self._current_batch = None
                    else:
                        await asyncio.sleep(self._poll_interval)

            except Exception as e:
                logger.exception("Error in worker loop: %s", e)
                await asyncio.sleep(self._poll_interval)

    async def _get_next_batch(
        self,
        session: AsyncSession,
    ) -> models.InferenceBatch | None:
        """Get the next running inference batch from the database.

        Parameters
        ----------
        session : AsyncSession
            Database session.

        Returns
        -------
        models.InferenceBatch | None
            The next running batch, or None if none available.
        """
        try:
            stmt = (
                select(models.InferenceBatch)
                .options(
                    joinedload(models.InferenceBatch.custom_model),
                    joinedload(models.InferenceBatch.dataset_scopes).options(
                        joinedload(models.InferenceBatchDatasetScope.dataset),
                        joinedload(models.InferenceBatchDatasetScope.foundation_model_run),
                    ),
                )
                .where(
                    models.InferenceBatch.status
                    == models.InferenceBatchStatus.RUNNING
                )
                .order_by(models.InferenceBatch.id)
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.unique().scalar_one_or_none()

        except Exception as e:
            logger.error("Failed to fetch running batches: %s", e)
            return None

    async def _is_batch_cancelled(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
    ) -> bool:
        """Check if the batch has been cancelled in the database.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The batch to check.

        Returns
        -------
        bool
            True if cancelled, False otherwise.
        """
        stmt = select(models.InferenceBatch.status).where(
            models.InferenceBatch.id == batch.id
        )
        result = await session.execute(stmt)
        status = result.scalar_one_or_none()
        return status == models.InferenceBatchStatus.CANCELLED

    async def process_batch(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
    ) -> None:
        """Process a single inference batch.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The batch to process.
        """
        logger.info("Processing inference batch %s", batch.uuid)
        self._cancel_requested = False

        try:
            # Load the custom model
            model = await self._load_model(session, batch.custom_model)
            if model is None:
                raise ValueError(
                    f"Failed to load custom model {batch.custom_model_id}"
                )

            # Get total clips count
            total_clips = await self._count_clips(session, batch)
            if total_clips == 0:
                logger.warning("No clips found for batch %s", batch.uuid)
                await self._update_batch_status(
                    session,
                    batch,
                    status=models.InferenceBatchStatus.COMPLETED,
                    completed_on=datetime.now(timezone.utc),
                )
                await session.commit()
                return

            # Update total items
            batch.total_items = total_clips
            await session.commit()

            # Process clips in batches
            processed_count = 0
            positive_count = 0
            total_positive_predictions = 0
            total_negative_predictions = 0
            total_confidence_sum = 0.0
            offset = 0

            while offset < total_clips:
                # Check for cancellation
                if self._cancel_requested or await self._is_batch_cancelled(
                    session, batch
                ):
                    logger.info("Batch %s cancelled", batch.uuid)
                    await self._update_batch_status(
                        session,
                        batch,
                        status=models.InferenceBatchStatus.CANCELLED,
                    )
                    await session.commit()
                    return

                # Get clips for this batch
                clips_data = await self._get_clips_batch(
                    session, batch, offset, self._batch_size
                )

                if not clips_data:
                    break

                # Run inference on this batch
                (
                    batch_positives,
                    batch_positive_predictions,
                    batch_negative_predictions,
                    batch_confidence_sum,
                ) = await self._run_inference(
                    session, batch, model, clips_data
                )

                processed_count += len(clips_data)
                positive_count += batch_positives
                total_positive_predictions += batch_positive_predictions
                total_negative_predictions += batch_negative_predictions
                total_confidence_sum += batch_confidence_sum

                # Calculate average confidence
                avg_confidence = None
                if processed_count > 0:
                    avg_confidence = round(total_confidence_sum / processed_count, 4)

                # Update progress
                progress = processed_count / total_clips
                await self._update_batch_progress(
                    session,
                    batch,
                    processed_items=processed_count,
                    positive_predictions=positive_count,
                    positive_predictions_count=total_positive_predictions,
                    negative_predictions_count=total_negative_predictions,
                    average_confidence=avg_confidence,
                    progress=progress,
                )
                await session.commit()

                offset += self._batch_size

                logger.debug(
                    "Batch %s: processed %d/%d clips (%d positives)",
                    batch.uuid,
                    processed_count,
                    total_clips,
                    positive_count,
                )

            # Mark complete
            await self._update_batch_status(
                session,
                batch,
                status=models.InferenceBatchStatus.COMPLETED,
                completed_on=datetime.now(timezone.utc),
            )
            await session.commit()

            logger.info(
                "Batch %s completed: %d/%d clips processed, %d positives",
                batch.uuid,
                processed_count,
                total_clips,
                positive_count,
            )

        except Exception as e:
            logger.exception("Batch %s failed: %s", batch.uuid, e)
            try:
                await self._update_batch_status(
                    session,
                    batch,
                    status=models.InferenceBatchStatus.FAILED,
                    error_message=str(e),
                )
                await session.commit()
            except Exception as commit_error:
                logger.error("Failed to update batch status: %s", commit_error)

    async def _load_model(
        self,
        session: AsyncSession,
        custom_model: models.CustomModel,
    ) -> object | None:
        """Load a custom model from disk.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        custom_model : models.CustomModel
            The custom model to load.

        Returns
        -------
        object | None
            Loaded model object, or None if loading fails.
        """
        # Check cache first
        if custom_model.id in self._models:
            return self._models[custom_model.id]

        # Verify model is trained
        if custom_model.status not in (
            models.CustomModelStatus.TRAINED,
            models.CustomModelStatus.DEPLOYED,
        ):
            logger.error(
                "Custom model %s is not trained (status: %s)",
                custom_model.id,
                custom_model.status,
            )
            return None

        # Verify model file exists
        if not custom_model.model_path:
            logger.error("Custom model %s has no model_path", custom_model.id)
            return None

        model_path = self._model_dir / custom_model.model_path
        if not model_path.exists():
            logger.error("Model file not found: %s", model_path)
            return None

        try:
            # Load model using UnifiedClassifier.load()
            logger.info("Loading custom model from %s", model_path)
            model = UnifiedClassifier.load(model_path)

            # Cache the model
            self._models[custom_model.id] = model

            return model

        except Exception as e:
            logger.error(
                "Failed to load custom model from %s: %s", model_path, e
            )
            return None

    async def _count_clips(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
    ) -> int:
        """Count total clips to process for a batch.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The batch to count clips for.

        Returns
        -------
        int
            Total number of clips to process.
        """
        from sqlalchemy import func

        total_clips = 0

        for dataset_scope in batch.dataset_scopes:
            # Count clips that have embeddings from the foundation model run
            stmt = (
                select(func.count(models.Clip.id))
                .join(
                    models.Recording, models.Clip.recording_id == models.Recording.id
                )
                .join(
                    models.DatasetRecording,
                    models.Recording.id == models.DatasetRecording.recording_id,
                )
                .join(
                    models.ClipEmbedding,
                    models.Clip.id == models.ClipEmbedding.clip_id,
                )
                .join(
                    models.ModelRun,
                    models.ClipEmbedding.model_run_id == models.ModelRun.id,
                )
                .where(
                    models.DatasetRecording.dataset_id == dataset_scope.dataset_id
                )
                .where(
                    models.ModelRun.id == dataset_scope.foundation_model_run.model_run_id
                )
            )

            count = await session.scalar(stmt) or 0
            total_clips += count

        return total_clips

    async def _get_clips_batch(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
        offset: int,
        limit: int,
    ) -> list[tuple[int, int, np.ndarray]]:
        """Get a batch of clips with their embeddings using raw SQL.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The inference batch.
        offset : int
            Starting offset.
        limit : int
            Maximum number of clips to fetch.

        Returns
        -------
        list[tuple[int, int, np.ndarray]]
            List of (clip_id, dataset_scope_id, embedding) tuples.
        """
        # Build dataset scope filters
        dataset_scope_filters = []
        for ds in batch.dataset_scopes:
            dataset_scope_filters.append(
                f"(dr.dataset_id = {ds.dataset_id} AND "
                f"fmr.model_run_id = {ds.foundation_model_run.model_run_id})"
            )

        if not dataset_scope_filters:
            return []

        scope_filter_sql = " OR ".join(dataset_scope_filters)

        # Use raw SQL to avoid SQLAlchemy ORM's automatic eager loading
        query = f"""
            SELECT DISTINCT ON (c.id)
                c.id as clip_id,
                dr.dataset_id,
                ce.embedding
            FROM clip c
            JOIN recording r ON c.recording_id = r.id
            JOIN dataset_recording dr ON r.id = dr.recording_id
            JOIN clip_embedding ce ON c.id = ce.clip_id
            JOIN model_run mr ON ce.model_run_id = mr.id
            JOIN inference_batch_dataset_scope ibds ON dr.dataset_id = ibds.dataset_id
            JOIN foundation_model_run fmr ON ibds.foundation_model_run_id = fmr.id
            WHERE ibds.inference_batch_id = :batch_id
              AND ({scope_filter_sql})
            ORDER BY c.id
            OFFSET :offset
            LIMIT :limit
        """

        result = await session.execute(
            text(query),
            {"batch_id": batch.id, "offset": offset, "limit": limit},
        )
        rows = result.fetchall()

        clips_data: list[tuple[int, int, np.ndarray]] = []
        expected_shape: tuple[int, ...] | None = None

        for row in rows:
            # Parse embedding (may be JSON string or array)
            emb = row.embedding
            if isinstance(emb, str):
                emb = json.loads(emb)
            embedding = np.array(emb, dtype=np.float32)

            # Check for NaN or Inf values
            if np.isnan(embedding).any() or np.isinf(embedding).any():
                logger.warning(
                    "Skipping clip %d: embedding contains NaN or Inf values",
                    row.clip_id,
                )
                continue

            # Validate embedding shape consistency
            if expected_shape is None:
                expected_shape = embedding.shape
            elif embedding.shape != expected_shape:
                logger.warning(
                    "Skipping clip %d: embedding shape %s doesn't match expected %s",
                    row.clip_id,
                    embedding.shape,
                    expected_shape,
                )
                continue

            clips_data.append((row.clip_id, row.dataset_id, embedding))

        return clips_data

    async def _run_inference(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
        model: Any,
        clips_data: list[tuple[int, int, np.ndarray]],
    ) -> tuple[int, int, int, float]:
        """Run inference on a batch of clips.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The inference batch.
        model : object
            Loaded custom model.
        clips_data : list[tuple[int, int, np.ndarray]]
            List of (clip_id, dataset_id, embedding) tuples.

        Returns
        -------
        tuple[int, int, int, float]
            Tuple of (positive_count, positive_predictions_count, negative_predictions_count, sum_confidence).
        """
        if not clips_data:
            return 0, 0, 0, 0.0

        # Extract embeddings
        embeddings = np.array([emb for _, _, emb in clips_data])

        # Run inference
        try:
            # Use predict_proba to get confidence scores
            probabilities = model.predict_proba(embeddings)

            # For binary classification, get probability of positive class
            if probabilities.ndim == 2 and probabilities.shape[1] == 2:
                # Get probability of class 1 (positive)
                positive_probs = probabilities[:, 1]
            else:
                # Single class or 1D output
                positive_probs = probabilities

        except Exception as e:
            logger.error("Inference failed for batch %s: %s", batch.uuid, e)
            raise

        # Create predictions and collect statistics
        positive_count = 0
        positive_predictions_count = 0
        negative_predictions_count = 0
        sum_confidence = 0.0
        threshold = batch.confidence_threshold

        for (clip_id, dataset_id, _), confidence in zip(clips_data, positive_probs):
            predicted_positive = confidence >= threshold
            confidence_float = float(confidence)

            # Create prediction record
            prediction = models.InferencePrediction(
                inference_batch_id=batch.id,
                clip_id=clip_id,
                confidence=confidence_float,
                predicted_positive=predicted_positive,
            )
            session.add(prediction)

            # Update statistics
            sum_confidence += confidence_float
            if predicted_positive:
                positive_count += 1
                positive_predictions_count += 1
            else:
                negative_predictions_count += 1

        # Flush to database
        await session.flush()

        return positive_count, positive_predictions_count, negative_predictions_count, sum_confidence

    async def _update_batch_status(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
        *,
        status: models.InferenceBatchStatus | None = None,
        started_on: datetime | None = None,
        completed_on: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update batch status in database.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The batch to update.
        status : models.InferenceBatchStatus | None
            New status.
        started_on : datetime | None
            Start timestamp.
        completed_on : datetime | None
            Completion timestamp.
        error_message : str | None
            Error message if failed.
        """
        if status is not None:
            batch.status = status
        if started_on is not None:
            batch.started_on = started_on
        if completed_on is not None:
            batch.completed_on = completed_on
        if error_message is not None:
            batch.error_message = error_message

        await session.flush()

    async def _update_batch_progress(
        self,
        session: AsyncSession,
        batch: models.InferenceBatch,
        *,
        processed_items: int | None = None,
        positive_predictions: int | None = None,
        positive_predictions_count: int | None = None,
        negative_predictions_count: int | None = None,
        average_confidence: float | None = None,
        progress: float | None = None,
    ) -> None:
        """Update batch progress in database.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        batch : models.InferenceBatch
            The batch to update.
        processed_items : int | None
            Number of items processed.
        positive_predictions : int | None
            Number of positive predictions.
        positive_predictions_count : int | None
            Number of predictions with positive label.
        negative_predictions_count : int | None
            Number of predictions with negative label.
        average_confidence : float | None
            Average confidence score across all predictions.
        progress : float | None
            Progress value (0.0-1.0).
        """
        if processed_items is not None:
            batch.processed_items = processed_items
        if positive_predictions is not None:
            batch.positive_predictions = positive_predictions
        if positive_predictions_count is not None:
            batch.positive_predictions_count = positive_predictions_count
        if negative_predictions_count is not None:
            batch.negative_predictions_count = negative_predictions_count
        if average_confidence is not None:
            batch.average_confidence = average_confidence
        if progress is not None:
            batch.progress = progress

        await session.flush()

    async def cancel_current_batch(self) -> None:
        """Request cancellation of the current batch."""
        if self._current_batch is not None:
            logger.info("Cancellation requested for batch %s", self._current_batch)
            self._cancel_requested = True
        else:
            logger.warning("No batch currently running to cancel")
