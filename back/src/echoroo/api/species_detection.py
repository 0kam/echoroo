"""Python API for Species Detection Jobs.

NOTE: This module is still used internally by the Foundation Models API.
The SpeciesDetectionJobAPI class handles the low-level job management,
while the Foundation Models API provides the unified external interface.

The routes for this API have been deprecated - all detection/review
functionality is now accessed through the Foundation Models API at:

- GET /api/v1/foundation_models/runs/{run_uuid}/progress
- GET /api/v1/foundation_models/runs/{run_uuid}/detections
- GET /api/v1/foundation_models/runs/{run_uuid}/detections/summary
- POST /api/v1/foundation_models/runs/{run_uuid}/detections/{clip_prediction_uuid}/review
- POST /api/v1/foundation_models/runs/{run_uuid}/detections/bulk-review
"""

import datetime
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement, ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.common.permissions import can_manage_project
from echoroo.filters.base import Filter

__all__ = [
    "SpeciesDetectionJobAPI",
    "species_detection_jobs",
]


async def _get_dataset_project_id(
    session: AsyncSession,
    dataset_id: int,
) -> str | None:
    """Get the project_id for a dataset."""
    dataset = await session.get(models.Dataset, dataset_id)
    return dataset.project_id if dataset else None


async def can_view_species_detection_job(
    session: AsyncSession,
    job: models.SpeciesDetectionJob | schemas.SpeciesDetectionJob,
    user: models.User | None,
) -> bool:
    """Return True if the user can view the species detection job."""
    if user is None:
        return False
    if user.is_superuser:
        return True

    # Creator can always view
    if hasattr(job, "created_by_id") and job.created_by_id == user.id:
        return True

    # Check project membership via dataset
    project_id = await _get_dataset_project_id(session, job.dataset_id)
    if project_id:
        membership = await session.scalar(
            select(models.ProjectMember).where(
                models.ProjectMember.project_id == project_id,
                models.ProjectMember.user_id == user.id,
            )
        )
        return membership is not None

    return False


async def can_edit_species_detection_job(
    session: AsyncSession,
    job: models.SpeciesDetectionJob | schemas.SpeciesDetectionJob,
    user: models.User | None,
) -> bool:
    """Return True if the user can edit the species detection job."""
    if user is None:
        return False
    if user.is_superuser:
        return True
    if hasattr(job, "created_by_id") and job.created_by_id == user.id:
        return True

    project_id = await _get_dataset_project_id(session, job.dataset_id)
    if project_id:
        return await can_manage_project(session, project_id, user)
    return False


