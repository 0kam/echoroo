"""Python API for Standalone Custom Models.

This module provides APIs for custom models that operate independently
of the ML Project workflow. It supports multiple dataset scopes and
multiple training sources.
"""

import logging
from typing import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement, ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI, UserResolutionMixin
from echoroo.api.common.permissions import can_manage_project
from echoroo.filters.base import Filter

__all__ = [
    "CustomModelStandaloneAPI",
    "custom_models_standalone",
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


async def can_view_custom_model(
    session: AsyncSession,
    custom_model: models.CustomModel,
    user: models.User | None,
) -> bool:
    """Return True if the user can view the custom model."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    # Check if user is the creator
    if custom_model.created_by_id == user.id:
        return True

    # Check project membership
    if custom_model.project_id:
        membership = await _get_project_membership(
            session, custom_model.project_id, user
        )
        return membership is not None

    return False


async def can_edit_custom_model(
    session: AsyncSession,
    custom_model: models.CustomModel,
    user: models.User | None,
) -> bool:
    """Return True if the user can edit the custom model."""
    if user is None:
        return False

    if user.is_superuser:
        return True

    # Check if user is the creator
    if custom_model.created_by_id == user.id:
        return True

    # Check project manager role
    if custom_model.project_id:
        return await can_manage_project(session, custom_model.project_id, user)

    return False


async def filter_custom_models_by_access(
    session: AsyncSession,
    user: models.User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting custom models accessible to the user."""
    if user is None:
        return [models.CustomModel.id == -1]  # No access for anonymous users

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
        models.CustomModel.created_by_id == user.id,
    ]

    if project_ids:
        conditions.append(models.CustomModel.project_id.in_(project_ids))

    return [or_(*conditions)]


