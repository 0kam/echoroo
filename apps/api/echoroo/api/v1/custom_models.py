"""Custom model management API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access
from echoroo.middleware.auth import CurrentUser
from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.schemas.custom_model import (
    CustomModelApplyResponse,
    CustomModelCreate,
    CustomModelListResponse,
    CustomModelResponse,
    CustomModelTrainRequest,
    CustomModelUpdate,
)
from echoroo.services.custom_model import CustomModelService

router = APIRouter(prefix="/projects/{project_id}/custom-models", tags=["custom-models"])


def get_custom_model_service(db: DbSession) -> CustomModelService:
    """Get CustomModelService instance.

    Args:
        db: Database session

    Returns:
        CustomModelService instance
    """
    return CustomModelService(db)


CustomModelServiceDep = Annotated[CustomModelService, Depends(get_custom_model_service)]


async def get_model_or_404(
    model_id: UUID,
    project_id: UUID,
    service: CustomModelService,
) -> CustomModel:
    """Fetch a CustomModel by ID, scoped to the given project.

    Args:
        model_id: CustomModel's UUID
        project_id: Project's UUID (used for scoping)
        service: CustomModelService instance

    Returns:
        CustomModel instance

    Raises:
        HTTPException: 404 if model not found in project
    """
    model = await service.get_model(model_id, project_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Custom model not found",
        )
    return model


@router.get(
    "",
    response_model=CustomModelListResponse,
    summary="List custom models",
    description="List custom models for a project with optional tag filter",
)
async def list_custom_models(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
    limit: int = 50,
    offset: int = 0,
    tag_id: UUID | None = None,
) -> CustomModelListResponse:
    """List custom models for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance
        limit: Maximum number of results to return (default: 50)
        offset: Number of results to skip (default: 0)
        tag_id: Optional target tag filter

    Returns:
        Paginated list of custom models

    Raises:
        401: Not authenticated
        403: Access denied
    """
    await check_project_access(project_id, current_user.id, db)
    models, total = await service.list_models(
        project_id=project_id,
        limit=limit,
        offset=offset,
        tag_id=tag_id,
    )
    return CustomModelListResponse(models=models, total=total)


@router.post(
    "",
    response_model=CustomModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create custom model",
    description="Create a new custom model in DRAFT status",
)
async def create_custom_model(
    project_id: UUID,
    request: CustomModelCreate,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> CustomModelResponse:
    """Create a new custom model.

    Args:
        project_id: Project's UUID
        request: Custom model creation data
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Created custom model with DRAFT status

    Raises:
        401: Not authenticated
        403: Access denied
        422: Validation error
    """
    await check_project_access(project_id, current_user.id, db)
    model = await service.create_model(
        project_id=project_id,
        user_id=current_user.id,
        request=request,
    )
    return CustomModelResponse.model_validate(model)


@router.get(
    "/{model_id}",
    response_model=CustomModelResponse,
    summary="Get custom model",
    description="Get a custom model by ID",
)
async def get_custom_model(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> CustomModelResponse:
    """Get custom model by ID.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Custom model detail

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)
    return CustomModelResponse.model_validate(model)


@router.patch(
    "/{model_id}",
    response_model=CustomModelResponse,
    summary="Update custom model",
    description="Update a custom model's name and description (only allowed in DRAFT status)",
)
async def update_custom_model(
    project_id: UUID,
    model_id: UUID,
    request: CustomModelUpdate,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> CustomModelResponse:
    """Update custom model metadata.

    Only allowed when the model is in DRAFT status.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        request: Fields to update (name, description)
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Updated custom model

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: Model is not in DRAFT status
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    if model.status != CustomModelStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot update model with status '{model.status}'. Only DRAFT models can be updated.",
        )

    updated = await service.update_model(
        model=model,
        name=request.name,
        description=request.description,
    )
    return CustomModelResponse.model_validate(updated)


@router.delete(
    "/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete custom model",
    description="Delete a custom model and its S3 artifact if present",
)
async def delete_custom_model(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> None:
    """Delete a custom model.

    Also deletes the associated S3 model artifact if one exists.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)
    await service.delete_model(model)


@router.post(
    "/{model_id}/train",
    response_model=CustomModelResponse,
    summary="Start model training",
    description="Dispatch a Celery training task. Allowed only when status is DRAFT or FAILED.",
)
async def train_custom_model(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
    request: CustomModelTrainRequest | None = None,
) -> CustomModelResponse:
    """Start training for a custom model.

    Transitions the model to TRAINING status and dispatches the Celery task.
    Only allowed when the model is in DRAFT or FAILED status.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance
        request: Optional training parameters

    Returns:
        Updated custom model with TRAINING status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: Model is not in DRAFT or FAILED status
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    if model.status not in (CustomModelStatus.DRAFT, CustomModelStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot start training for model with status '{model.status}'. "
                "Only DRAFT or FAILED models can be trained."
            ),
        )

    updated = await service.start_training(model)
    return CustomModelResponse.model_validate(updated)


@router.get(
    "/{model_id}/status",
    response_model=CustomModelResponse,
    summary="Get training status",
    description="Lightweight polling endpoint to check the current training status",
)
async def get_custom_model_status(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> CustomModelResponse:
    """Get current training status of a custom model.

    Intended for polling during training. Returns the full model response
    so callers can inspect status, metrics, and error_message in one request.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Custom model with current status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)
    return CustomModelResponse.model_validate(model)


@router.post(
    "/{model_id}/apply",
    response_model=CustomModelApplyResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Apply custom model to dataset",
    description=(
        "Apply a trained custom SVM model to all Perch embeddings in a dataset, "
        "creating detection annotations for clips above the confidence threshold."
    ),
)
async def apply_custom_model(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
    dataset_id: UUID = Query(..., description="Dataset UUID to apply the model to"),
    threshold: float = Query(0.5, ge=0.0, le=1.0, description="Confidence threshold (0.0-1.0)"),
) -> CustomModelApplyResponse:
    """Apply a trained custom model to all embeddings in a dataset.

    Creates a DetectionRun record and dispatches a Celery task to run SVM
    inference on all Perch embeddings in the specified dataset. Annotations
    for clips with confidence >= threshold are created and linked to the run.

    Only models with status TRAINED or DEPLOYED can be applied.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance
        dataset_id: Dataset to run inference on
        threshold: Minimum confidence score for annotation creation (default: 0.5)

    Returns:
        Detection run ID and initial status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: Model is not in TRAINED or DEPLOYED status, or lacks a model artifact
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    if model.status not in (CustomModelStatus.TRAINED, CustomModelStatus.DEPLOYED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot apply model with status '{model.status}'. "
                "Only TRAINED or DEPLOYED models can be applied to a dataset."
            ),
        )

    if not model.model_artifact_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Model has no artifact. Please retrain before applying.",
        )

    detection_run = await service.create_detection_run(
        project_id=project_id,
        dataset_id=dataset_id,
        model=model,
        threshold=threshold,
    )
    detection_run_id = detection_run.id

    # Lazy import to avoid circular dependency issues
    from echoroo.workers.classifier_tasks import run_custom_model_inference  # noqa: PLC0415

    run_custom_model_inference.delay(
        str(model_id),
        str(detection_run_id),
        str(dataset_id),
        threshold,
    )

    from echoroo.models.enums import DetectionRunStatus  # noqa: PLC0415

    return CustomModelApplyResponse(
        detection_run_id=detection_run_id,
        status=DetectionRunStatus.PENDING,
    )
