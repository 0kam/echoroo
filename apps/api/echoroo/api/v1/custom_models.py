"""Custom model management API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator

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
from echoroo.schemas.sampling import (
    AuditSetEvaluateResponse,
    AuditSetGenerateResponse,
    AuditSetItemResponse,
    AuditSetListResponse,
    SamplingRoundItemResponse,
    SamplingRoundListResponse,
    SamplingRoundResponse,
    SeedSamplingRequest,
)
from echoroo.services.custom_model import CustomModelService

router = APIRouter(prefix="/projects/{project_id}/custom-models", tags=["custom-models"])


class SeedSamplingBody(BaseModel):
    """Request body for the POST /{model_id}/seed-samples endpoint.

    Accepts either reference_embedding_ids (explicit embedding UUIDs to use as
    query vectors) or search_session_id (to load query vectors from the
    search_query_embeddings table). Exactly one must be provided.
    """

    reference_embedding_ids: list[UUID] | None = None
    search_session_id: UUID | None = None
    config: SeedSamplingRequest | None = None

    @model_validator(mode="after")
    def check_reference_source(self) -> SeedSamplingBody:
        """Ensure exactly one reference source is provided."""
        if not self.reference_embedding_ids and not self.search_session_id:
            raise ValueError(
                "Either reference_embedding_ids or search_session_id is required."
            )
        return self


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
    search_session_id: UUID | None = Query(default=None, description="Filter by source search session"),
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
        search_session_id: Optional filter by source search session

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
        search_session_id=search_session_id,
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

    if model.status not in (CustomModelStatus.DRAFT, CustomModelStatus.FAILED, CustomModelStatus.TRAINED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot start training for model with status '{model.status}'. "
                "Only DRAFT, FAILED, or TRAINED models can be trained."
            ),
        )

    updated = await service.start_training(model, train_request=request)
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


@router.post(
    "/{model_id}/seed-samples",
    response_model=SamplingRoundResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start seed sampling",
    description=(
        "Generate three-category seed samples (easy_positive, boundary, others) "
        "for a model using the provided reference embeddings as query vectors. "
        "Only allowed when the model is in DRAFT or FAILED status."
    ),
)
async def create_seed_samples(
    project_id: UUID,
    model_id: UUID,
    body: SeedSamplingBody,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> SamplingRoundResponse:
    """Start seed sample generation for a custom model.

    Creates a SamplingRound record in 'pending' status and dispatches a
    Celery task that will select representative training examples via
    farthest-first sampling. The returned round can be polled via
    GET /{model_id}/sampling-rounds/{round_id}.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        body: Reference embedding IDs and optional sampling config overrides
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Newly created SamplingRound with status='pending'

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: Model is not in DRAFT or FAILED status
        422: No reference_embedding_ids provided
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    if model.status not in (CustomModelStatus.DRAFT, CustomModelStatus.FAILED, CustomModelStatus.TRAINED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot start seed sampling for model with status '{model.status}'. "
                "Only DRAFT, FAILED, or TRAINED models are supported."
            ),
        )

    # Resolve reference embedding IDs from search_session_id if not provided directly
    reference_embedding_ids: list[UUID]
    if body.search_session_id and not body.reference_embedding_ids:
        from sqlalchemy import select as _select  # noqa: PLC0415

        from echoroo.models.search_query_embedding import SearchQueryEmbedding  # noqa: PLC0415

        result = await db.execute(
            _select(SearchQueryEmbedding.id).where(
                SearchQueryEmbedding.search_session_id == body.search_session_id
            )
        )
        ref_ids = [row[0] for row in result.all()]
        if not ref_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No query embeddings found for this search session.",
            )
        reference_embedding_ids = ref_ids
    else:
        # body.reference_embedding_ids is guaranteed non-None by model_validator
        reference_embedding_ids = body.reference_embedding_ids  # type: ignore[assignment]

    round_ = await service.create_seed_sampling_round(
        model=model,
        reference_embedding_ids=reference_embedding_ids,
        seed_sampling_request=body.config,
    )

    return SamplingRoundResponse(
        id=round_.id,
        custom_model_id=round_.custom_model_id,
        round_number=round_.round_number,
        round_type=round_.round_type,
        sampling_config=round_.sampling_config,
        sample_count=round_.sample_count,
        status=round_.status,
        job_id=round_.job_id,
        error_message=round_.error_message,
        created_at=round_.created_at,
        completed_at=round_.completed_at,
        items=[],
    )


