"""Python API for Standalone Inference Batches.

This module provides APIs for inference batches that operate independently
of the ML Project workflow. It supports multiple dataset scopes for running
inference across datasets.
"""

import datetime
import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement, ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.common.permissions import can_manage_project
from echoroo.filters.base import Filter

__all__ = [
    "InferenceBatchStandaloneAPI",
    "inference_batches_standalone",
]

logger = logging.getLogger(__name__)


async def _get_project_membership(
    session: AsyncSession,
    project_id: str,
    user: models.User | None,
) -> models.ProjectMember | None:
    """Get user's membership in a project."""
    if user is None:
        return None

    return await session.scalar(
        select(models.ProjectMember).where(
            models.ProjectMember.project_id == project_id,
            models.ProjectMember.user_id == user.id,
        )
    )


async def can_view_inference_batch(
    session: AsyncSession,
    batch: models.InferenceBatch,
    user: models.User | None,
) -> bool:
    """Return True if the user can view the inference batch."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    # Check if user is the creator
    if batch.created_by_id == user.id:
        return True

    # Check project membership
    if batch.project_id:
        membership = await _get_project_membership(session, batch.project_id, user)
        return membership is not None

    return False


async def can_edit_inference_batch(
    session: AsyncSession,
    batch: models.InferenceBatch,
    user: models.User | None,
) -> bool:
    """Return True if the user can edit the inference batch."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    # Check if user is the creator
    if batch.created_by_id == user.id:
        return True

    # Check project manager role
    if batch.project_id:
        return await can_manage_project(session, batch.project_id, user)

    return False


