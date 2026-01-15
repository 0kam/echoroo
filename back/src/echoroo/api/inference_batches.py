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
                selectinload(self._model.custom_model).options(
                    selectinload(models.CustomModel.ml_project),
                    selectinload(models.CustomModel.target_tag),
                ),
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

        # Build CustomModel schema if available
        custom_model_data = None
        if db_obj.custom_model:
            cm = db_obj.custom_model

            # Model type mapping (backend enum → API enum)
            model_type_map = {
                models.CustomModelType.SELF_TRAINING_SVM: schemas.CustomModelType.SVM,
            }
            model_type = model_type_map.get(
                cm.model_type, schemas.CustomModelType.SVM
            )

            # Map status enum
            cm_status_map = {
                models.CustomModelStatus.DRAFT: schemas.CustomModelStatus.DRAFT,
                models.CustomModelStatus.TRAINING: schemas.CustomModelStatus.TRAINING,
                models.CustomModelStatus.TRAINED: schemas.CustomModelStatus.TRAINED,
                models.CustomModelStatus.FAILED: schemas.CustomModelStatus.FAILED,
                models.CustomModelStatus.DEPLOYED: schemas.CustomModelStatus.DEPLOYED,
                models.CustomModelStatus.ARCHIVED: schemas.CustomModelStatus.ARCHIVED,
            }
            cm_status = cm_status_map.get(cm.status, schemas.CustomModelStatus.DRAFT)

            # Build training config
            training_config = schemas.CustomModelTrainingConfig(
                model_type=model_type,
                train_split=getattr(cm, "train_split", 0.8),
                validation_split=getattr(cm, "validation_split", 0.1),
                learning_rate=getattr(cm, "learning_rate", 0.001),
                batch_size=getattr(cm, "batch_size", 32),
                max_epochs=getattr(cm, "max_epochs", 100),
                early_stopping_patience=getattr(cm, "early_stopping_patience", 10),
                hidden_layers=getattr(cm, "hidden_layers", None) or [256, 128],
                dropout_rate=getattr(cm, "dropout_rate", 0.3),
                class_weight_balanced=getattr(cm, "class_weight_balanced", True),
                random_seed=getattr(cm, "random_seed", 42),
            )

            # Build metrics if available
            metrics = None
            if cm.status in (
                models.CustomModelStatus.TRAINED,
                models.CustomModelStatus.DEPLOYED,
            ):
                metrics = schemas.CustomModelMetrics(
                    accuracy=getattr(cm, "accuracy", None),
                    precision=getattr(cm, "precision", None),
                    recall=getattr(cm, "recall", None),
                    f1_score=getattr(cm, "f1_score", None),
                    roc_auc=getattr(cm, "roc_auc", None),
                    pr_auc=getattr(cm, "pr_auc", None),
                    training_samples=getattr(cm, "training_samples", None) or 0,
                    validation_samples=getattr(cm, "validation_samples", None) or 0,
                    positive_samples=getattr(cm, "positive_samples", None) or 0,
                    negative_samples=getattr(cm, "negative_samples", None) or 0,
                )

            custom_model_data = schemas.CustomModel(
                uuid=cm.uuid,
                id=cm.id,
                name=cm.name,
                description=cm.description,
                ml_project_id=cm.ml_project_id if cm.ml_project_id is not None else None,
                ml_project_uuid=cm.ml_project.uuid if cm.ml_project else None,
                tag_id=cm.target_tag_id if cm.target_tag_id is not None else None,
                tag=schemas.Tag.model_validate(cm.target_tag) if cm.target_tag else None,
                model_type=model_type,
                status=cm_status,
                training_config=training_config,
                metrics=metrics,
                model_path=getattr(cm, "model_path", None),
                training_started_at=getattr(cm, "training_started_at", None),
                training_completed_at=getattr(cm, "training_completed_at", None),
                training_duration_seconds=getattr(cm, "training_duration_seconds", None),
                error_message=getattr(cm, "error_message", None),
                version=getattr(cm, "version", 1),
                is_active=getattr(cm, "is_active", True),
                created_by_id=cm.created_by_id,
                created_on=cm.created_on,
            )

        # Calculate duration if completed
        duration_seconds = None
        if db_obj.started_on and db_obj.completed_on:
            duration_seconds = (db_obj.completed_on - db_obj.started_on).total_seconds()

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "custom_model_id": db_obj.custom_model_id,
            "custom_model": custom_model_data,
            "status": status,
            "confidence_threshold": db_obj.confidence_threshold,
            "total_clips": db_obj.total_items,
            "processed_clips": db_obj.processed_items,
            "total_predictions": total_predictions or 0,
            "positive_predictions_count": db_obj.positive_predictions_count,
            "negative_predictions_count": db_obj.negative_predictions_count,
            "average_confidence": db_obj.average_confidence,
            "started_at": db_obj.started_on,
            "completed_at": db_obj.completed_on,
            "duration_seconds": duration_seconds,
            "error_message": db_obj.error_message,
            "description": db_obj.description,
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
            "confidence": db_obj.confidence,
            "predicted_positive": db_obj.predicted_positive,
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

        if db_obj.ml_project_id is None:
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {pk} not found"
            )

        ml_project_id = db_obj.ml_project_id
        assert ml_project_id is not None
        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {pk} not found"
            )

        return await self._build_schema(session, db_obj)

    async def get_many(  # type: ignore[override]
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
        description: str | None = None,
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

        # Validate custom model is trained or deployed
        if custom_model.status not in (
            models.CustomModelStatus.TRAINED,
            models.CustomModelStatus.DEPLOYED,
        ):
            raise exceptions.InvalidDataError(
                f"Custom model {custom_model_id} must be trained or deployed (current: {custom_model.status})"
            )

        # Calculate total clips to process
        # Get all datasets associated with this ML project via dataset scopes
        dataset_scope_stmt = select(models.MLProjectDatasetScope).where(
            models.MLProjectDatasetScope.ml_project_id == ml_project.id
        )
        dataset_scopes = list((await session.scalars(dataset_scope_stmt)).all())

        total_clips = 0
        if clip_ids:
            # Use specific clip IDs if provided
            total_clips = len(clip_ids)
        else:
            # Count clips from ML project's dataset scopes
            if dataset_scopes:
                dataset_ids = [scope.dataset_id for scope in dataset_scopes]

                # Count clips in these datasets
                clip_count_stmt = (
                    select(func.count(models.Clip.id))
                    .join(models.Recording, models.Clip.recording_id == models.Recording.id)
                    .join(
                        models.DatasetRecording,
                        models.Recording.id == models.DatasetRecording.recording_id,
                    )
                    .where(models.DatasetRecording.dataset_id.in_(dataset_ids))
                )

                total_clips = await session.scalar(clip_count_stmt) or 0

        db_obj = await common.create_object(
            session,
            self._model,
            name=name,
            ml_project_id=ml_project.id,
            custom_model_id=custom_model_id,
            confidence_threshold=confidence_threshold,
            status=models.InferenceBatchStatus.PENDING,
            description=description,
            created_by_id=db_user.id,
            total_items=total_clips,
            processed_items=0,
        )

        # Create InferenceBatchDatasetScope records from MLProjectDatasetScope
        for ml_dataset_scope in dataset_scopes:
            dataset_scope = models.InferenceBatchDatasetScope(
                inference_batch_id=db_obj.id,
                dataset_id=ml_dataset_scope.dataset_id,
                foundation_model_run_id=ml_dataset_scope.foundation_model_run_id,
                clips_processed=0,
                positive_count=0,
            )
            session.add(dataset_scope)

        await session.flush()

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

        if db_obj.ml_project_id is None:
            raise exceptions.NotFoundError(
                "Inference batch not found"
            )

        ml_project_id = db_obj.ml_project_id
        assert ml_project_id is not None
        ml_project = await self._get_ml_project(session, ml_project_id)

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

        if db_obj.ml_project_id is None:
            raise exceptions.NotFoundError(
                "Inference batch not found"
            )

        ml_project_id = db_obj.ml_project_id
        assert ml_project_id is not None
        db_ml_project = await self._get_ml_project(session, ml_project_id)

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

        # Update status to running
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
            {
                "status": models.InferenceBatchStatus.RUNNING,
                "started_on": datetime.now(timezone.utc),
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
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.InferencePrediction], int]:
        """Get predictions for an inference batch."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        if db_obj.ml_project_id is None:
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {obj.uuid} not found"
            )

        ml_project_id = db_obj.ml_project_id
        assert ml_project_id is not None
        ml_project = await self._get_ml_project(session, ml_project_id)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Inference batch with uuid {obj.uuid} not found"
            )

        # Build filters
        filters: list[ColumnExpressionArgument] = [
            models.InferencePrediction.inference_batch_id == db_obj.id
        ]

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
        if batch is None or batch.ml_project_id is None:
            raise exceptions.NotFoundError(
                f"Inference prediction with uuid {pk} not found"
            )

        ml_project_id = batch.ml_project_id
        assert ml_project_id is not None
        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Inference prediction with uuid {pk} not found"
            )

        return await self._build_prediction_schema(session, db_obj)


inference_batches = InferenceBatchAPI()
