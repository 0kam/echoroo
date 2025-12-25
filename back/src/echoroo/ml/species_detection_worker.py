"""Species Detection Worker service for processing automatic species detection jobs.

This module provides a background worker that processes species detection jobs
from the database, runs BirdNET or Perch models, and stores results including
embeddings and predictions.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import exceptions, models, schemas
from echoroo.api import (
    clips,
    clip_embeddings,
    clip_predictions,
    datasets,
    model_runs,
    search_gbif_species,
    tags,
)
from echoroo.ml.base import InferenceEngine, InferenceResult, ModelLoader
from echoroo.ml.filters import (
    BirdNETGeoFilter,
    FilterContext,
    PassThroughFilter,
    SpeciesFilter,
)
from echoroo.ml.registry import ModelNotFoundError, ModelRegistry

__all__ = [
    "SpeciesDetectionWorker",
]

logger = logging.getLogger(__name__)


@dataclass
class _SpeciesSummary:
    gbif_taxon_id: str | None
    annotation_tag_id: int | None
    scientific_name: str
    common_name_ja: str | None
    detections: int = 0
    total_confidence: float = 0.0


class SpeciesDetectionWorker:
    """Background worker for processing species detection jobs.

    This worker polls the database for pending species detection jobs,
    processes them using BirdNET or Perch models, and stores results
    including embeddings and predictions.
    """

    _RUN_STATUS_MAP = {
        "pending": models.FoundationModelRunStatus.QUEUED,
        "running": models.FoundationModelRunStatus.RUNNING,
        "completed": models.FoundationModelRunStatus.COMPLETED,
        "failed": models.FoundationModelRunStatus.FAILED,
        "cancelled": models.FoundationModelRunStatus.CANCELLED,
    }

    def __init__(
        self,
        audio_dir: Path,
        model_dir: Path | None = None,
        poll_interval: float = 5.0,
        batch_size: int = 32,
        use_geo_filter: bool = True,
    ):
        self._audio_dir = audio_dir
        self._model_dir = model_dir
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._use_geo_filter = use_geo_filter
        self._running = False
        self._current_job: UUID | None = None
        self._cancel_requested = False
        self._task: asyncio.Task | None = None

        # Model loaders and engines (lazy loaded)
        self._loaders: dict[str, ModelLoader] = {}
        self._engines: dict[str, InferenceEngine] = {}

        # Prediction filters (lazy loaded)
        self._geo_filter: SpeciesFilter | None = None
        self._passthrough_filter: SpeciesFilter = PassThroughFilter()
        self._run_species_stats: dict[UUID, dict[str, _SpeciesSummary]] = {}
        self._foundation_run_ids: dict[int, int] = {}
        self._gbif_cache: dict[str, tuple[str | None, str]] = {}

    def _get_geo_filter(self) -> SpeciesFilter:
        """Get or create BirdNET geo filter (lazy loaded)."""
        if not self._use_geo_filter:
            return self._passthrough_filter

        if self._geo_filter is None:
            self._geo_filter = BirdNETGeoFilter()
            if self._geo_filter.is_loaded:
                logger.info("BirdNET geo filter loaded")
            else:
                logger.info("BirdNET geo filter will load on first use")

        return self._geo_filter

    @property
    def is_running(self) -> bool:
        """Check if the worker is currently running."""
        return self._running

    @property
    def current_job(self) -> UUID | None:
        """Get the UUID of the currently processing job."""
        return self._current_job

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
        """Main processing loop."""
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
    ) -> schemas.SpeciesDetectionJob | None:
        """Get the next pending job from the database."""
        try:
            # Query for pending jobs
            stmt = (
                select(models.SpeciesDetectionJob)
                .where(
                    models.SpeciesDetectionJob.status
                    == models.SpeciesDetectionJobStatus.PENDING
                )
                .order_by(models.SpeciesDetectionJob.id)
                .limit(1)
            )
            result = await session.execute(stmt)
            db_job = result.scalar_one_or_none()

            if db_job is None:
                return None

            # Build schema manually
            return schemas.SpeciesDetectionJob(
                uuid=db_job.uuid,
                id=db_job.id,
                name=db_job.name,
                dataset_id=db_job.dataset_id,
                created_by_id=db_job.created_by_id,
                model_name=db_job.model_name,
                model_version=db_job.model_version,
                confidence_threshold=db_job.confidence_threshold,
                overlap=db_job.overlap,
                use_metadata_filter=db_job.use_metadata_filter,
                custom_species_list=db_job.custom_species_list,
                recording_filters=db_job.recording_filters,
                status=schemas.SpeciesDetectionJobStatus(db_job.status),
                progress=db_job.progress,
                total_recordings=db_job.total_recordings,
                processed_recordings=db_job.processed_recordings,
                total_clips=db_job.total_clips,
                total_detections=db_job.total_detections,
                error_message=db_job.error_message,
                started_on=db_job.started_on,
                completed_on=db_job.completed_on,
                model_run_id=db_job.model_run_id,
            )

        except Exception as e:
            logger.error("Failed to fetch pending jobs: %s", e)
            return None

    async def process_job(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
    ) -> None:
        """Process a single species detection job."""
        logger.info("Processing species detection job %s", job.uuid)
        self._cancel_requested = False

        tracked_run = await self._get_foundation_model_run(session, job)
        if tracked_run is not None and job.id is not None:
            self._foundation_run_ids[job.id] = tracked_run.id
            self._run_species_stats[job.uuid] = {}

        try:
            # Get or create model run
            model_run = await self._get_or_create_model_run(session, job)

            # Mark job as running
            await self._update_job_status(
                session,
                job,
                status=models.SpeciesDetectionJobStatus.RUNNING,
                started_on=datetime.datetime.now(datetime.UTC),
                model_run_id=model_run.id,
            )
            await session.commit()

            # Get filtered recordings
            recording_list = await self._get_filtered_recordings(session, job)

            if not recording_list:
                logger.warning("No recordings found for job %s", job.uuid)
                await self._persist_species_summary(session, job)
                await self._update_job_status(
                    session,
                    job,
                    status=models.SpeciesDetectionJobStatus.COMPLETED,
                    completed_on=datetime.datetime.now(datetime.UTC),
                )
                await session.commit()
                return

            # Update total recordings
            await self._update_job_progress(
                session,
                job,
                total_recordings=len(recording_list),
            )
            await session.commit()

            # Ensure model is loaded
            engine = self._ensure_model_loaded(job)

            # Get prediction filter
            filter_instance = self._get_filter(job)

            # Process each recording
            total_clips = 0
            total_detections = 0

            for i, recording in enumerate(recording_list):
                if self._cancel_requested:
                    logger.info("Job %s cancelled by user", job.uuid)
                    await self._update_job_status(
                        session,
                        job,
                        status=models.SpeciesDetectionJobStatus.CANCELLED,
                    )
                    await session.commit()
                    return

                try:
                    clips_count, detections_count = await self._process_recording(
                        session,
                        recording,
                        model_run,
                        engine,
                        filter_instance,
                        job,
                    )
                    total_clips += clips_count
                    total_detections += detections_count

                except Exception as e:
                    logger.error(
                        "Error processing recording %s: %s",
                        recording.uuid,
                        e,
                    )

                # Update progress
                progress = (i + 1) / len(recording_list)
                await self._update_job_progress(
                    session,
                    job,
                    processed_recordings=i + 1,
                    total_clips=total_clips,
                    total_detections=total_detections,
                    progress=progress,
                )
                await session.commit()

            # Mark complete
            await self._persist_species_summary(session, job)
            await self._update_job_status(
                session,
                job,
                status=models.SpeciesDetectionJobStatus.COMPLETED,
                completed_on=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()

            logger.info(
                "Job %s completed: %d clips, %d detections from %d recordings",
                job.uuid,
                total_clips,
                total_detections,
                len(recording_list),
            )

        except Exception as e:
            logger.exception("Job %s failed: %s", job.uuid, e)
            try:
                await self._update_job_status(
                    session,
                    job,
                    status=models.SpeciesDetectionJobStatus.FAILED,
                    error_message=str(e),
                )
                await session.commit()
            except Exception as commit_error:
                logger.error("Failed to update job status: %s", commit_error)
        finally:
            if job.id is not None:
                self._foundation_run_ids.pop(job.id, None)
            self._run_species_stats.pop(job.uuid, None)

    async def _get_or_create_model_run(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
    ) -> schemas.ModelRun:
        """Get existing model run or create a new one for the job."""
        # Include job UUID in version to ensure uniqueness per job
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
            f"Species detection job {job.uuid}",
            f"threshold={job.confidence_threshold}",
            f"overlap={job.overlap}",
        ]
        if job.use_metadata_filter:
            description_parts.append("metadata_filter=true")
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
        job: schemas.SpeciesDetectionJob,
    ) -> list[schemas.Recording]:
        """Get recordings based on job filters."""
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
        dataset_schema = schemas.Dataset(
            uuid=dataset_obj.uuid,
            id=dataset_obj.id,
            audio_dir=dataset_obj.audio_dir,
            name=dataset_obj.name,
            description=dataset_obj.description,
            recording_count=dataset_obj.recording_count,
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

        # Apply filters if specified
        filters = job.recording_filters
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

    def _ensure_model_loaded(
        self,
        job: schemas.SpeciesDetectionJob,
    ) -> InferenceEngine:
        """Ensure the required model is loaded."""
        model_name = job.model_name

        if model_name in self._engines:
            engine = self._engines[model_name]
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

        logger.info("Loading %s model", model_name)

        loader = loader_class(model_dir=self._model_dir)
        loader.load()
        self._loaders[model_name] = loader

        engine = engine_class(
            loader,
            confidence_threshold=job.confidence_threshold,  # type: ignore[call-arg]
        )
        self._engines[model_name] = engine

        return engine

    def _get_filter(
        self,
        job: schemas.SpeciesDetectionJob,
    ) -> SpeciesFilter:
        """Get appropriate prediction filter."""
        if job.use_metadata_filter:
            return self._get_geo_filter()
        return self._passthrough_filter

    def _create_filter_context(
        self,
        recording: schemas.Recording,
    ) -> FilterContext:
        """Create filter context from recording metadata."""
        return FilterContext.from_recording(
            latitude=recording.latitude,
            longitude=recording.longitude,
            recording_date=recording.date,
        )

    async def _process_recording(
        self,
        session: AsyncSession,
        recording: schemas.Recording,
        model_run: schemas.ModelRun,
        engine: InferenceEngine,
        filter_instance: SpeciesFilter,
        job: schemas.SpeciesDetectionJob,
    ) -> tuple[int, int]:
        """Process a single recording. Returns (clips_count, detections_count)."""
        logger.debug("Processing recording %s", recording.uuid)

        audio_path = self._audio_dir / recording.path

        if not audio_path.exists():
            logger.warning("Audio file not found: %s", audio_path)
            return 0, 0

        filter_context = self._create_filter_context(recording)

        # Run inference
        try:
            results = await self._run_inference(engine, audio_path, job.overlap)
        except Exception as e:
            logger.error("Inference failed for %s: %s", recording.uuid, e)
            return 0, 0

        if not results:
            return 0, 0

        # Store results
        clips_created = 0
        detections_created = 0

        for result in results:
            if self._cancel_requested:
                break

            clip_count, det_count = await self._store_result(
                session,
                recording,
                model_run,
                result,
                filter_instance,
                filter_context,
                job,
            )
            clips_created += clip_count
            detections_created += det_count

        return clips_created, detections_created

    async def _run_inference(
        self,
        engine: InferenceEngine,
        audio_path: Path,
        overlap: float,
    ) -> list[InferenceResult]:
        """Run inference on an audio file."""
        spec = engine.specification
        overlap_seconds = overlap * spec.segment_duration

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
        filter_instance: SpeciesFilter,
        filter_context: FilterContext,
        job: schemas.SpeciesDetectionJob,
    ) -> tuple[int, int]:
        """Store inference result. Returns (clips_count, detections_count)."""
        # Get or create clip
        clip = await self._get_or_create_clip(
            session,
            recording=recording,
            start_time=result.start_time,
            end_time=result.end_time,
        )

        # Store embedding (always, for search functionality)
        embedding_list = result.embedding.tolist()
        await clip_embeddings.create(
            session,
            clip=clip,
            model_run=model_run,
            embedding=embedding_list,
        )

        clips_created = 1
        detections_created = 0

        # Store predictions if available
        if result.predictions:
            # Apply filtering
            filtered_predictions = await filter_instance.filter_predictions(
                result.predictions, filter_context, session
            )

            # Apply custom species list
            if job.custom_species_list:
                filtered_predictions = [
                    (species, conf)
                    for species, conf in filtered_predictions
                    if self._matches_custom_species(species, job.custom_species_list)
                ]

            if filtered_predictions:
                # Create clip prediction
                clip_pred = await clip_predictions.create(
                    session,
                    clip=clip,
                )

                # Link to model run
                await model_runs.add_clip_prediction(
                    session,
                    model_run,
                    clip_pred,
                )

                # Add tags
                for species_label, confidence in filtered_predictions:
                    (
                        tag,
                        scientific_name,
                        common_name,
                        gbif_taxon_id,
                    ) = await self._get_or_create_species_tag(
                        session,
                        species_label,
                    )
                    clip_pred = await clip_predictions.add_tag(
                        session,
                        clip_pred,
                        tag,
                        score=confidence,
                    )
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
    ) -> tuple[schemas.Tag, str, str | None, str | None]:
        """Get or create a species tag."""
        scientific_name, common_name = self._parse_species_label(species_label)
        gbif_taxon_id, canonical_name = await self._resolve_gbif_taxon(scientific_name)

        resolved_name = canonical_name or scientific_name
        tag_value = gbif_taxon_id or resolved_name

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
        scientific_name: str,
    ) -> tuple[str | None, str | None]:
        """Resolve GBIF taxon id for a scientific name."""
        if scientific_name in self._gbif_cache:
            return self._gbif_cache[scientific_name]

        candidates = await search_gbif_species(scientific_name, limit=1)
        if candidates:
            candidate = candidates[0]
            usage_key = candidate.usage_key
            canonical = candidate.canonical_name or scientific_name
        else:
            usage_key = None
            canonical = scientific_name

        self._gbif_cache[scientific_name] = (usage_key, canonical)
        return usage_key, canonical

    def _record_species_summary(
        self,
        job: schemas.SpeciesDetectionJob,
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
                common_name_ja=common_name,
            )
            stats_map[key] = summary

        summary.detections += 1
        summary.total_confidence += confidence

    async def _persist_species_summary(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
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

        total_detections = 0
        for summary in stats_map.values():
            if summary.detections == 0:
                continue
            avg_conf = summary.total_confidence / summary.detections
            session.add(
                models.FoundationModelRunSpecies(
                    foundation_model_run_id=run.id,
                    gbif_taxon_id=summary.gbif_taxon_id,
                    annotation_tag_id=summary.annotation_tag_id,
                    scientific_name=summary.scientific_name,
                    common_name_ja=summary.common_name_ja,
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

    async def _get_foundation_model_run(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
    ) -> models.FoundationModelRun | None:
        """Fetch foundation model run linked to the job."""
        if job.id is None:
            return None

        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.species_detection_job_id == job.id
        )
        return await session.scalar(stmt)

    def _get_tracked_run_id(
        self,
        job: schemas.SpeciesDetectionJob,
    ) -> int | None:
        if job.id is None:
            return None
        return self._foundation_run_ids.get(job.id)

    async def _load_tracked_run(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
    ) -> models.FoundationModelRun | None:
        run_id = self._get_tracked_run_id(job)
        if run_id is None:
            return None
        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.id == run_id,
        )
        return await session.scalar(stmt)

    async def _sync_foundation_run_state(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
        *,
        run_status: models.FoundationModelRunStatus | None = None,
        started_on: datetime.datetime | None = None,
        completed_on: datetime.datetime | None = None,
        error_message: str | None = None,
        model_run_id: int | None = None,
        total_recordings: int | None = None,
        processed_recordings: int | None = None,
        total_clips: int | None = None,
        total_detections: int | None = None,
        progress: float | None = None,
    ) -> None:
        """Sync job data to foundation model run if linked."""
        run = await self._load_tracked_run(session, job)
        if run is None:
            return

        if run_status is not None:
            run.status = run_status
        if started_on is not None:
            run.started_on = started_on
        if completed_on is not None:
            run.completed_on = completed_on
        if error_message is not None:
            run.error = {"message": error_message}
        if model_run_id is not None:
            run.model_run_id = model_run_id
        if total_recordings is not None:
            run.total_recordings = total_recordings
        if processed_recordings is not None:
            run.processed_recordings = processed_recordings
        if total_clips is not None:
            run.total_clips = total_clips
        if total_detections is not None:
            run.total_detections = total_detections
        if progress is not None:
            run.progress = progress

        await session.flush()

    async def _update_job_status(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
        *,
        status: str | None = None,
        started_on: datetime.datetime | None = None,
        completed_on: datetime.datetime | None = None,
        error_message: str | None = None,
        model_run_id: int | None = None,
    ) -> None:
        """Update job status in database."""
        stmt = select(models.SpeciesDetectionJob).where(
            models.SpeciesDetectionJob.uuid == job.uuid
        )
        result = await session.execute(stmt)
        db_job = result.scalar_one()

        if status is not None:
            db_job.status = status
        if started_on is not None:
            db_job.started_on = started_on
        if completed_on is not None:
            db_job.completed_on = completed_on
        if error_message is not None:
            db_job.error_message = error_message
        if model_run_id is not None:
            db_job.model_run_id = model_run_id

        status_value = getattr(status, "value", status) if status is not None else None
        run_status = self._RUN_STATUS_MAP.get(status_value) if status_value else None
        await self._sync_foundation_run_state(
            session,
            job,
            run_status=run_status,
            started_on=started_on,
            completed_on=completed_on,
            error_message=error_message,
            model_run_id=model_run_id,
        )

        await session.flush()

    async def _update_job_progress(
        self,
        session: AsyncSession,
        job: schemas.SpeciesDetectionJob,
        *,
        total_recordings: int | None = None,
        processed_recordings: int | None = None,
        total_clips: int | None = None,
        total_detections: int | None = None,
        progress: float | None = None,
    ) -> None:
        """Update job progress in database."""
        stmt = select(models.SpeciesDetectionJob).where(
            models.SpeciesDetectionJob.uuid == job.uuid
        )
        result = await session.execute(stmt)
        db_job = result.scalar_one()

        if total_recordings is not None:
            db_job.total_recordings = total_recordings
        if processed_recordings is not None:
            db_job.processed_recordings = processed_recordings
        if total_clips is not None:
            db_job.total_clips = total_clips
        if total_detections is not None:
            db_job.total_detections = total_detections
        if progress is not None:
            db_job.progress = progress

        await self._sync_foundation_run_state(
            session,
            job,
            total_recordings=total_recordings,
            processed_recordings=processed_recordings,
            total_clips=total_clips,
            total_detections=total_detections,
            progress=progress,
        )

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

    def unload_models(self) -> None:
        """Unload all loaded models."""
        for model_name, loader in self._loaders.items():
            loader.unload()
            logger.info("%s model unloaded", model_name)

        self._loaders.clear()
        self._engines.clear()