@router.post(
    "/{model_id}/suggest-samples",
    response_model=SamplingRoundResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Suggest active learning samples",
    description=(
        "Run one active learning iteration: trains a lightweight SVM on existing labeled data, "
        "scores all unlabeled project embeddings to find the most uncertain samples, "
        "and creates a new SamplingRound for human review. "
        "Requires at least one completed sampling round with sufficient labels "
        "(≥5 positive + ≥5 negative)."
    ),
)
async def suggest_next_samples(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> SamplingRoundResponse:
    """Start an active learning iteration for a custom model.

    Validates that sufficient labeled data exists from previous rounds,
    creates a new SamplingRound in 'pending' status, and dispatches the
    Celery task that selects uncertain, diverse samples near the SVM decision
    boundary. Poll the returned round via GET /{model_id}/sampling-rounds/{round_id}.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Newly created SamplingRound with status='pending'

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: No completed rounds or insufficient labeled data
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    try:
        round_ = await service.suggest_next_samples(model)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return SamplingRoundResponse(
        id=round_.id,
        custom_model_id=round_.custom_model_id,
        round_number=round_.round_number,
        round_type=round_.round_type,
        sampling_config=round_.sampling_config,
        sample_count=round_.sample_count,
        status=round_.status,
        job_id=round_.job_id,
        error_message=round_.error_message,
        created_at=round_.created_at,
        completed_at=round_.completed_at,
        items=[],
    )


@router.get(
    "/{model_id}/sampling-rounds",
    response_model=SamplingRoundListResponse,
    summary="List sampling rounds",
    description="List all sampling rounds for a custom model, ordered by round_number",
)
async def list_sampling_rounds(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> SamplingRoundListResponse:
    """List all sampling rounds for a custom model.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        List of all sampling rounds ordered by round_number

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)
    rounds = await service.list_sampling_rounds(model)

    round_responses = [
        SamplingRoundResponse(
            id=r.id,
            custom_model_id=r.custom_model_id,
            round_number=r.round_number,
            round_type=r.round_type,
            sampling_config=r.sampling_config,
            sample_count=r.sample_count,
            status=r.status,
            job_id=r.job_id,
            error_message=r.error_message,
            created_at=r.created_at,
            completed_at=r.completed_at,
            items=[],
        )
        for r in rounds
    ]

    return SamplingRoundListResponse(rounds=round_responses, total=len(round_responses))


