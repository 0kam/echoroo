"""Cross-model evaluation API endpoints (spec 003-annotation, Phase A3).

Routes:

- ``POST /annotation-sets/{id}/evaluate`` — create a run and enqueue it.
- ``GET  /evaluation-runs`` — list runs for a given annotation set.
- ``GET  /evaluation-runs/{id}`` — return the grouped-by-model summary.
- ``DELETE /evaluation-runs/{id}`` — delete a run and its results.

All endpoints enforce project-level access via
:func:`echoroo.core.permissions.check_project_access` resolved through the
parent AnnotationSet's ``project_id``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from echoroo.core.actions import (
    EVALUATION_CREATE_ACTION,
    EVALUATION_RUN_DELETE_ACTION,
    EVALUATION_RUN_GET_ACTION,
    EVALUATION_RUN_LIST_ACTION,
    EVALUATION_RUNS_BY_SET_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.annotation_set import AnnotationSet
from echoroo.repositories.evaluation import (
    EvaluationResultRepository,
    EvaluationRunRepository,
)
from echoroo.schemas.evaluation import (
    EvaluationRunCreate,
    EvaluationRunListResponse,
    EvaluationRunResponse,
    EvaluationSummary,
)
from echoroo.services.evaluation import EvaluationService


def get_evaluation_service(db: DbSession) -> EvaluationService:
    """Provide a request-scoped :class:`EvaluationService`."""
    return EvaluationService(
        db=db,
        run_repo=EvaluationRunRepository(db),
        result_repo=EvaluationResultRepository(db),
    )


EvaluationServiceDep = Annotated[
    EvaluationService, Depends(get_evaluation_service),
]


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# POST and GET-list are mounted under the annotation-sets prefix so the URL
# matches the existing pattern used by 003-annotation contracts.
annotation_set_router = APIRouter(
    prefix="/annotation-sets", tags=["evaluation"],
)

# Direct evaluation-run routes live at /evaluation-runs/{id}.
run_router = APIRouter(prefix="/evaluation-runs", tags=["evaluation"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _annotation_set_project_id(
    db: DbSession, annotation_set_id: UUID,
) -> UUID:
    """Return the project ID of an annotation set or raise 404."""
    row = (
        await db.execute(
            select(AnnotationSet.project_id).where(
                AnnotationSet.id == annotation_set_id
            )
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation set not found",
        )
    project_id: UUID = row[0]
    return project_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# W2-3 PR-5: the public ``/api/v1/annotation-sets/*/evaluate`` and
# ``/api/v1/evaluation-runs*`` routes were unmounted in favour of the
# project-scoped ``/web-api/v1/projects/{project_id}/...`` evaluation BFF surface
# (``echoroo.api.web_v1.projects._annotation_sets``). The handlers below are left
# as plain importable functions (no ``@router`` decorators) because the BFF
# delegates to them via ``legacy_evaluation.{create_evaluation_run,
# list_evaluation_runs_for_set,get_evaluation_run,delete_evaluation_run}(...)``
# and reuses ``EvaluationServiceDep``. ``list_evaluation_runs`` (the unscoped
# ``GET /evaluation-runs`` alias) has no BFF twin and becomes a dead-but-
# importable helper, left in place for the W2-3 global-cleanup PR.
async def create_evaluation_run(
    annotation_set_id: UUID,
    payload: EvaluationRunCreate,
    request: Request,
    current_user: CurrentUser,
    service: EvaluationServiceDep,
    db: DbSession,
) -> EvaluationRunResponse:
    """Create a pending evaluation run and dispatch the worker task."""
    project_id = await _annotation_set_project_id(db, annotation_set_id)
    await gate_action(
        action=EVALUATION_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    refs = [ref.model_dump() for ref in payload.model_refs]
    return await service.evaluate_annotation_set(
        annotation_set_id=annotation_set_id,
        model_refs=refs,
        user_id=current_user.id,
    )


async def list_evaluation_runs_for_set(
    annotation_set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: EvaluationServiceDep,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EvaluationRunListResponse:
    """List evaluation runs for an annotation set (newest first)."""
    project_id = await _annotation_set_project_id(db, annotation_set_id)
    await gate_action(
        action=EVALUATION_RUNS_BY_SET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    items, total = await service.list_by_annotation_set(
        annotation_set_id, limit=limit, offset=offset,
    )
    return EvaluationRunListResponse(
        items=[EvaluationRunResponse.model_validate(r) for r in items],
        total=total,
    )


async def list_evaluation_runs(
    request: Request,
    current_user: CurrentUser,
    service: EvaluationServiceDep,
    db: DbSession,
    annotation_set_id: UUID = Query(
        ..., description="Filter by annotation set ID",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EvaluationRunListResponse:
    """List evaluation runs for a given annotation set."""
    project_id = await _annotation_set_project_id(db, annotation_set_id)
    await gate_action(
        action=EVALUATION_RUN_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    items, total = await service.list_by_annotation_set(
        annotation_set_id, limit=limit, offset=offset,
    )
    return EvaluationRunListResponse(
        items=[EvaluationRunResponse.model_validate(r) for r in items],
        total=total,
    )


async def get_evaluation_run(
    run_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: EvaluationServiceDep,
    db: DbSession,
) -> EvaluationSummary:
    """Return the grouped-by-model dashboard summary for a run."""
    run = await service.get_run(run_id)
    project_id = await _annotation_set_project_id(
        db, run.annotation_set_id,
    )
    await gate_action(
        action=EVALUATION_RUN_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_summary(run_id)


async def delete_evaluation_run(
    run_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: EvaluationServiceDep,
    db: DbSession,
) -> None:
    """Delete an evaluation run and its results."""
    run = await service.get_run(run_id)
    project_id = await _annotation_set_project_id(
        db, run.annotation_set_id,
    )
    await gate_action(
        action=EVALUATION_RUN_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.delete_run(run_id)


__all__ = ["annotation_set_router", "run_router"]
