"""API helpers for foundation models and runs."""

from __future__ import annotations

import datetime
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql import ColumnElement

from echoroo import exceptions, models, schemas
from echoroo.api import datasets, common
from echoroo.api.common.permissions import can_manage_project

__all__ = ["foundation_models"]


async def _get_dataset_project_id(
    session: AsyncSession,
    dataset_id: int,
) -> str | None:
    """Get the project_id for a dataset."""
    dataset = await session.get(models.Dataset, dataset_id)
    return dataset.project_id if dataset else None


async def can_view_foundation_model_run(
    session: AsyncSession,
    run: models.FoundationModelRun | schemas.FoundationModelRun,
    user: models.User | None,
) -> bool:
    """Return True if the user can view the foundation model run."""
    if user is None:
        return False
    if user.is_superuser:
        return True

    # Requester can always view
    if hasattr(run, "requested_by_id") and run.requested_by_id == user.id:
        return True

    # Check project membership via dataset
    project_id = await _get_dataset_project_id(session, run.dataset_id)
    if project_id:
        membership = await session.scalar(
            select(models.ProjectMember).where(
                models.ProjectMember.project_id == project_id,
                models.ProjectMember.user_id == user.id,
            )
        )
        return membership is not None

    return False


async def can_edit_foundation_model_run(
    session: AsyncSession,
    run: models.FoundationModelRun | schemas.FoundationModelRun,
    user: models.User | None,
) -> bool:
    """Return True if the user can edit the foundation model run."""
    if user is None:
        return False
    if user.is_superuser:
        return True
    if hasattr(run, "requested_by_id") and run.requested_by_id == user.id:
        return True

    project_id = await _get_dataset_project_id(session, run.dataset_id)
    if project_id:
        return await can_manage_project(session, project_id, user)
    return False


