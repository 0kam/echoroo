"""Python API for Custom Models."""

import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.filters.base import Filter

__all__ = [
    "CustomModelAPI",
    "custom_models",
]

logger = logging.getLogger(__name__)


class CustomModelAPI(
    BaseAPI[
        UUID,
        models.CustomModel,
        schemas.CustomModel,
        schemas.CustomModelCreate,
        schemas.CustomModel,
    ]
):
    """API for managing Custom Models."""

    _model = models.CustomModel
    _schema = schemas.CustomModel

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
        db_obj: models.CustomModel,
    ) -> models.CustomModel:
        """Eagerly load relationships needed for schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.ml_project),
                selectinload(self._model.tag),
                selectinload(self._model.created_by),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.CustomModel,
    ) -> schemas.CustomModel:
        """Build schema from database object."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Map model type enum
        model_type_map = {
            models.CustomModelType.LINEAR: schemas.CustomModelType.LINEAR_CLASSIFIER,
            models.CustomModelType.MLP: schemas.CustomModelType.MLP,
            models.CustomModelType.RANDOM_FOREST: schemas.CustomModelType.RANDOM_FOREST,
            models.CustomModelType.SVM: schemas.CustomModelType.SVM,
            models.CustomModelType.GRADIENT_BOOSTING: schemas.CustomModelType.GRADIENT_BOOSTING,
        }
        model_type = model_type_map.get(
            db_obj.model_type, schemas.CustomModelType.MLP
        )

        # Map status enum
        status_map = {
            models.CustomModelStatus.PENDING: schemas.CustomModelStatus.PENDING,
            models.CustomModelStatus.PREPARING: schemas.CustomModelStatus.PREPARING,
            models.CustomModelStatus.TRAINING: schemas.CustomModelStatus.TRAINING,
            models.CustomModelStatus.VALIDATING: schemas.CustomModelStatus.VALIDATING,
            models.CustomModelStatus.COMPLETED: schemas.CustomModelStatus.COMPLETED,
            models.CustomModelStatus.FAILED: schemas.CustomModelStatus.FAILED,
            models.CustomModelStatus.CANCELLED: schemas.CustomModelStatus.CANCELLED,
        }
        status = status_map.get(db_obj.status, schemas.CustomModelStatus.PENDING)

        # Build training config
        training_config = schemas.CustomModelTrainingConfig(
            model_type=model_type,
            train_split=getattr(db_obj, "train_split", 0.8),
            validation_split=getattr(db_obj, "validation_split", 0.1),
            learning_rate=getattr(db_obj, "learning_rate", 0.001),
            batch_size=getattr(db_obj, "batch_size", 32),
            max_epochs=getattr(db_obj, "max_epochs", 100),
            early_stopping_patience=getattr(db_obj, "early_stopping_patience", 10),
            hidden_layers=getattr(db_obj, "hidden_layers", None) or [256, 128],
            dropout_rate=getattr(db_obj, "dropout_rate", 0.3),
            class_weight_balanced=getattr(db_obj, "class_weight_balanced", True),
            random_seed=getattr(db_obj, "random_seed", 42),
        )

        # Build metrics if available
        metrics = None
        if db_obj.status == models.CustomModelStatus.COMPLETED:
            metrics = schemas.CustomModelMetrics(
                accuracy=getattr(db_obj, "accuracy", None),
                precision=getattr(db_obj, "precision", None),
                recall=getattr(db_obj, "recall", None),
                f1_score=getattr(db_obj, "f1_score", None),
                roc_auc=getattr(db_obj, "roc_auc", None),
                pr_auc=getattr(db_obj, "pr_auc", None),
                training_samples=getattr(db_obj, "training_samples", 0),
                validation_samples=getattr(db_obj, "validation_samples", 0),
                positive_samples=getattr(db_obj, "positive_samples", 0),
                negative_samples=getattr(db_obj, "negative_samples", 0),
            )

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "description": db_obj.description,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "tag_id": db_obj.tag_id,
            "tag": schemas.Tag.model_validate(db_obj.tag) if db_obj.tag else None,
            "model_type": model_type,
            "status": status,
            "training_config": training_config,
            "metrics": metrics,
            "model_path": getattr(db_obj, "model_path", None),
            "training_started_at": getattr(db_obj, "training_started_at", None),
            "training_completed_at": getattr(db_obj, "training_completed_at", None),
            "training_duration_seconds": getattr(
                db_obj, "training_duration_seconds", None
            ),
            "error_message": getattr(db_obj, "error_message", None),
            "version": getattr(db_obj, "version", 1),
            "is_active": getattr(db_obj, "is_active", True),
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
        }

        return schemas.CustomModel.model_validate(data)

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.CustomModel:
        """Get a custom model by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Custom model with uuid {pk} not found"
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
    ) -> tuple[Sequence[schemas.CustomModel], int]:
        """Get custom models for an ML project."""
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
        name: str,
        description: str | None = None,
        tag_id: int,
        search_session_ids: list[int] | None = None,
        annotation_project_uuids: list[UUID] | None = None,
        training_config: schemas.CustomModelTrainingConfig,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.CustomModel:
        """Create a new custom model configuration."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create custom models"
            )

        db_ml_project = await self._get_ml_project(session, ml_project.id)
        if not await can_edit_ml_project(session, db_ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to create custom models in this ML project"
            )

        # Ensure at least one training source is provided
        search_session_ids = search_session_ids or []
        annotation_project_uuids = annotation_project_uuids or []
        if not search_session_ids and not annotation_project_uuids:
            raise exceptions.InvalidDataError(
                "At least one search session or annotation project must be provided for training data"
            )

        # Validate tag exists
        tag = await session.get(models.Tag, tag_id)
        if tag is None:
            raise exceptions.NotFoundError(f"Tag with id {tag_id} not found")

        # Validate search sessions exist and belong to this project
        for session_id in search_session_ids:
            search_session = await session.get(models.SearchSession, session_id)
            if search_session is None:
                raise exceptions.NotFoundError(
                    f"Search session with id {session_id} not found"
                )
            if search_session.ml_project_id != ml_project.id:
                raise exceptions.InvalidDataError(
                    f"Search session {session_id} does not belong to this ML project"
                )

        # Validate annotation projects exist
        annotation_project_ids = []
        for ap_uuid in annotation_project_uuids:
            stmt = select(models.AnnotationProject).where(
                models.AnnotationProject.uuid == ap_uuid
            )
            result = await session.execute(stmt)
            ap = result.scalar_one_or_none()
            if ap is None:
                raise exceptions.NotFoundError(
                    f"Annotation project with uuid {ap_uuid} not found"
                )
            annotation_project_ids.append(ap.id)

        # Map model type
        model_type_map = {
            schemas.CustomModelType.LINEAR_CLASSIFIER: models.CustomModelType.LINEAR,
            schemas.CustomModelType.MLP: models.CustomModelType.MLP,
            schemas.CustomModelType.RANDOM_FOREST: models.CustomModelType.RANDOM_FOREST,
            schemas.CustomModelType.SVM: models.CustomModelType.SVM,
            schemas.CustomModelType.GRADIENT_BOOSTING: models.CustomModelType.GRADIENT_BOOSTING,
        }

        db_obj = await common.create_object(
            session,
            self._model,
            name=name,
            description=description,
            ml_project_id=ml_project.id,
            tag_id=tag_id,
            model_type=model_type_map.get(
                training_config.model_type, models.CustomModelType.MLP
            ),
            status=models.CustomModelStatus.PENDING,
            created_by_id=db_user.id,
        )

        # Create training sources for annotation projects
        for ap_uuid in annotation_project_uuids:
            training_source = models.CustomModelTrainingSource(
                custom_model_id=db_obj.id,
                source_type=models.TrainingDataSource.ANNOTATION_PROJECT,
                source_uuid=ap_uuid,
                is_positive=True,
            )
            session.add(training_source)

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.CustomModel,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.CustomModel:
        """Delete a custom model."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this custom model"
            )

        result = await self._build_schema(session, db_obj)

        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def start_training(
        self,
        session: AsyncSession,
        obj: schemas.CustomModel,
        ml_project: schemas.MLProject,
        *,
        audio_dir: str | None = None,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.CustomModel:
        """Start training a custom model.

        This is a placeholder that would integrate with the ML pipeline
        to actually train the model using labeled search results.
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
                "You do not have permission to start training this model"
            )

        if db_obj.status not in [
            models.CustomModelStatus.PENDING,
            models.CustomModelStatus.FAILED,
            models.CustomModelStatus.CANCELLED,
        ]:
            raise exceptions.InvalidDataError(
                f"Cannot start training for model in status {db_obj.status.value}"
            )

        # Update status to preparing
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
            {"status": models.CustomModelStatus.PREPARING},
        )

        # TODO: Implement actual training
        # This would:
        # 1. Collect labeled results from associated search sessions
        # 2. Extract embeddings for the clips
        # 3. Train the classifier
        # 4. Evaluate on validation set
        # 5. Save the model
        # 6. Update metrics

        logger.info(
            f"Training requested for custom model {obj.uuid}. "
            "This feature requires ML pipeline integration."
        )

        return await self._build_schema(session, db_obj)

    async def get_training_status(
        self,
        session: AsyncSession,
        obj: schemas.CustomModel,
        user: models.User | None = None,
    ) -> schemas.TrainingProgress:
        """Get the current training status of a model."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Custom model with uuid {obj.uuid} not found"
            )

        # Map status
        status_map = {
            models.CustomModelStatus.PENDING: schemas.CustomModelStatus.PENDING,
            models.CustomModelStatus.PREPARING: schemas.CustomModelStatus.PREPARING,
            models.CustomModelStatus.TRAINING: schemas.CustomModelStatus.TRAINING,
            models.CustomModelStatus.VALIDATING: schemas.CustomModelStatus.VALIDATING,
            models.CustomModelStatus.COMPLETED: schemas.CustomModelStatus.COMPLETED,
            models.CustomModelStatus.FAILED: schemas.CustomModelStatus.FAILED,
            models.CustomModelStatus.CANCELLED: schemas.CustomModelStatus.CANCELLED,
        }

        return schemas.TrainingProgress(
            status=status_map.get(db_obj.status, schemas.CustomModelStatus.PENDING),
            current_epoch=getattr(db_obj, "current_epoch", 0),
            total_epochs=getattr(db_obj, "total_epochs", 0),
            current_step=0,
            total_steps=0,
            train_loss=getattr(db_obj, "train_loss", None),
            val_loss=getattr(db_obj, "val_loss", None),
            train_accuracy=getattr(db_obj, "train_accuracy", None),
            val_accuracy=getattr(db_obj, "val_accuracy", None),
            best_val_loss=getattr(db_obj, "best_val_loss", None),
            epochs_without_improvement=0,
            estimated_time_remaining_seconds=None,
            message=(
                getattr(db_obj, "error_message", None)
                or f"Status: {db_obj.status.value}"
            ),
        )


custom_models = CustomModelAPI()