@router.get(
    "/{model_id}/sampling-rounds/{round_id}",
    response_model=SamplingRoundResponse,
    summary="Get sampling round",
    description="Get a single sampling round with all its items (annotation status included)",
)
async def get_sampling_round(
    project_id: UUID,
    model_id: UUID,
    round_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> SamplingRoundResponse:
    """Get a single sampling round with items eagerly loaded.

    Returns the round with all SamplingRoundItems, including annotation review
    status and embedding metadata (recording_id, start_time, end_time) for
    each item.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        round_id: SamplingRound's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        SamplingRound with items populated

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model or round not found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    round_ = await service.get_sampling_round(round_id, model)
    if round_ is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sampling round not found",
        )

    item_responses = [
        SamplingRoundItemResponse(
            id=item.id,
            embedding_id=item.embedding_id,
            sample_type=item.sample_type,
            similarity=item.similarity,
            decision_distance=item.decision_distance,
            annotation_id=item.annotation_id,
            review_status=item.annotation.status.value if item.annotation else None,
            recording_id=item.embedding.recording_id if item.embedding else None,
            start_time=item.embedding.start_time if item.embedding else None,
            end_time=item.embedding.end_time if item.embedding else None,
        )
        for item in round_.items
    ]

    return SamplingRoundResponse(
        id=round_.id,
        custom_model_id=round_.custom_model_id,
        round_number=round_.round_number,
        round_type=round_.round_type,
        sampling_config=round_.sampling_config,
        sample_count=round_.sample_count,
        status=round_.status,
        job_id=round_.job_id,
        error_message=round_.error_message,
        created_at=round_.created_at,
        completed_at=round_.completed_at,
        items=item_responses,
    )


# ---------------------------------------------------------------------------
# Audit set endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{model_id}/audit-set",
    response_model=AuditSetGenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate audit set",
    description=(
        "Dispatch an async task to generate a score-stratified audit set for a "
        "TRAINED custom model. Returns 202 immediately."
    ),
)
async def create_audit_set(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> AuditSetGenerateResponse:
    """Start audit set generation for a trained custom model.

    Dispatches the generate_audit_set Celery task which will:
    1. Load the trained classifier from S3.
    2. Score all project embeddings (excluding already-labeled ones).
    3. Select a score-stratified sample.
    4. Create Annotation + AuditSetItem records.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        202 response with model_id and dispatched status

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        409: Model is not in TRAINED status or has no artifact
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    if model.status != CustomModelStatus.TRAINED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot generate audit set for model with status '{model.status}'. "
                "Only TRAINED models are supported."
            ),
        )

    if not model.model_artifact_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Model has no artifact. Please retrain before generating an audit set.",
        )

    await service.create_audit_set(model)

    return AuditSetGenerateResponse(model_id=model_id)


@router.get(
    "/{model_id}/audit-set",
    response_model=AuditSetListResponse,
    summary="List audit set items",
    description="List all audit set items for a custom model, ordered by predicted_proba descending.",
)
async def list_audit_set(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> AuditSetListResponse:
    """List all audit set items with annotation status and embedding metadata.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        List of audit set items with review status, start/end times

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
    """
    await check_project_access(project_id, current_user.id, db)
    await get_model_or_404(model_id, project_id, service)

    rows = await service.get_audit_items(model_id)

    item_responses = [
        AuditSetItemResponse(
            id=row.id,
            embedding_id=row.embedding_id,
            recording_id=row.recording_id,
            predicted_proba=row.predicted_proba,
            annotation_id=row.annotation_id,
            review_status=str(row.review_status),
            start_time=row.start_time,
            end_time=row.end_time,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return AuditSetListResponse(items=item_responses, total=len(item_responses))


@router.post(
    "/{model_id}/audit-set/evaluate",
    response_model=AuditSetEvaluateResponse,
    summary="Evaluate audit set",
    description=(
        "Compute classification metrics from all confirmed/rejected audit set "
        "annotations and persist them as model.audit_metrics."
    ),
)
async def evaluate_audit_set(
    project_id: UUID,
    model_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: CustomModelServiceDep,
) -> AuditSetEvaluateResponse:
    """Evaluate the model on reviewed audit set items.

    Collects all AuditSetItems whose annotation has been confirmed or rejected,
    computes classification metrics, and stores them in model.audit_metrics.

    Args:
        project_id: Project's UUID
        model_id: CustomModel's UUID
        current_user: Current authenticated user
        db: Database session
        service: CustomModelService instance

    Returns:
        Computed audit metrics

    Raises:
        401: Not authenticated
        403: Access denied
        404: Model not found
        422: Fewer than 2 reviewed audit items found
    """
    await check_project_access(project_id, current_user.id, db)
    model = await get_model_or_404(model_id, project_id, service)

    try:
        metrics = await service.evaluate_audit_set(model)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    return AuditSetEvaluateResponse(model_id=model_id, audit_metrics=metrics)
