"""Python API for Inference Batches."""

import logging
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI, UserResolutionMixin
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.filters.base import Filter

__all__ = [
    "InferenceBatchAPI",
    "inference_batches",
]

logger = logging.getLogger(__name__)


class InferenceBatchAPI(
    BaseAPI[
        UUID,
        models.InferenceBatch,
        schemas.InferenceBatch,
        schemas.InferenceBatchCreate,
        schemas.InferenceBatch,
    ],
    UserResolutionMixin,
):
    """API for managing Inference Batches."""

    _model = models.InferenceBatch
    _schema = schemas.InferenceBatch

    async def _get_ml_project(
        self,
        session: AsyncSession,
        ml_project_id: int,
    ) -> models.MLProject:
        """Get ML project by ID."""
        ml_project = await session.get(models.MLProject, ml_project_id)
        if ml_project is None:
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )
        return ml_project

    async def _eager_load_relationships(
        self,
        session: AsyncSession,
        db_obj: models.InferenceBatch,
    ) -> models.InferenceBatch:
        """Eagerly load relationships needed for schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.ml_project),
                selectinload(self._model.custom_model),
                selectinload(self._model.created_by),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.InferenceBatch,
    ) -> schemas.InferenceBatch:
        """Build schema from database object."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Map status enum
        status_map = {
            models.InferenceBatchStatus.PENDING: schemas.InferenceBatchStatus.PENDING,
            models.InferenceBatchStatus.PREPARING: schemas.InferenceBatchStatus.PREPARING,
            models.InferenceBatchStatus.RUNNING: schemas.InferenceBatchStatus.RUNNING,
            models.InferenceBatchStatus.COMPLETED: schemas.InferenceBatchStatus.COMPLETED,
            models.InferenceBatchStatus.FAILED: schemas.InferenceBatchStatus.FAILED,
            models.InferenceBatchStatus.CANCELLED: schemas.InferenceBatchStatus.CANCELLED,
        }
        status = status_map.get(db_obj.status, schemas.InferenceBatchStatus.PENDING)

        # Get prediction counts
        total_predictions = await session.scalar(
            select(func.count(models.InferencePrediction.id)).where(
                models.InferencePrediction.inference_batch_id == db_obj.id
            )
        )

        reviewed_count = await session.scalar(
            select(func.count(models.InferencePrediction.id))
            .where(models.InferencePrediction.inference_batch_id == db_obj.id)
            .where(
                models.InferencePrediction.review_status
                != models.InferencePredictionReviewStatus.UNREVIEWED
            )
        )

        confirmed_count = await session.scalar(
            select(func.count(models.InferencePrediction.id))
            .where(models.InferencePrediction.inference_batch_id == db_obj.id)
            .where(
                models.InferencePrediction.review_status
                == models.InferencePredictionReviewStatus.CONFIRMED
            )
        )

        rejected_count = await session.scalar(
            select(func.count(models.InferencePrediction.id))
            .where(models.InferencePrediction.inference_batch_id == db_obj.id)
            .where(
                models.InferencePrediction.review_status
                == models.InferencePredictionReviewStatus.REJECTED
            )
        )

        uncertain_count = await session.scalar(
            select(func.count(models.InferencePrediction.id))
            .where(models.InferencePrediction.inference_batch_id == db_obj.id)
            .where(
                models.InferencePrediction.review_status
                == models.InferencePredictionReviewStatus.UNCERTAIN
            )
        )

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "custom_model_id": db_obj.custom_model_id,
            "custom_model": None,  # Would require building CustomModel schema
            "status": status,
            "confidence_threshold": db_obj.confidence_threshold,
            "total_clips": getattr(db_obj, "total_clips", 0),
            "processed_clips": getattr(db_obj, "processed_clips", 0),
            "total_predictions": total_predictions or 0,
            "reviewed_count": reviewed_count or 0,
            "confirmed_count": confirmed_count or 0,
            "rejected_count": rejected_count or 0,
            "uncertain_count": uncertain_count or 0,
            "started_at": getattr(db_obj, "started_at", None),
            "completed_at": getattr(db_obj, "completed_at", None),
            "duration_seconds": getattr(db_obj, "duration_seconds", None),
            "error_message": getattr(db_obj, "error_message", None),
            "notes": getattr(db_obj, "notes", None),
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
        }

        return schemas.InferenceBatch.model_validate(data)

    async def _build_prediction_schema(
        self,
        session: AsyncSession,
        db_obj: models.InferencePrediction,
    ) -> schemas.InferencePrediction:
        """Build prediction schema from database object."""
        # Load relationships
        stmt = (
            select(models.InferencePrediction)
            .where(models.InferencePrediction.uuid == db_obj.uuid)
            .options(
                selectinload(models.InferencePrediction.clip),
                selectinload(models.InferencePrediction.tag),
                selectinload(models.InferencePrediction.inference_batch),
            )
        )
        result = await session.execute(stmt)
        db_obj = result.scalar_one()

        # Map review status
        review_status_map = {
            models.InferencePredictionReviewStatus.UNREVIEWED: schemas.InferencePredictionReviewStatus.UNREVIEWED,
            models.InferencePredictionReviewStatus.CONFIRMED: schemas.InferencePredictionReviewStatus.CONFIRMED,
            models.InferencePredictionReviewStatus.REJECTED: schemas.InferencePredictionReviewStatus.REJECTED,
            models.InferencePredictionReviewStatus.UNCERTAIN: schemas.InferencePredictionReviewStatus.UNCERTAIN,
        }

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "inference_batch_id": db_obj.inference_batch_id,
            "inference_batch_uuid": (
                db_obj.inference_batch.uuid if db_obj.inference_batch else None
            ),
            "clip_id": db_obj.clip_id,
            "clip": (
                schemas.Clip.model_validate(db_obj.clip) if db_obj.clip else None
            ),
            "tag_id": db_obj.tag_id,
            "tag": schemas.Tag.model_validate(db_obj.tag) if db_obj.tag else None,
            "confidence": db_obj.confidence,
            "rank": getattr(db_obj, "rank", 1),
            "review_status": review_status_map.get(
                db_obj.review_status,
                schemas.InferencePredictionReviewStatus.UNREVIEWED,
            ),
            "reviewed_at": getattr(db_obj, "reviewed_at", None),
            "reviewed_by_id": getattr(db_obj, "reviewed_by_id", None),
            "notes": getattr(db_obj, "notes", None),
            "created_on": db_obj.created_on,
        }

        return schemas.InferencePrediction.model_validate(data)

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.InferenceBatch:
        """Get an inference batch by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {pk} not found"
            )

        return await self._build_schema(session, db_obj)

    async def get_many(
        self,
        session: AsyncSession,
        ml_project: schemas.MLProject,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.InferenceBatch], int]:
        """Get inference batches for an ML project."""
        db_user = await self._resolve_user(session, user)

        db_ml_project = await self._get_ml_project(session, ml_project.id)
        if not await can_view_ml_project(session, db_ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project.id} not found"
            )

        combined_filters: list[Filter | ColumnExpressionArgument] = [
            self._model.ml_project_id == ml_project.id
        ]
        if filters:
            combined_filters.extend(filters)

        db_objs, count = await common.get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters,
            sort_by=sort_by,
        )

        results = []
        for db_obj in db_objs:
            schema_obj = await self._build_schema(session, db_obj)
            results.append(schema_obj)

        return results, count

    async def create(
        self,
        session: AsyncSession,
        ml_project: schemas.MLProject,
        *,
        name: str | None = None,
        custom_model_id: int,
        confidence_threshold: float = 0.5,
        clip_ids: list[int] | None = None,
        include_all_clips: bool = False,
        exclude_already_labeled: bool = True,
        notes: str | None = None,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.InferenceBatch:
        """Create a new inference batch."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create inference batches"
            )

        db_ml_project = await self._get_ml_project(session, ml_project.id)
        if not await can_edit_ml_project(session, db_ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to create inference batches in this ML project"
            )

        # Validate custom model exists and belongs to this project
        custom_model = await session.get(models.CustomModel, custom_model_id)
        if custom_model is None:
            raise exceptions.NotFoundError(
                f"Custom model with id {custom_model_id} not found"
            )
        if custom_model.ml_project_id != ml_project.id:
            raise exceptions.InvalidDataError(
                f"Custom model {custom_model_id} does not belong to this ML project"
            )

        # Validate custom model is trained
        if custom_model.status != models.CustomModelStatus.COMPLETED:
            raise exceptions.InvalidDataError(
                f"Custom model {custom_model_id} has not completed training"
            )

        db_obj = await common.create_object(
            session,
            self._model,
            name=name,
            ml_project_id=ml_project.id,
            custom_model_id=custom_model_id,
            confidence_threshold=confidence_threshold,
            status=models.InferenceBatchStatus.PENDING,
            notes=notes,
            created_by_id=db_user.id,
        )

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.InferenceBatch,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.InferenceBatch:
        """Delete an inference batch."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this inference batch"
            )

        result = await self._build_schema(session, db_obj)

        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def start(
        self,
        session: AsyncSession,
        obj: schemas.InferenceBatch,
        ml_project: schemas.MLProject,
        *,
        audio_dir: str | None = None,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.InferenceBatch:
        """Start running inference for a batch.

        This is a placeholder that would integrate with the ML pipeline
        to run inference using the trained model.
        """
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        db_ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, db_ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to start inference for this batch"
            )

        if db_obj.status not in [
            models.InferenceBatchStatus.PENDING,
            models.InferenceBatchStatus.FAILED,
            models.InferenceBatchStatus.CANCELLED,
        ]:
            raise exceptions.InvalidDataError(
                f"Cannot start inference for batch in status {db_obj.status.value}"
            )

        # Update status to preparing
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
            {
                "status": models.InferenceBatchStatus.PREPARING,
                "started_at": datetime.now(timezone.utc),
            },
        )

        # TODO: Implement actual inference
        # This would:
        # 1. Load the trained model
        # 2. Get clips to process
        # 3. Run inference on each clip
        # 4. Create InferencePrediction records for clips above threshold
        # 5. Update batch status to completed

        logger.info(
            f"Inference requested for batch {obj.uuid}. "
            "This feature requires ML pipeline integration."
        )

        return await self._build_schema(session, db_obj)

    async def get_predictions(
        self,
        session: AsyncSession,
        obj: schemas.InferenceBatch,
        *,
        limit: int | None = 100,
        offset: int | None = 0,
        review_status: schemas.InferencePredictionReviewStatus | None = None,
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.InferencePrediction], int]:
        """Get predictions for an inference batch."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {obj.uuid} not found"
            )

        # Build filters
        filters: list[ColumnExpressionArgument] = [
            models.InferencePrediction.inference_batch_id == db_obj.id
        ]

        if review_status is not None:
            status_map = {
                schemas.InferencePredictionReviewStatus.UNREVIEWED: models.InferencePredictionReviewStatus.UNREVIEWED,
                schemas.InferencePredictionReviewStatus.CONFIRMED: models.InferencePredictionReviewStatus.CONFIRMED,
                schemas.InferencePredictionReviewStatus.REJECTED: models.InferencePredictionReviewStatus.REJECTED,
                schemas.InferencePredictionReviewStatus.UNCERTAIN: models.InferencePredictionReviewStatus.UNCERTAIN,
            }
            filters.append(
                models.InferencePrediction.review_status == status_map[review_status]
            )

        db_predictions, count = await common.get_objects(
            session,
            models.InferencePrediction,
            limit=limit,
            offset=offset,
            filters=filters,
            sort_by="-confidence",
        )

        results = []
        for db_pred in db_predictions:
            schema_obj = await self._build_prediction_schema(session, db_pred)
            results.append(schema_obj)

        return results, count

    async def get_prediction(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.InferencePrediction:
        """Get a specific prediction by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            models.InferencePrediction,
            models.InferencePrediction.uuid == pk,
        )

        # Check access via batch -> ml project
        batch = await session.get(models.InferenceBatch, db_obj.inference_batch_id)
        if batch is None:
            raise exceptions.NotFoundError(
                f"Inference prediction with uuid {pk} not found"
            )

        ml_project = await self._get_ml_project(session, batch.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Inference prediction with uuid {pk} not found"
            )

        return await self._build_prediction_schema(session, db_obj)

    async def review_prediction(
        self,
        session: AsyncSession,
        prediction: schemas.InferencePrediction,
        *,
        review_status: schemas.InferencePredictionReviewStatus,
        notes: str | None = None,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.InferencePrediction:
        """Review an inference prediction."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to review predictions"
            )

        db_obj = await common.get_object(
            session,
            models.InferencePrediction,
            models.InferencePrediction.uuid == prediction.uuid,
        )

        batch = await session.get(models.InferenceBatch, db_obj.inference_batch_id)
        if batch is None:
            raise exceptions.NotFoundError(
                f"Inference prediction with uuid {prediction.uuid} not found"
            )

        ml_project = await self._get_ml_project(session, batch.ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to review predictions in this batch"
            )

        status_map = {
            schemas.InferencePredictionReviewStatus.UNREVIEWED: models.InferencePredictionReviewStatus.UNREVIEWED,
            schemas.InferencePredictionReviewStatus.CONFIRMED: models.InferencePredictionReviewStatus.CONFIRMED,
            schemas.InferencePredictionReviewStatus.REJECTED: models.InferencePredictionReviewStatus.REJECTED,
            schemas.InferencePredictionReviewStatus.UNCERTAIN: models.InferencePredictionReviewStatus.UNCERTAIN,
        }

        update_data = {
            "review_status": status_map[review_status],
            "reviewed_at": datetime.now(timezone.utc),
            "reviewed_by_id": db_user.id,
        }
        if notes is not None:
            update_data["notes"] = notes

        db_obj = await common.update_object(
            session,
            models.InferencePrediction,
            models.InferencePrediction.uuid == prediction.uuid,
            update_data,
        )

        return await self._build_prediction_schema(session, db_obj)


inference_batches = InferenceBatchAPI()
