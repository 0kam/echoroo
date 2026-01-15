"""REST API routes for Standalone Inference Batches.

Inference Batches allow running trained custom models on datasets to
generate predictions. This endpoint provides standalone access to
inference batches without requiring the ML Project workflow.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo import models, schemas
from echoroo.api import inference_batches_standalone as api
from echoroo.routes.dependencies import (
    EchorooSettings,
    Session,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.types import Limit, Offset

__all__ = ["get_inference_batches_router"]


class InferenceBatchCreateWithProject(schemas.InferenceBatchCreate):
    """Extended schema for creating inference batch with project UUID."""

    project_uuid: str
    """Project UUID for access control."""


def get_inference_batches_router(settings: EchorooSettings) -> APIRouter:
    """Create a router with Inference Batches endpoints wired with authentication."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # Inference Batch CRUD
    # =========================================================================

    @router.get(
        "/",
        response_model=schemas.Page[schemas.InferenceBatch],
    )
    async def get_inference_batches(
        session: Session,
        project_id: str | None = Query(
            default=None,
            description="Filter by project ID",
        ),
        limit: Limit = 10,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.InferenceBatch]:
        """Get a paginated list of inference batches.

        Returns inference batches accessible to the current user, optionally
        filtered by project.
        """
        batches, total = await api.inference_batches_standalone.get_many(
            session,
            project_id=project_id,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=batches,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/",
        response_model=schemas.InferenceBatch,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_inference_batch(
        session: Session,
        data: InferenceBatchCreateWithProject,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferenceBatch:
        """Create a new inference batch.

        Creates an inference batch configuration using the specified
        custom model. The batch must be run to generate predictions.

        **Required fields:**
        - project_uuid: Project for access control
        - custom_model_id: Trained custom model to use

        **Optional fields:**
        - name: Human-readable name (auto-generated if not provided)
        - confidence_threshold: Minimum confidence for predictions (default: 0.5)
        - notes: Optional notes about the batch
        """
        base_data = schemas.InferenceBatchCreate(
            name=data.name,
            custom_model_id=data.custom_model_id,
            confidence_threshold=data.confidence_threshold,
            clip_ids=data.clip_ids,
            include_all_clips=data.include_all_clips,
            exclude_already_labeled=data.exclude_already_labeled,
            description=data.description,
        )
        batch = await api.inference_batches_standalone.create(
            session,
            base_data,
            project_uuid=data.project_uuid,
            user=user,
        )
        await session.commit()
        return batch

    @router.get(
        "/{inference_batch_uuid}",
        response_model=schemas.InferenceBatch,
    )
    async def get_inference_batch(
        session: Session,
        inference_batch_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.InferenceBatch:
        """Get an inference batch by UUID."""
        return await api.inference_batches_standalone.get(
            session,
            inference_batch_uuid,
            user=user,
        )

    @router.delete(
        "/{inference_batch_uuid}",
        response_model=schemas.InferenceBatch,
    )
    async def delete_inference_batch(
        session: Session,
        inference_batch_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferenceBatch:
        """Delete an inference batch.

        Deletes the inference batch and all associated predictions.
        This action cannot be undone.
        """
        batch = await api.inference_batches_standalone.get(
            session,
            inference_batch_uuid,
            user=user,
        )
        deleted = await api.inference_batches_standalone.delete(
            session,
            batch,
            user=user,
        )
        await session.commit()
        return deleted

    # =========================================================================
    # Inference Execution
    # =========================================================================

    @router.post(
        "/{inference_batch_uuid}/run",
        response_model=schemas.InferenceBatch,
    )
    async def run_inference_batch(
        session: Session,
        inference_batch_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.InferenceBatch:
        """Run inference for a batch.

        Executes the trained model on all clips in the configured dataset
        scopes and generates predictions for clips with confidence above
        the threshold.

        **Requirements:**
        - Batch must be in 'pending' or 'failed' status
        - The associated custom model must be trained or deployed
        """
        updated = await api.inference_batches_standalone.run(
            session,
            inference_batch_uuid,
            user=user,
        )
        await session.commit()
        return updated

    # =========================================================================
    # Predictions
    # =========================================================================

    @router.get(
        "/{inference_batch_uuid}/predictions",
        response_model=schemas.Page[schemas.InferencePrediction],
    )
    async def get_predictions(
        session: Session,
        inference_batch_uuid: UUID,
        limit: Limit = 50,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.InferencePrediction]:
        """Get paginated predictions for an inference batch.

        Predictions are sorted by confidence score in descending order.
        """
        predictions, total = await api.inference_batches_standalone.get_predictions(
            session,
            inference_batch_uuid,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=predictions,
            total=total,
            limit=limit,
            offset=offset,
        )

    return router