async def filter_inference_batches_by_access(
    session: AsyncSession,
    user: models.User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting inference batches accessible to the user."""
    if user is None:
        return [models.InferenceBatch.id == -1]  # No access for anonymous users

    if user.is_superuser:
        return []

    # Get project IDs user has membership in
    project_ids = (
        await session.scalars(
            select(models.ProjectMember.project_id).where(
                models.ProjectMember.user_id == user.id
            )
        )
    ).all()

    conditions: list[ColumnElement[bool]] = [
        models.InferenceBatch.created_by_id == user.id,
    ]

    if project_ids:
        conditions.append(models.InferenceBatch.project_id.in_(project_ids))

    return [or_(*conditions)]


class InferenceBatchStandaloneAPI(
    BaseAPI[
        UUID,
        models.InferenceBatch,
        schemas.InferenceBatch,
        schemas.InferenceBatchCreate,
        schemas.InferenceBatch,
    ]
):
    """API for managing Standalone Inference Batches."""

    _model = models.InferenceBatch
    _schema = schemas.InferenceBatch

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
        db_obj: models.InferenceBatch,
    ) -> models.InferenceBatch:
        """Eagerly load relationships needed for schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.custom_model),
                selectinload(self._model.created_by),
                selectinload(self._model.dataset_scopes).options(
                    selectinload(models.InferenceBatchDatasetScope.dataset),
                    selectinload(models.InferenceBatchDatasetScope.foundation_model_run),
                ),
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

        # Calculate duration if completed
        duration_seconds = None
        if db_obj.started_on and db_obj.completed_on:
            duration_seconds = (db_obj.completed_on - db_obj.started_on).total_seconds()

        # Build a pseudo ml_project_uuid (for compatibility with existing schema)
        ml_project_uuid = UUID(int=0)
        if db_obj.ml_project:
            ml_project_uuid = db_obj.ml_project.uuid

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "ml_project_id": db_obj.ml_project_id or 0,
            "ml_project_uuid": ml_project_uuid,
            "custom_model_id": db_obj.custom_model_id,
            "custom_model": None,  # Would require building CustomModel schema
            "status": status,
            "confidence_threshold": db_obj.confidence_threshold,
            "total_clips": db_obj.total_items,
            "processed_clips": db_obj.processed_items,
            "total_predictions": total_predictions or 0,
            "reviewed_count": reviewed_count or 0,
            "confirmed_count": confirmed_count or 0,
            "rejected_count": rejected_count or 0,
            "uncertain_count": uncertain_count or 0,
            "started_at": db_obj.started_on,
            "completed_at": db_obj.completed_on,
            "duration_seconds": duration_seconds,
            "error_message": db_obj.error_message,
            "notes": db_obj.description,
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
                selectinload(models.InferencePrediction.inference_batch),
            )
        )
        result = await session.execute(stmt)
        db_obj = result.scalar_one()

        # Get the target tag from the custom model
        custom_model = await session.get(
            models.CustomModel, db_obj.inference_batch.custom_model_id
        )
        tag = await session.get(models.Tag, custom_model.target_tag_id)

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
            "tag_id": tag.id if tag else 0,
            "tag": schemas.Tag.model_validate(tag) if tag else None,
            "confidence": db_obj.confidence,
            "rank": 1,  # Would need separate calculation
            "review_status": review_status_map.get(
                db_obj.review_status,
                schemas.InferencePredictionReviewStatus.UNREVIEWED,
            ),
            "reviewed_at": db_obj.reviewed_on,
            "reviewed_by_id": db_obj.reviewed_by_id,
            "notes": db_obj.notes,
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

        if not await can_view_inference_batch(session, db_obj, db_user):
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {pk} not found"
            )

        return await self._build_schema(session, db_obj)

    async def get_many(
        self,
        session: AsyncSession,
        *,
        project_id: str | None = None,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.InferenceBatch], int]:
        """Get multiple inference batches with access control."""
        db_user = await self._resolve_user(session, user)
        access_filters = await filter_inference_batches_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        # Filter by project if specified
        if project_id:
            combined_filters.append(self._model.project_id == project_id)

        db_objs, count = await common.get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters or None,
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
        data: schemas.InferenceBatchCreate,
        *,
        project_uuid: str,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.InferenceBatch:
        """Create a new standalone inference batch."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create inference batches"
            )

        # Verify project access
        project_membership = await _get_project_membership(
            session, project_uuid, db_user
        )
        if not db_user.is_superuser and project_membership is None:
            raise exceptions.PermissionDeniedError(
                "You do not have access to this project"
            )

        # Validate custom model exists
        custom_model = await session.get(models.CustomModel, data.custom_model_id)
        if custom_model is None:
            raise exceptions.NotFoundError(
                f"Custom model with id {data.custom_model_id} not found"
            )

        # Validate custom model is trained/deployed
        if custom_model.status not in [
            models.CustomModelStatus.TRAINED,
            models.CustomModelStatus.DEPLOYED,
        ]:
            raise exceptions.InvalidDataError(
                f"Custom model has not completed training (status: {custom_model.status.value})"
            )

        # Generate name if not provided
        name = data.name
        if not name:
            name = f"Inference batch - {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%d %H:%M')}"

        # Create the inference batch
        db_obj = await common.create_object(
            session,
            self._model,
            name=name,
            project_id=project_uuid,
            custom_model_id=data.custom_model_id,
            confidence_threshold=data.confidence_threshold,
            description=data.notes,
            status=models.InferenceBatchStatus.PENDING,
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

        if not await can_edit_inference_batch(session, db_obj, db_user):
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

    async def run(
        self,
        session: AsyncSession,
        inference_batch_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.InferenceBatch:
        """Start running inference for a batch.

        This loads the trained model and runs inference on all clips
        in the configured dataset scopes.
        """
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(inference_batch_uuid),
        )

        if not await can_edit_inference_batch(session, db_obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to run inference for this batch"
            )

        if db_obj.status not in [
            models.InferenceBatchStatus.PENDING,
            models.InferenceBatchStatus.FAILED,
        ]:
            raise exceptions.InvalidDataError(
                f"Cannot start inference for batch in status {db_obj.status.value}"
            )

        # Update status to running
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(inference_batch_uuid),
            {
                "status": models.InferenceBatchStatus.RUNNING,
                "started_on": datetime.datetime.now(datetime.UTC),
            },
        )

        # TODO: Implement actual inference pipeline
        # The inference process would:
        # 1. Load the trained model
        # 2. For each dataset scope:
        #    a. Get clips with embeddings
        #    b. Run inference on embeddings
        #    c. Create predictions for clips above threshold
        # 3. Update batch status and statistics

        logger.info(
            f"Inference requested for batch {inference_batch_uuid}. "
            "This feature requires ML pipeline integration."
        )

        return await self._build_schema(session, db_obj)

    async def get_predictions(
        self,
        session: AsyncSession,
        inference_batch_uuid: UUID,
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
            self._get_pk_condition(inference_batch_uuid),
        )

        if not await can_view_inference_batch(session, db_obj, db_user):
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {inference_batch_uuid} not found"
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

    async def review_prediction(
        self,
        session: AsyncSession,
        prediction_uuid: UUID,
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

        db_pred = await common.get_object(
            session,
            models.InferencePrediction,
            models.InferencePrediction.uuid == prediction_uuid,
        )

        # Get the batch to check permissions
        batch = await session.get(models.InferenceBatch, db_pred.inference_batch_id)
        if batch is None:
            raise exceptions.NotFoundError(
                f"Inference prediction with uuid {prediction_uuid} not found"
            )

        if not await can_edit_inference_batch(session, batch, db_user):
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
            "reviewed_on": datetime.datetime.now(datetime.UTC),
            "reviewed_by_id": db_user.id,
        }
        if notes is not None:
            update_data["notes"] = notes

        db_pred = await common.update_object(
            session,
            models.InferencePrediction,
            models.InferencePrediction.uuid == prediction_uuid,
            update_data,
        )

        return await self._build_prediction_schema(session, db_pred)


inference_batches_standalone = InferenceBatchStandaloneAPI()
