"""Project custom-model BFF adapters (spec/009 PR 3b).

Spec/009 PR 3b moves the entire custom-SVM-classifier surface from
``/api/v1`` to ``/web-api/v1``. The legacy
``/api/v1/custom_models.py`` handlers continue to own service
orchestration (Celery dispatch, S3 artifact lookup, seed/active-learning
sampling, model→dataset apply, and dataset-context join for
detection-run listing). The BFF layer is a thin adapter that:

* lands the request on the cookie + CSRF session boundary, and
* re-uses :func:`gate_action` on each route so the permission decision
  fires under the BFF actor (``actor_kind == "session"``) before the
  legacy handler runs its own ``gate_action`` (idempotent — the gate is
  safe to call twice; the per-request decision cache short-circuits the
  second call).

Endpoints (13):

* GET    ``/{pid}/custom-models``                              → ``CUSTOM_MODEL_LIST_ACTION``
* POST   ``/{pid}/custom-models``                              → ``CUSTOM_MODEL_TRAIN_ACTION``
* GET    ``/{pid}/custom-models/{mid}``                        → ``CUSTOM_MODEL_GET_ACTION``
* PATCH  ``/{pid}/custom-models/{mid}``                        → ``CUSTOM_MODEL_TRAIN_ACTION``
* DELETE ``/{pid}/custom-models/{mid}``                        → ``CUSTOM_MODEL_DELETE_ACTION``
* POST   ``/{pid}/custom-models/{mid}/train``                  → ``CUSTOM_MODEL_TRAIN_ACTION``
* GET    ``/{pid}/custom-models/{mid}/status``                 → ``CUSTOM_MODEL_GET_ACTION``
* POST   ``/{pid}/custom-models/{mid}/apply``                  → ``CUSTOM_MODEL_TRAIN_ACTION``
* GET    ``/{pid}/custom-models/{mid}/detection-runs``         → ``CUSTOM_MODEL_GET_ACTION``
* POST   ``/{pid}/custom-models/{mid}/seed-samples``           → ``CUSTOM_MODEL_TRAIN_ACTION``
* POST   ``/{pid}/custom-models/{mid}/suggest-samples``        → ``CUSTOM_MODEL_TRAIN_ACTION``
* GET    ``/{pid}/custom-models/{mid}/sampling-rounds``        → ``CUSTOM_MODEL_GET_ACTION``
* GET    ``/{pid}/custom-models/{mid}/sampling-rounds/{rid}``  → ``CUSTOM_MODEL_GET_ACTION``

All 13 legacy handlers are already centrally gated through
:func:`gate_action` (see ``apps/api/echoroo/api/v1/custom_models.py``),
so no entry is required in
``scripts/allowlists/permission_guard_allowlist.txt``. None of the
response models name ``Recording`` / ``Detection`` / ``Site`` (custom
models expose ML metadata and detection-run summaries only — never the
underlying ``Detection`` record), so no entry is required in
``scripts/allowlists/response_filter_allowlist.txt``.

NOTE: route order — ``status``, ``apply``, ``train``, ``seed-samples``,
``suggest-samples``, ``detection-runs``, ``sampling-rounds`` are
declared BEFORE the bare ``/{model_id}`` / ``/{model_id}/...`` family
so the literal segments win against the UUID-shaped ``{model_id}``
pattern. The path layout intentionally mirrors the legacy router order
in ``api/v1/custom_models.py``.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from echoroo.api.v1 import custom_models as legacy_custom_models
from echoroo.core.actions import (
    CUSTOM_MODEL_DELETE_ACTION,
    CUSTOM_MODEL_GET_ACTION,
    CUSTOM_MODEL_LIST_ACTION,
    CUSTOM_MODEL_TRAIN_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.custom_model import (
    CustomModelApplyResponse,
    CustomModelCreate,
    CustomModelDetectionRunListResponse,
    CustomModelListResponse,
    CustomModelResponse,
    CustomModelTrainRequest,
    CustomModelUpdate,
)
from echoroo.schemas.sampling import (
    SamplingRoundListResponse,
    SamplingRoundResponse,
)

router = APIRouter()


@router.get(
    "/{project_id}/custom-models",
    response_model=CustomModelListResponse,
    summary="List custom models",
    description="BFF adapter for the legacy custom-model list endpoint.",
)
async def list_custom_models(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
    limit: int = 50,
    offset: int = 0,
    tag_id: UUID | None = None,
    search_session_id: UUID | None = Query(
        default=None, description="Filter by source search session"
    ),
) -> CustomModelListResponse:
    """Delegate custom-model list to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.list_custom_models(
        project_id=project_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
        limit=limit,
        offset=offset,
        tag_id=tag_id,
        search_session_id=search_session_id,
    )