class CustomModelStandaloneAPI(
    BaseAPI[
        UUID,
        models.CustomModel,
        schemas.CustomModel,
        schemas.CustomModelCreateStandalone,
        schemas.CustomModel,
    ],
    UserResolutionMixin,
):
    """API for managing Standalone Custom Models."""

    _model = models.CustomModel
    _schema = schemas.CustomModel

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
                selectinload(self._model.target_tag),
                selectinload(self._model.created_by),
                selectinload(self._model.dataset_scopes).options(
                    selectinload(models.CustomModelDatasetScope.dataset),
                    selectinload(models.CustomModelDatasetScope.foundation_model_run),
                ),
                selectinload(self._model.training_sources),
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
            models.CustomModelType.LOGISTIC_REGRESSION: schemas.CustomModelType.LINEAR_CLASSIFIER,
            models.CustomModelType.SVM_LINEAR: schemas.CustomModelType.SVM,
            models.CustomModelType.MLP_SMALL: schemas.CustomModelType.MLP,
            models.CustomModelType.MLP_MEDIUM: schemas.CustomModelType.MLP,
            models.CustomModelType.RANDOM_FOREST: schemas.CustomModelType.RANDOM_FOREST,
        }
        model_type = model_type_map.get(
            db_obj.model_type, schemas.CustomModelType.MLP
        )

        # Map status enum
        status_map = {
            models.CustomModelStatus.DRAFT: schemas.CustomModelStatus.PENDING,
            models.CustomModelStatus.TRAINING: schemas.CustomModelStatus.TRAINING,
            models.CustomModelStatus.TRAINED: schemas.CustomModelStatus.COMPLETED,
            models.CustomModelStatus.FAILED: schemas.CustomModelStatus.FAILED,
            models.CustomModelStatus.DEPLOYED: schemas.CustomModelStatus.COMPLETED,
            models.CustomModelStatus.ARCHIVED: schemas.CustomModelStatus.CANCELLED,
        }
        status = status_map.get(db_obj.status, schemas.CustomModelStatus.PENDING)

        # Build training config
        hyperparams = db_obj.hyperparameters or {}
        training_config = schemas.CustomModelTrainingConfig(
            model_type=model_type,
            train_split=hyperparams.get("train_split", 0.8),
            validation_split=hyperparams.get("validation_split", 0.1),
            learning_rate=hyperparams.get("learning_rate", 0.001),
            batch_size=hyperparams.get("batch_size", 32),
            max_epochs=hyperparams.get("max_epochs", 100),
            early_stopping_patience=hyperparams.get("early_stopping_patience", 10),
            hidden_layers=hyperparams.get("hidden_layers", [256, 128]),
            dropout_rate=hyperparams.get("dropout_rate", 0.3),
            class_weight_balanced=hyperparams.get("class_weight_balanced", True),
            random_seed=hyperparams.get("random_seed", 42),
        )

        # Build metrics if training is completed
        metrics = None
        if db_obj.status == models.CustomModelStatus.TRAINED:
            metrics = schemas.CustomModelMetrics(
                accuracy=db_obj.accuracy,
                precision=db_obj.precision,
                recall=db_obj.recall,
                f1_score=db_obj.f1_score,
                confusion_matrix=(
                    [
                        [
                            db_obj.confusion_matrix.get("tn", 0),
                            db_obj.confusion_matrix.get("fp", 0),
                        ],
                        [
                            db_obj.confusion_matrix.get("fn", 0),
                            db_obj.confusion_matrix.get("tp", 0),
                        ],
                    ]
                    if db_obj.confusion_matrix
                    else None
                ),
                training_samples=db_obj.training_samples or 0,
                validation_samples=db_obj.validation_samples or 0,
                positive_samples=0,  # Would need separate storage
                negative_samples=0,
            )

        # Calculate training duration if available
        training_duration = None
        if db_obj.training_started_on and db_obj.training_completed_on:
            training_duration = (
                db_obj.training_completed_on - db_obj.training_started_on
            ).total_seconds()

        # Build a pseudo ml_project_uuid (for compatibility with existing schema)
        # Use UUID(int=0) as placeholder for standalone models
        ml_project_uuid = UUID(int=0)
        if db_obj.ml_project:
            ml_project_uuid = db_obj.ml_project.uuid

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "description": db_obj.description,
            "ml_project_id": db_obj.ml_project_id or 0,
            "ml_project_uuid": ml_project_uuid,
            "tag_id": db_obj.target_tag_id,
            "tag": schemas.Tag.model_validate(db_obj.target_tag),
            "model_type": model_type,
            "status": status,
            "training_config": training_config,
            "metrics": metrics,
            "model_path": db_obj.model_path,
            "training_started_at": db_obj.training_started_on,
            "training_completed_at": db_obj.training_completed_on,
            "training_duration_seconds": training_duration,
            "error_message": db_obj.error_message,
            "version": 1,
            "is_active": db_obj.status == models.CustomModelStatus.DEPLOYED,
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

        if not await can_view_custom_model(session, db_obj, db_user):
            raise exceptions.NotFoundError(
                f"Custom model with uuid {pk} not found"
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
    ) -> tuple[Sequence[schemas.CustomModel], int]:
        """Get multiple custom models with access control."""
        db_user = await self._resolve_user(session, user)
        access_filters = await filter_custom_models_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        # Filter by project if specified
        if project_id:
            combined_filters.append(self._model.project_id == project_id)

        # Only get standalone models (no ml_project association)
        # combined_filters.append(self._model.ml_project_id.is_(None))

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
        data: schemas.CustomModelCreateStandalone,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.CustomModel:
        """Create a new standalone custom model."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create custom models"
            )

        # Verify project access
        project_membership = await _get_project_membership(
            session, data.project_uuid, db_user
        )
        if not db_user.is_superuser and project_membership is None:
            raise exceptions.PermissionDeniedError(
                "You do not have access to this project"
            )

        # Get the target tag
        target_tag = await session.scalar(
            select(models.Tag).where(models.Tag.uuid == data.target_tag_uuid)
        )
        if target_tag is None:
            raise exceptions.NotFoundError(
                f"Tag with uuid {data.target_tag_uuid} not found"
            )

        # Validate dataset scopes
        dataset_scope_data = []
        for scope in data.dataset_scopes:
            dataset = await session.scalar(
                select(models.Dataset).where(models.Dataset.uuid == scope.dataset_uuid)
            )
            if dataset is None:
                raise exceptions.NotFoundError(
                    f"Dataset with uuid {scope.dataset_uuid} not found"
                )

            run = await session.scalar(
                select(models.FoundationModelRun).where(
                    models.FoundationModelRun.uuid == scope.foundation_model_run_uuid
                )
            )
            if run is None:
                raise exceptions.NotFoundError(
                    f"Foundation model run with uuid {scope.foundation_model_run_uuid} not found"
                )
            if run.dataset_id != dataset.id:
                raise exceptions.InvalidDataError(
                    f"Foundation model run {scope.foundation_model_run_uuid} "
                    f"does not belong to dataset {scope.dataset_uuid}"
                )
            dataset_scope_data.append((dataset.id, run.id))

        # Validate training sources
        training_source_data = []
        has_positive = False
        for source in data.training_sources:
            if source.is_positive:
                has_positive = True

            # Validate source exists based on type
            if source.source_type == schemas.TrainingDataSource.SOUND_SEARCH:
                sound_search = await session.scalar(
                    select(models.SoundSearch).where(
                        models.SoundSearch.uuid == source.source_uuid
                    )
                )
                if sound_search is None:
                    raise exceptions.NotFoundError(
                        f"Sound search with uuid {source.source_uuid} not found"
                    )
            elif source.source_type == schemas.TrainingDataSource.ANNOTATION_PROJECT:
                annotation_project = await session.scalar(
                    select(models.AnnotationProject).where(
                        models.AnnotationProject.uuid == source.source_uuid
                    )
                )
                if annotation_project is None:
                    raise exceptions.NotFoundError(
                        f"Annotation project with uuid {source.source_uuid} not found"
                    )

            # Validate tag if specified
            tag_uuid = None
            if source.tag_uuid:
                tag = await session.scalar(
                    select(models.Tag).where(models.Tag.uuid == source.tag_uuid)
                )
                if tag is None:
                    raise exceptions.NotFoundError(
                        f"Tag with uuid {source.tag_uuid} not found"
                    )
                tag_uuid = source.tag_uuid

            training_source_data.append({
                "source_type": models.TrainingDataSource(source.source_type.value),
                "source_uuid": source.source_uuid,
                "is_positive": source.is_positive,
                "tag_uuid": tag_uuid,
            })

        if not has_positive:
            raise exceptions.InvalidDataError(
                "At least one training source must be marked as positive"
            )

        # Map model type
        model_type_map = {
            schemas.CustomModelType.LINEAR_CLASSIFIER: models.CustomModelType.LOGISTIC_REGRESSION,
            schemas.CustomModelType.MLP: models.CustomModelType.MLP_MEDIUM,
            schemas.CustomModelType.RANDOM_FOREST: models.CustomModelType.RANDOM_FOREST,
            schemas.CustomModelType.SVM: models.CustomModelType.SVM_LINEAR,
            schemas.CustomModelType.GRADIENT_BOOSTING: models.CustomModelType.RANDOM_FOREST,
        }

        # Store hyperparameters as JSON
        hyperparameters = {
            "train_split": data.training_config.train_split,
            "validation_split": data.training_config.validation_split,
            "learning_rate": data.training_config.learning_rate,
            "batch_size": data.training_config.batch_size,
            "max_epochs": data.training_config.max_epochs,
            "early_stopping_patience": data.training_config.early_stopping_patience,
            "hidden_layers": data.training_config.hidden_layers,
            "dropout_rate": data.training_config.dropout_rate,
            "class_weight_balanced": data.training_config.class_weight_balanced,
            "random_seed": data.training_config.random_seed,
        }

        # Create the custom model
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            description=data.description,
            project_id=data.project_uuid,
            target_tag_id=target_tag.id,
            model_type=model_type_map.get(
                data.model_type, models.CustomModelType.MLP_MEDIUM
            ),
            hyperparameters=hyperparameters,
            status=models.CustomModelStatus.DRAFT,
            created_by_id=db_user.id,
        )

        # Create dataset scopes
        for dataset_id, run_id in dataset_scope_data:
            await common.create_object(
                session,
                models.CustomModelDatasetScope,
                custom_model_id=db_obj.id,
                dataset_id=dataset_id,
                foundation_model_run_id=run_id,
            )

        # Create training sources
        for source_data in training_source_data:
            await common.create_object(
                session,
                models.CustomModelTrainingSource,
                custom_model_id=db_obj.id,
                **source_data,
            )

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

        if not await can_edit_custom_model(session, db_obj, db_user):
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
        custom_model_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.CustomModel:
        """Start training a custom model.

        This collects training data from all configured sources and
        initiates the training process.
        """
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(custom_model_uuid),
        )

        if not await can_edit_custom_model(session, db_obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to start training this model"
            )

        if db_obj.status not in [
            models.CustomModelStatus.DRAFT,
            models.CustomModelStatus.FAILED,
        ]:
            raise exceptions.InvalidDataError(
                f"Cannot start training for model in status {db_obj.status.value}"
            )

        # Update status to training
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(custom_model_uuid),
            {"status": models.CustomModelStatus.TRAINING},
        )

        # TODO: Implement actual training pipeline
        # The training process would:
        # 1. Collect embeddings from training sources
        #    - For SoundSearch: get embeddings from saved annotations
        #    - For AnnotationProject: get embeddings from annotated clips
        # 2. Split into train/validation sets
        # 3. Train the model
        # 4. Evaluate and save metrics
        # 5. Save the trained model

        logger.info(
            f"Training requested for standalone custom model {custom_model_uuid}. "
            "This feature requires ML pipeline integration."
        )

        return await self._build_schema(session, db_obj)

    async def deploy(
        self,
        session: AsyncSession,
        custom_model_uuid: UUID,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.CustomModel:
        """Deploy a trained custom model for inference."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(custom_model_uuid),
        )

        if not await can_edit_custom_model(session, db_obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to deploy this model"
            )

        if db_obj.status != models.CustomModelStatus.TRAINED:
            raise exceptions.InvalidDataError(
                f"Cannot deploy model in status {db_obj.status.value}. "
                "Model must be trained first."
            )

        # Update status to deployed
        db_obj = await common.update_object(
            session,
            self._model,
            self._get_pk_condition(custom_model_uuid),
            {"status": models.CustomModelStatus.DEPLOYED},
        )

        logger.info(f"Custom model {custom_model_uuid} deployed for inference.")

        return await self._build_schema(session, db_obj)

    async def get_training_status(
        self,
        session: AsyncSession,
        custom_model_uuid: UUID,
        user: models.User | None = None,
    ) -> schemas.TrainingProgress:
        """Get the current training status of a model."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(custom_model_uuid),
        )

        if not await can_view_custom_model(session, db_obj, db_user):
            raise exceptions.NotFoundError(
                f"Custom model with uuid {custom_model_uuid} not found"
            )

        # Map status
        status_map = {
            models.CustomModelStatus.DRAFT: schemas.CustomModelStatus.PENDING,
            models.CustomModelStatus.TRAINING: schemas.CustomModelStatus.TRAINING,
            models.CustomModelStatus.TRAINED: schemas.CustomModelStatus.COMPLETED,
            models.CustomModelStatus.FAILED: schemas.CustomModelStatus.FAILED,
            models.CustomModelStatus.DEPLOYED: schemas.CustomModelStatus.COMPLETED,
            models.CustomModelStatus.ARCHIVED: schemas.CustomModelStatus.CANCELLED,
        }

        message = f"Status: {db_obj.status.value}"
        if db_obj.error_message:
            message = db_obj.error_message

        return schemas.TrainingProgress(
            status=status_map.get(db_obj.status, schemas.CustomModelStatus.PENDING),
            current_epoch=0,
            total_epochs=0,
            current_step=0,
            total_steps=0,
            train_loss=None,
            val_loss=None,
            train_accuracy=None,
            val_accuracy=None,
            best_val_loss=None,
            epochs_without_improvement=0,
            estimated_time_remaining_seconds=None,
            message=message,
        )


custom_models_standalone = CustomModelStandaloneAPI()
