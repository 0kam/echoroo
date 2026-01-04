"""REST API routes for Standalone Custom Models.

Custom Models are machine learning classifiers trained to distinguish
target sounds from background noise. This endpoint provides standalone
access to custom models without requiring the ML Project workflow.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from echoroo import models, schemas
from echoroo.api import custom_models_standalone as api
from echoroo.routes.dependencies import (
    EchorooSettings,
    Session,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.types import Limit, Offset

__all__ = ["get_custom_models_router"]


def get_custom_models_router(settings: EchorooSettings) -> APIRouter:
    """Create a router with Custom Models endpoints wired with authentication."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # Custom Model CRUD
    # =========================================================================

    @router.get(
        "/",
        response_model=schemas.Page[schemas.CustomModel],
    )
    async def get_custom_models(
        session: Session,
        project_id: str | None = Query(
            default=None,
            description="Filter by project ID",
        ),
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.CustomModel]:
        """Get a paginated list of custom models.

        Returns custom models accessible to the current user, optionally
        filtered by project.
        """
        models_list, total = await api.custom_models_standalone.get_many(
            session,
            project_id=project_id,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=models_list,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/",
        response_model=schemas.CustomModel,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_custom_model(
        session: Session,
        data: schemas.CustomModelCreateStandalone,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Create a new custom model.

        Creates a custom model configuration with the specified dataset scopes
        and training sources. The model must be trained before it can be used
        for inference.

        **Required fields:**
        - name: Human-readable name for the model
        - project_uuid: Project for access control
        - target_tag_uuid: Species/sound tag to detect
        - dataset_scopes: At least one dataset scope with embedding source
        - training_sources: At least one positive training source
        """
        custom_model = await api.custom_models_standalone.create(
            session,
            data,
            user=user,
        )
        await session.commit()
        return custom_model

    @router.get(
        "/{custom_model_uuid}",
        response_model=schemas.CustomModel,
    )
    async def get_custom_model(
        session: Session,
        custom_model_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.CustomModel:
        """Get a custom model by UUID."""
        return await api.custom_models_standalone.get(
            session,
            custom_model_uuid,
            user=user,
        )

    @router.delete(
        "/{custom_model_uuid}",
        response_model=schemas.CustomModel,
    )
    async def delete_custom_model(
        session: Session,
        custom_model_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Delete a custom model.

        Deletes the custom model and all associated data including
        dataset scopes and training sources. This action cannot be undone.
        """
        custom_model = await api.custom_models_standalone.get(
            session,
            custom_model_uuid,
            user=user,
        )
        deleted = await api.custom_models_standalone.delete(
            session,
            custom_model,
            user=user,
        )
        await session.commit()
        return deleted

    # =========================================================================
    # Training Operations
    # =========================================================================

    @router.post(
        "/{custom_model_uuid}/train",
        response_model=schemas.CustomModel,
    )
    async def start_training(
        session: Session,
        custom_model_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Start training a custom model.

        Collects training data from all configured sources and begins
        the model training process. Training data is collected from:
        - Sound Search results (saved as annotations)
        - Annotation Project annotations

        The model status will be updated to 'training' and progress can
        be monitored via the /status endpoint.

        **Requirements:**
        - Model must be in 'pending' or 'failed' status
        - At least one positive training source must exist
        """
        updated = await api.custom_models_standalone.start_training(
            session,
            custom_model_uuid,
            user=user,
        )
        await session.commit()
        return updated

    @router.post(
        "/{custom_model_uuid}/deploy",
        response_model=schemas.CustomModel,
    )
    async def deploy_custom_model(
        session: Session,
        custom_model_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.CustomModel:
        """Deploy a trained custom model for inference.

        Marks a trained model as deployed and ready for use in inference
        batches. Only models with status 'trained' can be deployed.
        """
        updated = await api.custom_models_standalone.deploy(
            session,
            custom_model_uuid,
            user=user,
        )
        await session.commit()
        return updated

    @router.get(
        "/{custom_model_uuid}/status",
        response_model=schemas.TrainingProgress,
    )
    async def get_training_status(
        session: Session,
        custom_model_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.TrainingProgress:
        """Get the training status of a custom model.

        Returns current training progress including epoch, loss metrics,
        and estimated time remaining.
        """
        return await api.custom_models_standalone.get_training_status(
            session,
            custom_model_uuid,
            user=user,
        )

    return router