async def filter_runs_by_access(
    session: AsyncSession,
    user: models.User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting runs accessible to the user."""
    if user is None:
        return [models.FoundationModelRun.id == -1]
    if user.is_superuser:
        return []

    # Get dataset IDs user has access to via project membership
    accessible_dataset_ids_query = (
        select(models.Dataset.id)
        .join(models.Project, models.Dataset.project_id == models.Project.project_id)
        .join(models.ProjectMember, models.Project.project_id == models.ProjectMember.project_id)
        .where(models.ProjectMember.user_id == user.id)
    )
    accessible_dataset_ids = (await session.scalars(accessible_dataset_ids_query)).all()

    conditions: list[ColumnElement[bool]] = [
        models.FoundationModelRun.requested_by_id == user.id,
    ]
    if accessible_dataset_ids:
        conditions.append(models.FoundationModelRun.dataset_id.in_(accessible_dataset_ids))

    return [or_(*conditions)]


class FoundationModelAPI:
    """Service for managing foundation model runs."""

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        """Resolve a user schema to a user model."""
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(f"User with id {user.id} not found")
        return db_user

    async def list_models(
        self,
        session: AsyncSession,
        *,
        include_inactive: bool = False,
    ) -> list[schemas.FoundationModel]:
        stmt = select(models.FoundationModel)
        if not include_inactive:
            stmt = stmt.where(models.FoundationModel.is_active.is_(True))
        stmt = stmt.order_by(models.FoundationModel.display_name.asc())
        result = await session.scalars(stmt)
        return [
            schemas.FoundationModel.model_validate(obj)
            for obj in result.unique().all()
        ]

    async def get_model_by_slug(
        self,
        session: AsyncSession,
        slug: str,
    ) -> models.FoundationModel:
        stmt = select(models.FoundationModel).where(
            models.FoundationModel.slug == slug,
        )
        model = await session.scalar(stmt)
        if model is None:
            raise exceptions.NotFoundError(f"Foundation model {slug} not found")
        return model

    async def get_dataset_summary(
        self,
        session: AsyncSession,
        dataset_obj: schemas.Dataset,
    ) -> list[schemas.DatasetFoundationModelSummary]:
        summaries: list[schemas.DatasetFoundationModelSummary] = []
        models_list = await self.list_models(session)

        for model in models_list:
            latest_run = await self._get_latest_run(
                session,
                dataset_obj.id,
                model.id,
            )
            completed_run = await self._get_latest_run(
                session,
                dataset_obj.id,
                model.id,
                status=models.FoundationModelRunStatus.COMPLETED,
            )
            summaries.append(
                schemas.DatasetFoundationModelSummary(
                    foundation_model=model,
                    latest_run=latest_run,
                    last_completed_run=completed_run,
                )
            )

        return summaries

    async def _get_latest_run(
        self,
        session: AsyncSession,
        dataset_id: int,
        model_id: int,
        *,
        status: models.FoundationModelRunStatus | None = None,
    ) -> schemas.FoundationModelRun | None:
        stmt = (
            select(models.FoundationModelRun)
            .options(
                joinedload(models.FoundationModelRun.foundation_model),
                joinedload(models.FoundationModelRun.requested_by),
            )
            .where(
                models.FoundationModelRun.dataset_id == dataset_id,
                models.FoundationModelRun.foundation_model_id == model_id,
            )
            .order_by(models.FoundationModelRun.created_on.desc())
            .limit(1)
        )
        if status is not None:
            stmt = stmt.where(models.FoundationModelRun.status == status)

        run = await session.scalar(stmt)
        if run is None:
            return None
        return schemas.FoundationModelRun.model_validate(run)

    async def list_runs(
        self,
        session: AsyncSession,
        *,
        dataset_id: int | None = None,
        foundation_model_id: int | None = None,
        status: models.FoundationModelRunStatus | None = None,
        limit: int = 20,
        offset: int = 0,
        user: models.User | None = None,
    ) -> tuple[list[schemas.FoundationModelRun], int]:
        base_query = select(models.FoundationModelRun)

        # Apply dataset filter if provided
        if dataset_id is not None:
            base_query = base_query.where(
                models.FoundationModelRun.dataset_id == dataset_id,
            )
        else:
            # When no dataset is specified, filter by user access
            access_filters = await filter_runs_by_access(session, user)
            for condition in access_filters:
                base_query = base_query.where(condition)

        if foundation_model_id is not None:
            base_query = base_query.where(
                models.FoundationModelRun.foundation_model_id == foundation_model_id,
            )

        if status is not None:
            base_query = base_query.where(
                models.FoundationModelRun.status == status,
            )

        total = await session.scalar(
            select(func.count()).select_from(base_query.subquery())
        )

        stmt = (
            base_query.options(
                joinedload(models.FoundationModelRun.foundation_model),
                joinedload(models.FoundationModelRun.dataset),
                joinedload(models.FoundationModelRun.requested_by),
            )
            .order_by(models.FoundationModelRun.created_on.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await session.scalars(stmt)
        runs = [
            schemas.FoundationModelRun.model_validate(obj)
            for obj in result.unique().all()
        ]

        return runs, int(total or 0)

    async def get_run(
        self,
        session: AsyncSession,
        uuid: UUID,
    ) -> models.FoundationModelRun:
        stmt = select(models.FoundationModelRun).where(
            models.FoundationModelRun.uuid == uuid,
        )
        run = await session.scalar(stmt)
        if run is None:
            raise exceptions.NotFoundError("Foundation model run not found")
        return run

    async def get_run_with_relations(
        self,
        session: AsyncSession,
        uuid: UUID,
    ) -> schemas.FoundationModelRun:
        stmt = (
            select(models.FoundationModelRun)
            .options(
                joinedload(models.FoundationModelRun.foundation_model),
                joinedload(models.FoundationModelRun.requested_by),
                joinedload(models.FoundationModelRun.dataset).options(
                    joinedload(models.Dataset.project).joinedload(
                        models.Project.memberships
                    ).joinedload(models.ProjectMember.user),
                    joinedload(models.Dataset.primary_site).joinedload(
                        models.Site.images
                    ),
                    joinedload(models.Dataset.primary_recorder),
                    joinedload(models.Dataset.license),
                ),
                joinedload(models.FoundationModelRun.species).joinedload(
                    models.FoundationModelRunSpecies.tag,
                ),
            )
            .where(models.FoundationModelRun.uuid == uuid)
        )
        run = await session.scalar(stmt)
        if run is None:
            raise exceptions.NotFoundError("Foundation model run not found")
        return schemas.FoundationModelRun.model_validate(run)

    async def list_species(
        self,
        session: AsyncSession,
        run: models.FoundationModelRun,
    ) -> list[schemas.FoundationModelRunSpecies]:
        stmt = (
            select(models.FoundationModelRunSpecies)
            .options(joinedload(models.FoundationModelRunSpecies.tag))
            .where(
                models.FoundationModelRunSpecies.foundation_model_run_id == run.id,
            )
            .order_by(
                models.FoundationModelRunSpecies.detection_count.desc(),
                models.FoundationModelRunSpecies.scientific_name.asc(),
            )
        )
        result = await session.scalars(stmt)
        return [
            schemas.FoundationModelRunSpecies.model_validate(obj)
            for obj in result.unique().all()
        ]

    async def enqueue_run(
        self,
        session: AsyncSession,
        dataset_obj: schemas.Dataset,
        model: models.FoundationModel,
        *,
        user: models.User,
        confidence_threshold: float | None = None,
        scope: dict[str, Any] | None = None,
    ) -> schemas.FoundationModelRun:
        if not await can_manage_project(session, dataset_obj.project_id, user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to run foundation models for this dataset",
            )

        threshold = confidence_threshold or model.default_confidence_threshold

        run = models.FoundationModelRun(
            foundation_model_id=model.id,
            dataset_id=dataset_obj.id,
            requested_by_id=user.id,
            confidence_threshold=threshold,
            scope=scope,
        )
        session.add(run)
        await session.flush()

        recording_filters = None
        if scope:
            try:
                recording_filters = schemas.RecordingFilter.model_validate(scope)
            except Exception:
                recording_filters = None

        # Import lazily to avoid circular dependency
        from echoroo.api import species_detection_jobs

        job = await species_detection_jobs.create(
            session,
            schemas.SpeciesDetectionJobCreate(
                name=f"{model.display_name} run for {dataset_obj.name}",
                dataset_uuid=dataset_obj.uuid,
                model_name=model.provider,
                model_version=model.version,
                confidence_threshold=threshold,
                overlap=0.0,
                use_metadata_filter=True,
                recording_filters=recording_filters,
            ),
            user=user,
        )

        run.species_detection_job_id = job.id
        await session.flush()

        run_schema = await self.get_run_with_relations(session, run.uuid)
        return run_schema

    async def cancel_run(
        self,
        session: AsyncSession,
        run: schemas.FoundationModelRun,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.FoundationModelRun:
        """Cancel a foundation model run."""
        db_user = await self._resolve_user(session, user)

        if not await can_edit_foundation_model_run(session, run, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to cancel this run"
            )

        db_run = await self.get_run(session, run.uuid)
        if db_run.status not in (
            models.FoundationModelRunStatus.QUEUED,
            models.FoundationModelRunStatus.RUNNING,
        ):
            raise exceptions.ValidationError(
                f"Cannot cancel run with status {db_run.status.value}"
            )

        db_run.status = models.FoundationModelRunStatus.CANCELLED
        await session.flush()

        return await self.get_run_with_relations(session, run.uuid)

    async def get_dataset(
        self,
        session: AsyncSession,
        dataset_uuid: UUID,
        *,
        user: models.User | None,
    ) -> schemas.Dataset:
        return await datasets.get(session, dataset_uuid, user=user)

    # =========================================================================
    # Progress tracking (from Species Detection API)
    # =========================================================================

    async def get_run_progress(
        self,
        session: AsyncSession,
        run: schemas.FoundationModelRun,
        user: models.User | None = None,
    ) -> schemas.FoundationModelRunProgress:
        """Get detailed progress for a foundation model run."""
        db_user = await self._resolve_user(session, user)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await self.get_run(session, run.uuid)

        # Calculate processing speed
        recordings_per_second = None
        estimated_time_remaining = None

        if db_run.started_on and db_run.processed_recordings > 0:
            elapsed = (datetime.datetime.now(datetime.UTC) - db_run.started_on).total_seconds()
            if elapsed > 0:
                recordings_per_second = db_run.processed_recordings / elapsed
                remaining = db_run.total_recordings - db_run.processed_recordings
                if recordings_per_second > 0:
                    estimated_time_remaining = remaining / recordings_per_second

        # Status message
        status_messages = {
            "queued": "Waiting to start...",
            "running": f"Processing recordings ({db_run.processed_recordings}/{db_run.total_recordings})",
            "post_processing": "Post-processing results...",
            "completed": f"Completed! Found {db_run.total_detections} detections",
            "failed": f"Failed: {db_run.error.get('message', 'Unknown error') if db_run.error else 'Unknown error'}",
            "cancelled": "Cancelled by user",
        }

        return schemas.FoundationModelRunProgress(
            status=db_run.status,
            progress=db_run.progress,
            total_recordings=db_run.total_recordings,
            processed_recordings=db_run.processed_recordings,
            total_clips=db_run.total_clips,
            total_detections=db_run.total_detections,
            recordings_per_second=recordings_per_second,
            estimated_time_remaining_seconds=estimated_time_remaining,
            message=status_messages.get(db_run.status.value, "Unknown status"),
        )

    # =========================================================================
    # Detection results (from Species Detection API)
    # =========================================================================

    async def get_detections(
        self,
        session: AsyncSession,
        run: schemas.FoundationModelRun,
        *,
        limit: int = 100,
        offset: int = 0,
        species_tag_id: int | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        review_status: schemas.DetectionReviewStatus | None = None,
        filter_uuid: UUID | None = None,
        include_excluded: bool = False,
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.DetectionResult], int]:
        """Get detection results for a run.

        Args:
            session: Database session.
            run: Foundation model run schema.
            limit: Maximum number of results to return.
            offset: Number of results to skip.
            species_tag_id: Filter by species tag ID.
            min_confidence: Minimum confidence score.
            max_confidence: Maximum confidence score.
            review_status: Filter by review status.
            filter_uuid: UUID of species filter application to apply.
            include_excluded: If True, include excluded detections (with is_included field).
            user: Current user for permission checks.

        Returns:
            Tuple of (detections list, total count).
        """
        db_user = await self._resolve_user(session, user)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await self.get_run(session, run.uuid)

        # Get the species detection job linked to this run
        if db_run.species_detection_job_id is None:
            return [], 0

        job = await session.get(models.SpeciesDetectionJob, db_run.species_detection_job_id)
        if job is None or job.model_run_id is None:
            return [], 0

        # Get filter application if filter_uuid is provided
        filter_application: models.SpeciesFilterApplication | None = None
        if filter_uuid is not None:
            filter_application = await session.scalar(
                select(models.SpeciesFilterApplication).where(
                    models.SpeciesFilterApplication.uuid == filter_uuid,
                    models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
                )
            )
            if filter_application is None:
                raise exceptions.NotFoundError(
                    f"Species filter application with uuid {filter_uuid} not found for this run"
                )

        # Base query - get ClipPredictions linked to this job's ModelRun
        base_conditions: list[Any] = [
            models.ModelRunPrediction.model_run_id == job.model_run_id,
        ]

        # Build query with joins
        query = (
            select(models.ClipPrediction)
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .options(
                selectinload(models.ClipPrediction.clip).options(
                    selectinload(models.Clip.recording)
                ),
                selectinload(models.ClipPrediction.tags).options(
                    selectinload(models.ClipPredictionTag.tag)
                ),
            )
        )

        # Apply species filter if specified
        if filter_application is not None:
            query = query.outerjoin(
                models.SpeciesFilterMask,
                (models.ClipPrediction.id == models.SpeciesFilterMask.clip_prediction_id)
                & (models.SpeciesFilterMask.species_filter_application_id == filter_application.id),
            )
            # Filter by is_included unless include_excluded is True
            if not include_excluded:
                base_conditions.append(models.SpeciesFilterMask.is_included.is_(True))

        query = query.where(*base_conditions)

        # Apply filters
        if species_tag_id is not None:
            query = query.join(
                models.ClipPredictionTag,
                models.ClipPrediction.id == models.ClipPredictionTag.clip_prediction_id,
            ).where(models.ClipPredictionTag.tag_id == species_tag_id)

        if min_confidence is not None:
            query = query.join(
                models.ClipPredictionTag,
                models.ClipPrediction.id == models.ClipPredictionTag.clip_prediction_id,
                isouter=True,
            ).where(models.ClipPredictionTag.score >= min_confidence)

        if max_confidence is not None:
            if min_confidence is None:
                query = query.join(
                    models.ClipPredictionTag,
                    models.ClipPrediction.id == models.ClipPredictionTag.clip_prediction_id,
                    isouter=True,
                )
            query = query.where(models.ClipPredictionTag.score <= max_confidence)

        # Count query - needs same filter logic
        count_query = (
            select(func.count(models.ClipPrediction.id.distinct()))
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .where(models.ModelRunPrediction.model_run_id == job.model_run_id)
        )

        if filter_application is not None:
            count_query = count_query.outerjoin(
                models.SpeciesFilterMask,
                (models.ClipPrediction.id == models.SpeciesFilterMask.clip_prediction_id)
                & (models.SpeciesFilterMask.species_filter_application_id == filter_application.id),
            )
            if not include_excluded:
                count_query = count_query.where(models.SpeciesFilterMask.is_included.is_(True))

        total_count = await session.scalar(count_query) or 0

        # Execute with pagination
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        clip_predictions = result.scalars().unique().all()

        # Pre-fetch filter mask data for all predictions if filter is applied
        mask_data: dict[int, tuple[bool, float | None]] = {}
        if filter_application is not None:
            cp_ids = [cp.id for cp in clip_predictions]
            if cp_ids:
                mask_query = select(models.SpeciesFilterMask).where(
                    models.SpeciesFilterMask.species_filter_application_id == filter_application.id,
                    models.SpeciesFilterMask.clip_prediction_id.in_(cp_ids),
                )
                mask_result = await session.scalars(mask_query)
                for mask in mask_result.all():
                    mask_data[mask.clip_prediction_id] = (
                        mask.is_included,
                        mask.occurrence_probability,
                    )

        # Build detection results
        detections = []
        for cp in clip_predictions:
            # Get the top tag for this prediction
            top_tag = None
            top_score = 0.0
            for cpt in cp.tags:
                if cpt.score > top_score:
                    top_score = cpt.score
                    top_tag = cpt.tag

            if top_tag is None:
                continue

            # Check for existing review (using species_detection_job_id)
            review = await session.scalar(
                select(models.DetectionReview).where(
                    models.DetectionReview.clip_prediction_id == cp.id,
                    models.DetectionReview.species_detection_job_id == job.id,
                )
            )

            review_status_value = schemas.DetectionReviewStatus.UNREVIEWED
            reviewed_on = None
            reviewed_by_id = None
            notes = None
            converted = False

            if review:
                review_status_value = schemas.DetectionReviewStatus(review.status)
                reviewed_on = review.reviewed_on
                reviewed_by_id = review.reviewed_by_id
                notes = review.notes
                converted = review.converted_to_annotation

            # Get filter mask data if available
            is_included: bool | None = None
            occurrence_probability: float | None = None
            if filter_application is not None:
                if cp.id in mask_data:
                    is_included, occurrence_probability = mask_data[cp.id]
                else:
                    # Detection not in mask - likely not filtered
                    is_included = None

            detections.append(schemas.DetectionResult(
                uuid=cp.uuid,
                id=cp.id,
                clip_id=cp.clip_id,
                clip=schemas.Clip.model_validate(cp.clip),
                species_tag=schemas.Tag.model_validate(top_tag),
                confidence=top_score,
                review_status=review_status_value,
                reviewed_on=reviewed_on,
                reviewed_by_id=reviewed_by_id,
                notes=notes,
                converted_to_annotation=converted,
                is_included=is_included,
                occurrence_probability=occurrence_probability,
            ))

        return detections, total_count

    async def get_detection_summary(
        self,
        session: AsyncSession,
        run: schemas.FoundationModelRun,
        user: models.User | None = None,
    ) -> schemas.DetectionSummary:
        """Get summary statistics for detection results."""
        db_user = await self._resolve_user(session, user)

        if not await can_view_foundation_model_run(session, run, db_user):
            raise exceptions.NotFoundError("Foundation model run not found")

        db_run = await self.get_run(session, run.uuid)

        # Get the species detection job linked to this run
        if db_run.species_detection_job_id is None:
            return schemas.DetectionSummary()

        job = await session.get(models.SpeciesDetectionJob, db_run.species_detection_job_id)
        if job is None or job.model_run_id is None:
            return schemas.DetectionSummary()

        # Get total detections
        total_query = (
            select(func.count(models.ClipPrediction.id))
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .where(models.ModelRunPrediction.model_run_id == job.model_run_id)
        )
        total_detections = await session.scalar(total_query) or 0

        # Get species summary
        species_query = (
            select(
                models.Tag.id,
                models.Tag.value,
                func.count(models.ClipPredictionTag.clip_prediction_id),
                func.avg(models.ClipPredictionTag.score),
            )
            .join(
                models.ClipPredictionTag,
                models.Tag.id == models.ClipPredictionTag.tag_id,
            )
            .join(
                models.ClipPrediction,
                models.ClipPredictionTag.clip_prediction_id == models.ClipPrediction.id,
            )
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .where(models.ModelRunPrediction.model_run_id == job.model_run_id)
            .group_by(models.Tag.id, models.Tag.value)
            .order_by(func.count(models.ClipPredictionTag.clip_prediction_id).desc())
        )
        species_results = await session.execute(species_query)

        species_summary = []
        for row in species_results.all():
            species_summary.append(schemas.SpeciesSummary(
                tag_id=row[0],
                tag_value=row[1],
                total_detections=row[2],
                average_confidence=float(row[3]) if row[3] else None,
            ))

        # Get review counts
        review_counts_query = (
            select(
                models.DetectionReview.status,
                func.count(models.DetectionReview.id),
            )
            .where(models.DetectionReview.species_detection_job_id == job.id)
            .group_by(models.DetectionReview.status)
        )
        review_results = await session.execute(review_counts_query)

        total_reviewed = 0
        total_confirmed = 0
        total_rejected = 0
        total_uncertain = 0

        for row in review_results.all():
            status, count = row
            if status == "confirmed":
                total_confirmed = count
                total_reviewed += count
            elif status == "rejected":
                total_rejected = count
                total_reviewed += count
            elif status == "uncertain":
                total_uncertain = count
                total_reviewed += count

        total_unreviewed = total_detections - total_reviewed

        return schemas.DetectionSummary(
            total_detections=total_detections,
            unique_species=len(species_summary),
            species_summary=species_summary,
            total_reviewed=total_reviewed,
            total_confirmed=total_confirmed,
            total_rejected=total_rejected,
            total_uncertain=total_uncertain,
            total_unreviewed=total_unreviewed,
        )

    # =========================================================================
    # Review operations (from Species Detection API)
    # =========================================================================

    async def review_detection(
        self,
        session: AsyncSession,
        run: schemas.FoundationModelRun,
        clip_prediction_uuid: UUID,
        data: schemas.DetectionReviewUpdate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.DetectionReview:
        """Review a detection result."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError("Authentication required")

        if not await can_edit_foundation_model_run(session, run, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to review detections for this run"
            )

        db_run = await self.get_run(session, run.uuid)

        # Get the species detection job linked to this run
        if db_run.species_detection_job_id is None:
            raise exceptions.ValidationError("Run has no associated detection job")

        job = await session.get(models.SpeciesDetectionJob, db_run.species_detection_job_id)
        if job is None:
            raise exceptions.ValidationError("Detection job not found")

        # Get the clip prediction
        clip_prediction = await session.scalar(
            select(models.ClipPrediction).where(
                models.ClipPrediction.uuid == clip_prediction_uuid
            )
        )
        if clip_prediction is None:
            raise exceptions.NotFoundError(
                f"Clip prediction with uuid {clip_prediction_uuid} not found"
            )

        # Check if review exists
        review = await session.scalar(
            select(models.DetectionReview).where(
                models.DetectionReview.clip_prediction_id == clip_prediction.id,
                models.DetectionReview.species_detection_job_id == job.id,
            )
        )

        now = datetime.datetime.now(datetime.UTC)

        if review:
            # Update existing review
            review.status = data.status.value
            review.reviewed_by_id = db_user.id
            review.reviewed_on = now
            if data.notes is not None:
                review.notes = data.notes
            await session.flush()
        else:
            # Create new review
            review = await common.create_object(
                session,
                models.DetectionReview,
                clip_prediction_id=clip_prediction.id,
                species_detection_job_id=job.id,
                status=data.status.value,
                reviewed_by_id=db_user.id,
                reviewed_on=now,
                notes=data.notes,
            )

        return schemas.DetectionReview(
            uuid=review.uuid,
            id=review.id,
            clip_prediction_id=review.clip_prediction_id,
            species_detection_job_id=review.species_detection_job_id,
            status=schemas.DetectionReviewStatus(review.status),
            reviewed_by_id=review.reviewed_by_id,
            reviewed_on=review.reviewed_on,
            notes=review.notes,
            converted_to_annotation=review.converted_to_annotation,
            clip_annotation_id=review.clip_annotation_id,
        )

    async def bulk_review_detections(
        self,
        session: AsyncSession,
        run: schemas.FoundationModelRun,
        clip_prediction_uuids: list[UUID],
        data: schemas.DetectionReviewUpdate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> int:
        """Bulk review multiple detection results. Returns count of reviewed items."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError("Authentication required")

        if not await can_edit_foundation_model_run(session, run, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to review detections for this run"
            )

        db_run = await self.get_run(session, run.uuid)

        # Get the species detection job linked to this run
        if db_run.species_detection_job_id is None:
            raise exceptions.ValidationError("Run has no associated detection job")

        job = await session.get(models.SpeciesDetectionJob, db_run.species_detection_job_id)
        if job is None:
            raise exceptions.ValidationError("Detection job not found")

        count = 0
        now = datetime.datetime.now(datetime.UTC)

        for cp_uuid in clip_prediction_uuids:
            clip_prediction = await session.scalar(
                select(models.ClipPrediction).where(
                    models.ClipPrediction.uuid == cp_uuid
                )
            )
            if clip_prediction is None:
                continue

            review = await session.scalar(
                select(models.DetectionReview).where(
                    models.DetectionReview.clip_prediction_id == clip_prediction.id,
                    models.DetectionReview.species_detection_job_id == job.id,
                )
            )

            if review:
                review.status = data.status.value
                review.reviewed_by_id = db_user.id
                review.reviewed_on = now
                if data.notes is not None:
                    review.notes = data.notes
            else:
                await common.create_object(
                    session,
                    models.DetectionReview,
                    clip_prediction_id=clip_prediction.id,
                    species_detection_job_id=job.id,
                    status=data.status.value,
                    reviewed_by_id=db_user.id,
                    reviewed_on=now,
                    notes=data.notes,
                )
            count += 1

        await session.flush()
        return count


foundation_models = FoundationModelAPI()