@router.post(
    "/{project_id}/custom-models",
    response_model=CustomModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create custom model",
    description="BFF adapter for the legacy custom-model create endpoint.",
)
async def create_custom_model(
    project_id: UUID,
    request_body: CustomModelCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> CustomModelResponse:
    """Delegate custom-model create to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_TRAIN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.create_custom_model(
        project_id=project_id,
        request_body=request_body,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


# ---------------------------------------------------------------------------
# Literal sub-path routes — declared BEFORE the bare ``/{model_id}`` family
# so FastAPI resolves ``status`` / ``apply`` / ``train`` / ``seed-samples``
# / ``suggest-samples`` / ``detection-runs`` / ``sampling-rounds`` against
# the literal segment instead of the ``{model_id}`` UUID pattern.
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/custom-models/{model_id}/train",
    response_model=CustomModelResponse,
    summary="Start model training",
    description="BFF adapter for the legacy custom-model train endpoint.",
)
async def train_custom_model(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
    request_body: CustomModelTrainRequest | None = None,
) -> CustomModelResponse:
    """Delegate custom-model train to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_TRAIN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.train_custom_model(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
        request_body=request_body,
    )


@router.get(
    "/{project_id}/custom-models/{model_id}/status",
    response_model=CustomModelResponse,
    summary="Get training status",
    description="BFF adapter for the legacy custom-model status polling endpoint.",
)
async def get_custom_model_status(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> CustomModelResponse:
    """Delegate custom-model status to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.get_custom_model_status(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.post(
    "/{project_id}/custom-models/{model_id}/apply",
    response_model=CustomModelApplyResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Apply custom model to dataset",
    description="BFF adapter for the legacy custom-model apply endpoint.",
)
async def apply_custom_model(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
    dataset_id: UUID = Query(..., description="Dataset UUID to apply the model to"),
    threshold: float = Query(
        0.5, ge=0.0, le=1.0, description="Confidence threshold (0.0-1.0)"
    ),
) -> CustomModelApplyResponse:
    """Delegate custom-model apply to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_TRAIN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.apply_custom_model(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
        dataset_id=dataset_id,
        threshold=threshold,
    )


@router.get(
    "/{project_id}/custom-models/{model_id}/detection-runs",
    response_model=CustomModelDetectionRunListResponse,
    summary="List recent detection runs for a custom model",
    description="BFF adapter for the legacy custom-model detection-run list endpoint.",
)
async def list_custom_model_detection_runs(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
    limit: int = Query(5, ge=1, le=50, description="Maximum number of runs to return"),
) -> CustomModelDetectionRunListResponse:
    """Delegate custom-model detection-run list to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.list_custom_model_detection_runs(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
        limit=limit,
    )


@router.post(
    "/{project_id}/custom-models/{model_id}/seed-samples",
    response_model=SamplingRoundResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start seed sampling",
    description="BFF adapter for the legacy custom-model seed-sample endpoint.",
)
async def create_seed_samples(
    project_id: UUID,
    model_id: UUID,
    body: legacy_custom_models.SeedSamplingBody,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> SamplingRoundResponse:
    """Delegate seed-sample creation to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_TRAIN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.create_seed_samples(
        project_id=project_id,
        model_id=model_id,
        body=body,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.post(
    "/{project_id}/custom-models/{model_id}/suggest-samples",
    response_model=SamplingRoundResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Suggest active learning samples",
    description="BFF adapter for the legacy custom-model active-learning endpoint.",
)
async def suggest_next_samples(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> SamplingRoundResponse:
    """Delegate active-learning sample suggestion to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_TRAIN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.suggest_next_samples(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.get(
    "/{project_id}/custom-models/{model_id}/sampling-rounds",
    response_model=SamplingRoundListResponse,
    summary="List sampling rounds",
    description="BFF adapter for the legacy custom-model sampling-round list endpoint.",
)
async def list_sampling_rounds(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> SamplingRoundListResponse:
    """Delegate sampling-round list to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.list_sampling_rounds(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.get(
    "/{project_id}/custom-models/{model_id}/sampling-rounds/{round_id}",
    response_model=SamplingRoundResponse,
    summary="Get sampling round",
    description="BFF adapter for the legacy custom-model sampling-round detail endpoint.",
)
async def get_sampling_round(
    project_id: UUID,
    model_id: UUID,
    round_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> SamplingRoundResponse:
    """Delegate sampling-round detail to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.get_sampling_round(
        project_id=project_id,
        model_id=model_id,
        round_id=round_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


# ---------------------------------------------------------------------------
# Bare ``/{model_id}`` routes — declared LAST so the literal sub-paths above
# (status, apply, train, seed-samples, suggest-samples, detection-runs,
# sampling-rounds) take precedence.
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/custom-models/{model_id}",
    response_model=CustomModelResponse,
    summary="Get custom model",
    description="BFF adapter for the legacy custom-model detail endpoint.",
)
async def get_custom_model(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> CustomModelResponse:
    """Delegate custom-model detail to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.get_custom_model(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.patch(
    "/{project_id}/custom-models/{model_id}",
    response_model=CustomModelResponse,
    summary="Update custom model",
    description="BFF adapter for the legacy custom-model update endpoint.",
)
async def update_custom_model(
    project_id: UUID,
    model_id: UUID,
    request_body: CustomModelUpdate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> CustomModelResponse:
    """Delegate custom-model update to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_TRAIN_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_custom_models.update_custom_model(
        project_id=project_id,
        model_id=model_id,
        request_body=request_body,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )


@router.delete(
    "/{project_id}/custom-models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete custom model",
    description="BFF adapter for the legacy custom-model delete endpoint.",
)
async def delete_custom_model(
    project_id: UUID,
    model_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_custom_models.CustomModelServiceDep,
) -> None:
    """Delegate custom-model delete to the legacy handler."""
    await gate_action(
        action=CUSTOM_MODEL_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_custom_models.delete_custom_model(
        project_id=project_id,
        model_id=model_id,
        request=request,
        current_user=current_user,
        db=db,
        service=service,
    )
