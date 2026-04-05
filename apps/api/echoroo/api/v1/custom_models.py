"""Custom model management API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from echoroo.core.database import DbSession
from echoroo.core.s3 import get_s3_client
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.models.custom_model import CustomModel, CustomModelStatus
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.custom_model import (
    CustomModelApplyResponse,
    CustomModelCreate,
    CustomModelListResponse,
    CustomModelResponse,
    CustomModelTrainRequest,
    CustomModelUpdate,
)

router = APIRouter(prefix="/projects/{project_id}/custom-models", tags=["custom-models"])


async def check_project_access(project_id: UUID, user_id: UUID, db: DbSession) -> None:
    """Check if user has access to the project.

    Args:
        project_id: Project's UUID
        user_id: User's UUID
        db: Database session

    Raises:
        HTTPException: 403 if user doesn't have access
    """
    project_repo = ProjectRepository(db)
    has_access = await project_repo.has_project_access(project_id, user_id)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to project",
        )


async def get_model_or_404(model_id: UUID, project_id: UUID, db: DbSession) -> CustomModel:
    """Fetch a CustomModel by ID, scoped to the given project.

    Args:
        model_id: CustomModel's UUID
        project_id: Project's UUID (used for scoping)
        db: Database session

    Returns:
        CustomModel instance

    Raises:
        HTTPException: 404 if model not found in project
    """
    result = await db.execute(
        select(CustomModel).where(
            CustomModel.id == model_id,
            CustomModel.project_id == project_id,
        )
    )
    model = result.scalar_one_or_none()
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
    limit: int = 50,
    offset: int = 0,
    tag_id: UUID | None = None,
) -> CustomModelListResponse:
    """List custom models for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        db: Database session
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

    query = select(CustomModel).where(CustomModel.project_id == project_id)
    count_query = select(func.count()).select_from(CustomModel).where(CustomModel.project_id == project_id)

    if tag_id is not None:
        query = query.where(CustomModel.target_tag_id == tag_id)
        count_query = count_query.where(CustomModel.target_tag_id == tag_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(CustomModel.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    models = list(result.scalars().all())

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
) -> CustomModelResponse:
    """Create a new custom model.

    Args:
        project_id: Project's UUID
        request: Custom model creation data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created custom model with DRAFT status

    Raises:
        401: Not authenticated
        403: Access denied
        422: Validation error
    """
    await check_project_access(project_id, current_user.id, db)

    model = CustomModel(
        project_id=project_id,
        user_id=current_user.id,
        name=request.name,
        description=request.description,
        target_tag_id=request.target_tag_id,
        training_session_ids=[str(sid) for sid in request.training_session_ids],
        embedding_model_name=request.embedding_model_name,
        status=CustomModelStatus.DRAFT,
    )
    db.add(model)
    await db.flush()
    await db.refresh(model)
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
) -> CustomModelResponse:
    """Get custom model by ID.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Custom model detail

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, db)
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
) -> CustomModelResponse:
    """Update custom model metadata.

    Only allowed when the model is in DRAFT status.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        request: Fields to update (name, description)
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated custom model

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: Model is not in DRAFT status
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, db)

    if model.status != CustomModelStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot update model with status '{model.status}'. Only DRAFT models can be updated.",
        )

    if request.name is not None:
        model.name = request.name
    if request.description is not None:
        model.description = request.description

    await db.flush()
    await db.refresh(model)
    return CustomModelResponse.model_validate(model)


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
) -> None:
    """Delete a custom model.

    Also deletes the associated S3 model artifact if one exists.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, db)

    # Delete S3 artifact if it exists
    if model.model_artifact_key:
        try:
            settings = get_settings()
            s3 = get_s3_client()
            s3.delete_object(Bucket=settings.S3_BUCKET, Key=model.model_artifact_key)
        except Exception:
            # Non-fatal: log but do not block deletion
            import logging

            logging.getLogger(__name__).warning(
                "Failed to delete S3 artifact for custom model %s (key=%s)",
                model_id,
                model.model_artifact_key,
            )

    await db.delete(model)


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
    model = await get_model_or_404(model_id, project_id, db)

    if model.status not in (CustomModelStatus.DRAFT, CustomModelStatus.FAILED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot start training for model with status '{model.status}'. "
                "Only DRAFT or FAILED models can be trained."
            ),
        )

    # Transition to TRAINING before dispatching the task to avoid race conditions
    model.status = CustomModelStatus.TRAINING
    model.error_message = None

    # Commit status change before dispatching Celery task so the worker sees it
    await db.flush()

    # Lazy import to avoid circular dependency issues
    from echoroo.workers.classifier_tasks import train_custom_model as train_task  # noqa: PLC0415

    train_task.delay(str(model_id))

    await db.refresh(model)
    return CustomModelResponse.model_validate(model)


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
) -> CustomModelResponse:
    """Get current training status of a custom model.

    Intended for polling during training. Returns the full model response
    so callers can inspect status, metrics, and error_message in one request.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session

    Returns:
        Custom model with current status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, db)
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
    model = await get_model_or_404(model_id, project_id, db)

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

    # Create a DetectionRun to track the inference job
    detection_run = DetectionRun(
        project_id=project_id,
        dataset_id=dataset_id,
        model_name="custom_svm",
        model_version=str(model.id),
        parameters={
            "custom_model_id": str(model_id),
            "threshold": threshold,
            "embedding_model_name": model.embedding_model_name,
        },
        status=DetectionRunStatus.PENDING,
        annotation_count=0,
    )
    db.add(detection_run)
    await db.flush()
    await db.refresh(detection_run)

    detection_run_id = detection_run.id

    # Commit before dispatching the Celery task so the worker can load the run
    await db.commit()

    # Lazy import to avoid circular dependency issues
    from echoroo.workers.classifier_tasks import run_custom_model_inference  # noqa: PLC0415

    run_custom_model_inference.delay(
        str(model_id),
        str(detection_run_id),
        str(dataset_id),
        threshold,
    )

    return CustomModelApplyResponse(
        detection_run_id=detection_run_id,
        status=DetectionRunStatus.PENDING,
    )
