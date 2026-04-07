"""Service layer for CustomModel lifecycle management."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.repositories.custom_model import CustomModelRepository
from echoroo.schemas.custom_model import CustomModelCreate

logger = logging.getLogger(__name__)


class CustomModelService:
    """Service for creating and managing CustomModel records.

    Encapsulates all business logic and database interactions related to
    custom ML classifier lifecycle: creation, update, deletion, training
    dispatch, and inference run creation.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self._repo = CustomModelRepository(db)

    async def get_model(
        self,
        model_id: UUID,
        project_id: UUID,
    ) -> CustomModel | None:
        """Fetch a CustomModel by ID, scoped to the given project.

        Args:
            model_id: CustomModel's UUID
            project_id: Project's UUID (used for scoping)

        Returns:
            CustomModel instance or None if not found
        """
        return await self._repo.get_by_id_and_project(model_id, project_id)

    async def list_models(
        self,
        project_id: UUID,
        limit: int = 50,
        offset: int = 0,
        tag_id: UUID | None = None,
    ) -> tuple[list[CustomModel], int]:
        """List custom models for a project with optional filters.

        Args:
            project_id: Project's UUID
            limit: Maximum number of results to return
            offset: Number of results to skip
            tag_id: Optional target tag filter

        Returns:
            Tuple of (models list, total count)
        """
        return await self._repo.list_for_project(
            project_id=project_id,
            limit=limit,
            offset=offset,
            tag_id=tag_id,
        )

    async def create_model(
        self,
        project_id: UUID,
        user_id: UUID,
        request: CustomModelCreate,
    ) -> CustomModel:
        """Create a new CustomModel in DRAFT status.

        Args:
            project_id: Project's UUID
            user_id: ID of the user creating the model
            request: Custom model creation data

        Returns:
            Created CustomModel instance
        """
        model = CustomModel(
            project_id=project_id,
            user_id=user_id,
            name=request.name,
            description=request.description,
            target_tag_id=request.target_tag_id,
            training_session_ids=[str(sid) for sid in request.training_session_ids],
            embedding_model_name=request.embedding_model_name,
            status=CustomModelStatus.DRAFT,
        )
        return await self._repo.create(model)

    async def update_model(
        self,
        model: CustomModel,
        name: str | None = None,
        description: str | None = None,
    ) -> CustomModel:
        """Update mutable fields on a CustomModel.

        Only applies changes for fields that are explicitly provided (not None).

        Args:
            model: Existing CustomModel instance to update
            name: New name, or None to leave unchanged
            description: New description, or None to leave unchanged

        Returns:
            Updated and refreshed CustomModel instance
        """
        if name is not None:
            model.name = name
        if description is not None:
            model.description = description
        return await self._repo.update(model)

    async def delete_model(
        self,
        model: CustomModel,
    ) -> None:
        """Delete a CustomModel, also cleaning up its S3 artifact if present.

        Args:
            model: CustomModel instance to delete
        """
        if model.model_artifact_key:
            try:
                from echoroo.core.s3 import get_s3_client  # noqa: PLC0415
                from echoroo.core.settings import get_settings  # noqa: PLC0415

                settings = get_settings()
                s3 = get_s3_client()
                s3.delete_object(Bucket=settings.S3_BUCKET, Key=model.model_artifact_key)
            except Exception:
                logger.warning(
                    "Failed to delete S3 artifact for custom model %s (key=%s)",
                    model.id,
                    model.model_artifact_key,
                )
        await self._repo.remove(model)

    async def start_training(self, model: CustomModel) -> CustomModel:
        """Transition a CustomModel to TRAINING status and dispatch the Celery task.

        Flushes the status change to the database before dispatching so the
        worker sees the updated state immediately.

        Args:
            model: CustomModel instance in DRAFT or FAILED status

        Returns:
            Updated CustomModel with TRAINING status
        """
        model.status = CustomModelStatus.TRAINING
        model.error_message = None
        updated = await self._repo.update(model)

        # Lazy import to avoid circular dependency issues
        from echoroo.workers.classifier_tasks import (  # noqa: PLC0415
            train_custom_model as train_task,
        )

        train_task.delay(str(model.id))
        return updated

    async def create_detection_run(
        self,
        project_id: UUID,
        dataset_id: UUID,
        model: CustomModel,
        threshold: float,
    ) -> DetectionRun:
        """Create a DetectionRun record for a custom model inference job.

        Commits the record before returning so that the Celery worker can load
        it as soon as it starts.

        Args:
            project_id: Project's UUID
            dataset_id: Dataset to run inference on
            model: CustomModel to apply
            threshold: Confidence threshold for annotation creation

        Returns:
            Persisted DetectionRun with PENDING status
        """
        detection_run = DetectionRun(
            project_id=project_id,
            dataset_id=dataset_id,
            model_name="custom_svm",
            model_version=str(model.id),
            parameters={
                "custom_model_id": str(model.id),
                "threshold": threshold,
                "embedding_model_name": model.embedding_model_name,
            },
            status=DetectionRunStatus.PENDING,
            annotation_count=0,
        )
        self.db.add(detection_run)
        await self.db.flush()
        await self.db.refresh(detection_run)

        # Commit before dispatching the Celery task so the worker can load the run
        await self.db.commit()

        return detection_run