async def filter_jobs_by_access(
    session: AsyncSession,
    user: models.User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting jobs accessible to the user."""
    if user is None:
        return [models.SpeciesDetectionJob.id == -1]
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
        models.SpeciesDetectionJob.created_by_id == user.id,
    ]
    if accessible_dataset_ids:
        conditions.append(models.SpeciesDetectionJob.dataset_id.in_(accessible_dataset_ids))

    return [or_(*conditions)]


class SpeciesDetectionJobAPI(
    BaseAPI[
        UUID,
        models.SpeciesDetectionJob,
        schemas.SpeciesDetectionJob,
        schemas.SpeciesDetectionJobCreate,
        schemas.SpeciesDetectionJobUpdate,
    ]
):
    """API for managing Species Detection Jobs."""

    _model = models.SpeciesDetectionJob
    _schema = schemas.SpeciesDetectionJob

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

    async def _eager_load_relationships(
        self,
        session: AsyncSession,
        db_obj: models.SpeciesDetectionJob,
    ) -> models.SpeciesDetectionJob:
        """Eagerly load relationships."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.dataset).options(
                    selectinload(models.Dataset.project).options(
                        selectinload(models.Project.memberships)
                    ),
                    selectinload(models.Dataset.primary_site).options(
                        selectinload(models.Site.images)
                    ),
                    selectinload(models.Dataset.primary_recorder),
                    selectinload(models.Dataset.license),
                ),
                selectinload(self._model.model_run),
                selectinload(self._model.created_by),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.SpeciesDetectionJob,
    ) -> schemas.SpeciesDetectionJob:
        """Build schema from database object."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Map model status (string) to schema status (enum)
        schema_status = schemas.SpeciesDetectionJobStatus(db_obj.status)

        return schemas.SpeciesDetectionJob(
            uuid=db_obj.uuid,
            id=db_obj.id,
            name=db_obj.name,
            dataset_id=db_obj.dataset_id,
            dataset=schemas.Dataset.model_validate(db_obj.dataset) if db_obj.dataset else None,
            created_by_id=db_obj.created_by_id,
            model_name=db_obj.model_name,
            model_version=db_obj.model_version,
            confidence_threshold=db_obj.confidence_threshold,
            overlap=db_obj.overlap,
            use_metadata_filter=db_obj.use_metadata_filter,
            custom_species_list=db_obj.custom_species_list,
            recording_filters=db_obj.recording_filters,
            status=schema_status,
            progress=db_obj.progress,
            total_recordings=db_obj.total_recordings,
            processed_recordings=db_obj.processed_recordings,
            total_clips=db_obj.total_clips,
            total_detections=db_obj.total_detections,
            error_message=db_obj.error_message,
            started_on=db_obj.started_on,
            completed_on=db_obj.completed_on,
            model_run_id=db_obj.model_run_id,
            model_run=schemas.ModelRun.model_validate(db_obj.model_run) if db_obj.model_run else None,
        )

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.SpeciesDetectionJob:
        """Get a species detection job by UUID."""
        db_user = await self._resolve_user(session, user)
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        if not await can_view_species_detection_job(session, db_obj, db_user):
            raise exceptions.NotFoundError(f"Species detection job with uuid {pk} not found")

        return await self._build_schema(session, db_obj)

    async def get_many(
        self,
        session: AsyncSession,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.SpeciesDetectionJob], int]:
        """Get multiple species detection jobs."""
        db_user = await self._resolve_user(session, user)
        access_filters = await filter_jobs_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        db_objs, count = await common.get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters or None,
            sort_by=sort_by,
        )

        jobs = []
        for db_obj in db_objs:
            schema_obj = await self._build_schema(session, db_obj)
            jobs.append(schema_obj)

        return jobs, count

    async def create(
        self,
        session: AsyncSession,
        data: schemas.SpeciesDetectionJobCreate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.SpeciesDetectionJob:
        """Create a new species detection job."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create species detection jobs"
            )

        # Get dataset by UUID
        dataset = await session.scalar(
            select(models.Dataset).where(models.Dataset.uuid == data.dataset_uuid)
        )
        if dataset is None:
            raise exceptions.NotFoundError(f"Dataset with uuid {data.dataset_uuid} not found")

        # Check permission
        if not await can_manage_project(session, dataset.project_id, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to create species detection jobs for this dataset"
            )

        # Validate model name
        if data.model_name.lower() not in ("birdnet", "perch"):
            raise exceptions.ValidationError(
                f"Invalid model name: {data.model_name}. Must be 'birdnet' or 'perch'"
            )

        # Create job
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            dataset_id=dataset.id,
            created_by_id=db_user.id,
            model_name=data.model_name.lower(),
            model_version=data.model_version,
            confidence_threshold=data.confidence_threshold,
            overlap=data.overlap,
            use_metadata_filter=data.use_metadata_filter,
            custom_species_list=data.custom_species_list,
            recording_filters=data.recording_filters.model_dump() if data.recording_filters else None,
            locale=data.locale,
        )

        return await self._build_schema(session, db_obj)

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.SpeciesDetectionJob,
        data: schemas.SpeciesDetectionJobUpdate,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SpeciesDetectionJob:
        """Update a species detection job."""
        db_user = await self._resolve_user(session, user)

        if not await can_edit_species_detection_job(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to update this species detection job"
            )

        update_data: dict[str, Any] = {}
        if data.name is not None:
            update_data["name"] = data.name
        if data.status is not None:
            # Only allow cancellation from update
            if data.status == schemas.SpeciesDetectionJobStatus.CANCELLED:
                update_data["status"] = "cancelled"

        if update_data:
            db_obj = await common.update_object(
                session,
                self._model,
                self._get_pk_condition(obj.uuid),
                update_data,
            )
        else:
            db_obj = await common.get_object(
                session,
                self._model,
                self._get_pk_condition(obj.uuid),
            )

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.SpeciesDetectionJob,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SpeciesDetectionJob:
        """Delete a species detection job."""
        db_user = await self._resolve_user(session, user)

        if not await can_edit_species_detection_job(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this species detection job"
            )

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        result = await self._build_schema(session, db_obj)

        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def get_progress(
        self,
        session: AsyncSession,
        obj: schemas.SpeciesDetectionJob,
        user: models.User | None = None,
    ) -> schemas.SpeciesDetectionJobProgress:
        """Get progress for a species detection job."""
        db_user = await self._resolve_user(session, user)

        if not await can_view_species_detection_job(session, obj, db_user):
            raise exceptions.NotFoundError(f"Species detection job with uuid {obj.uuid} not found")

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        # Calculate processing speed
        recordings_per_second = None
        estimated_time_remaining = None

        if db_obj.started_on and db_obj.processed_recordings > 0:
            elapsed = (datetime.datetime.now(datetime.UTC) - db_obj.started_on).total_seconds()
            if elapsed > 0:
                recordings_per_second = db_obj.processed_recordings / elapsed
                remaining = db_obj.total_recordings - db_obj.processed_recordings
                if recordings_per_second > 0:
                    estimated_time_remaining = remaining / recordings_per_second

        # Status message
        status_messages = {
            "pending": "Waiting to start...",
            "running": f"Processing recordings ({db_obj.processed_recordings}/{db_obj.total_recordings})",
            "completed": f"Completed! Found {db_obj.total_detections} detections",
            "failed": f"Failed: {db_obj.error_message or 'Unknown error'}",
            "cancelled": "Cancelled by user",
        }

        return schemas.SpeciesDetectionJobProgress(
            status=schemas.SpeciesDetectionJobStatus(db_obj.status),
            progress=db_obj.progress,
            total_recordings=db_obj.total_recordings,
            processed_recordings=db_obj.processed_recordings,
            total_clips=db_obj.total_clips,
            total_detections=db_obj.total_detections,
            recordings_per_second=recordings_per_second,
            estimated_time_remaining_seconds=estimated_time_remaining,
            message=status_messages.get(db_obj.status, "Unknown status"),
        )

    async def get_detections(
        self,
        session: AsyncSession,
        obj: schemas.SpeciesDetectionJob,
        *,
        limit: int = 100,
        offset: int = 0,
        species_tag_id: int | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        review_status: schemas.DetectionReviewStatus | None = None,
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.DetectionResult], int]:
        """Get detection results for a job."""
        db_user = await self._resolve_user(session, user)

        if not await can_view_species_detection_job(session, obj, db_user):
            raise exceptions.NotFoundError(f"Species detection job with uuid {obj.uuid} not found")

        if obj.model_run_id is None:
            return [], 0

        # Base query - get ClipPredictions linked to this job's ModelRun
        base_conditions = [
            models.ModelRunPrediction.model_run_id == obj.model_run_id,
        ]

        # Build query with joins
        query = (
            select(models.ClipPrediction)
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .where(*base_conditions)
            .options(
                selectinload(models.ClipPrediction.clip).options(
                    selectinload(models.Clip.recording)
                ),
                selectinload(models.ClipPrediction.tags).options(
                    selectinload(models.ClipPredictionTag.tag)
                ),
            )
        )

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

        # Count query
        count_query = (
            select(func.count(models.ClipPrediction.id))
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .where(*base_conditions)
        )
        total_count = await session.scalar(count_query) or 0

        # Execute with pagination
        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        clip_predictions = result.scalars().unique().all()

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

            # Check for existing review
            review = await session.scalar(
                select(models.DetectionReview).where(
                    models.DetectionReview.clip_prediction_id == cp.id,
                    models.DetectionReview.species_detection_job_id == obj.id,
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
            ))

        return detections, total_count

    async def get_detection_summary(
        self,
        session: AsyncSession,
        obj: schemas.SpeciesDetectionJob,
        user: models.User | None = None,
    ) -> schemas.DetectionSummary:
        """Get summary statistics for detection results."""
        db_user = await self._resolve_user(session, user)

        if not await can_view_species_detection_job(session, obj, db_user):
            raise exceptions.NotFoundError(f"Species detection job with uuid {obj.uuid} not found")

        if obj.model_run_id is None:
            return schemas.DetectionSummary()

        # Get total detections
        total_query = (
            select(func.count(models.ClipPrediction.id))
            .join(
                models.ModelRunPrediction,
                models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
            )
            .where(models.ModelRunPrediction.model_run_id == obj.model_run_id)
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
            .where(models.ModelRunPrediction.model_run_id == obj.model_run_id)
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
            .where(models.DetectionReview.species_detection_job_id == obj.id)
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

    async def review_detection(
        self,
        session: AsyncSession,
        obj: schemas.SpeciesDetectionJob,
        clip_prediction_uuid: UUID,
        data: schemas.DetectionReviewUpdate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.DetectionReview:
        """Review a detection result."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError("Authentication required")

        if not await can_edit_species_detection_job(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to review detections for this job"
            )

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
                models.DetectionReview.species_detection_job_id == obj.id,
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
                species_detection_job_id=obj.id,
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
        obj: schemas.SpeciesDetectionJob,
        clip_prediction_uuids: list[UUID],
        data: schemas.DetectionReviewUpdate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> int:
        """Bulk review multiple detection results. Returns count of reviewed items."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError("Authentication required")

        if not await can_edit_species_detection_job(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to review detections for this job"
            )

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
                    models.DetectionReview.species_detection_job_id == obj.id,
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
                    species_detection_job_id=obj.id,
                    status=data.status.value,
                    reviewed_by_id=db_user.id,
                    reviewed_on=now,
                    notes=data.notes,
                )
            count += 1

        await session.flush()
        return count


species_detection_jobs = SpeciesDetectionJobAPI()
