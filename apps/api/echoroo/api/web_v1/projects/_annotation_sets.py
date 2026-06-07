"""Project annotation-set BFF adapters (spec/009 PR 4).

Spec/009 PR 4 moves the spec/003-annotation ground-truth surface
(``AnnotationSet`` + ``AnnotationSegment`` + ``TimeRangeAnnotation`` +
``EvaluationRun``) from the project-less ``/api/v1/annotation-sets`` /
``/api/v1/segments`` / ``/api/v1/annotations`` / ``/api/v1/evaluation-runs``
mounts to a project-scoped ``/web-api/v1/projects/{project_id}/...``
surface. The legacy handlers continue to own service orchestration; the
BFF layer is a thin adapter that:

* lands the request on the cookie + CSRF session boundary, and
* fires :func:`gate_action` with a project-scoped Action before
  delegating to the legacy handler.

Spec/003-annotation pre-dates the spec/006 Action registry, so the
underlying handlers are still unguarded (entries 40-48, 138-141, 159-161
of ``scripts/allowlists/permission_guard_allowlist.txt``). The BFF
adapter mirrors that decision — no annotation-set-specific Actions
exist today (``ANNOTATION_SET_*`` etc. are *not* registered), so the
adapter wires the broad ``ANNOTATION_BATCH_TAG_ACTION`` for write
mutations and ``ANNOTATION_CLIP_GET_ACTION`` for reads (both already in
use for the spec/009 PR 2.5 annotation mutations); for evaluation we
reuse the dedicated ``EVALUATION_*`` Actions; for note creation we
reuse ``ANNOTATION_NOTE_CREATE_ACTION`` and for review we reuse
``ANNOTATION_REVIEW_ACTION``. This keeps the BFF surface auditable and
the permission decision lands in the canonical matrix.

Endpoints (18):

AnnotationSet CRUD
* GET    ``/{pid}/annotation-sets``                   → ``ANNOTATION_CLIP_GET_ACTION``
* POST   ``/{pid}/annotation-sets``                   → ``ANNOTATION_BATCH_TAG_ACTION``
* GET    ``/{pid}/annotation-sets/{set_id}``          → ``ANNOTATION_CLIP_GET_ACTION``
* PATCH  ``/{pid}/annotation-sets/{set_id}``          → ``ANNOTATION_BATCH_TAG_ACTION``
* DELETE ``/{pid}/annotation-sets/{set_id}``          → ``ANNOTATION_BATCH_TAG_ACTION``

Palette
* POST   ``/{pid}/annotation-sets/{set_id}/palette``                  → ``ANNOTATION_BATCH_TAG_ACTION``
* DELETE ``/{pid}/annotation-sets/{set_id}/palette/{species_id}``     → ``ANNOTATION_BATCH_TAG_ACTION``

Segments
* GET    ``/{pid}/annotation-sets/{set_id}/segments``                 → ``ANNOTATION_CLIP_GET_ACTION``
* GET    ``/{pid}/segments/{segment_id}``                             → ``ANNOTATION_CLIP_GET_ACTION``
* PATCH  ``/{pid}/segments/{segment_id}``                             → ``ANNOTATION_BATCH_TAG_ACTION``
* POST   ``/{pid}/segments/{segment_id}/annotations``                 → ``ANNOTATION_BATCH_TAG_ACTION``
* POST   ``/{pid}/segments/{segment_id}/notes``                       → ``ANNOTATION_NOTE_CREATE_ACTION``

TimeRangeAnnotation
* PATCH  ``/{pid}/annotations/{annotation_id}``                       → ``ANNOTATION_BATCH_TAG_ACTION``
* DELETE ``/{pid}/annotations/{annotation_id}``                       → ``ANNOTATION_BATCH_TAG_ACTION``
* POST   ``/{pid}/annotations/{annotation_id}/notes``                 → ``ANNOTATION_NOTE_CREATE_ACTION``

Evaluation
* POST   ``/{pid}/annotation-sets/{set_id}/evaluate``                 → ``EVALUATION_CREATE_ACTION``
* GET    ``/{pid}/annotation-sets/{set_id}/evaluation-runs``          → ``EVALUATION_RUNS_BY_SET_ACTION``
* GET    ``/{pid}/evaluation-runs/{run_id}``                          → ``EVALUATION_RUN_GET_ACTION``
* DELETE ``/{pid}/evaluation-runs/{run_id}``                          → ``EVALUATION_RUN_DELETE_ACTION``

(``GET /evaluation-runs?annotation_set_id=...`` from the legacy
``run_router`` is intentionally not mirrored; the frontend client uses
the annotation-set-scoped list path above.)

Permission guard allowlist
--------------------------

No new entries required. Although none of the legacy handlers fire
``gate_action`` themselves, every BFF adapter declared in this module
DOES fire ``gate_action`` before delegating, so
``scripts/lint_permission_guard.py`` is satisfied.

Response filter allowlist
-------------------------

None of the legacy / BFF response models in this module name
``Recording`` / ``Detection`` / ``Site`` (they expose
``AnnotationSet`` / ``AnnotationSegment`` / ``TimeRangeAnnotation`` /
``EvaluationRun`` shapes), so no allowlist entry is required.

Route order
-----------

The ``/segments/{segment_id}`` and ``/annotations/{annotation_id}``
families collide with the ``/annotation-sets`` / ``/evaluation-runs``
literals only by accident of path tokens, not by route shape, so the
declaration order here mirrors the legacy router declarations to keep
``app.openapi()`` deterministic. ``literal`` sub-paths under each
``{set_id}`` family (``segments`` / ``palette`` / ``evaluate`` /
``evaluation-runs``) are declared adjacent to their parent for the
same reason.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from echoroo.api.v1 import annotation_sets as legacy_annotation_sets
from echoroo.api.v1 import evaluation as legacy_evaluation
from echoroo.api.v1 import segments as legacy_segments
from echoroo.api.v1 import time_range_annotations as legacy_time_range_annotations
from echoroo.core.actions import (
    ANNOTATION_BATCH_TAG_ACTION,
    ANNOTATION_CLIP_GET_ACTION,
    ANNOTATION_NOTE_CREATE_ACTION,
    EVALUATION_CREATE_ACTION,
    EVALUATION_RUN_DELETE_ACTION,
    EVALUATION_RUN_GET_ACTION,
    EVALUATION_RUNS_BY_SET_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.pagination import PaginationParams
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import AnnotationSegmentStatus, AnnotationSetStatus
from echoroo.schemas.annotation_set import (
    AnnotationNoteCreate,
    AnnotationNoteResponse,
    AnnotationSegmentDetailResponse,
    AnnotationSegmentListResponse,
    AnnotationSegmentStatusUpdate,
    AnnotationSetCreate,
    AnnotationSetDetailResponse,
    AnnotationSetListResponse,
    AnnotationSetUpdate,
    PaletteEntryResponse,
    PaletteItemCreate,
    TimeRangeAnnotationCreate,
    TimeRangeAnnotationResponse,
    TimeRangeAnnotationUpdate,
)
from echoroo.schemas.evaluation import (
    EvaluationRunCreate,
    EvaluationRunListResponse,
    EvaluationRunResponse,
    EvaluationSummary,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# AnnotationSet CRUD
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/annotation-sets",
    response_model=AnnotationSetListResponse,
    summary="List annotation sets",
    description="BFF adapter for the legacy annotation-set list endpoint.",
)
async def list_annotation_sets(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
    dataset_id: UUID | None = Query(default=None),
    status_filter: AnnotationSetStatus | None = Query(
        default=None, alias="status"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> AnnotationSetListResponse:
    """Delegate annotation-set list to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    pagination = PaginationParams(page=page, page_size=page_size)
    return await legacy_annotation_sets.list_annotation_sets(
        current_user=current_user,
        service=service,
        pagination=pagination,
        project_id=project_id,
        dataset_id=dataset_id,
        status_filter=status_filter,
    )


@router.post(
    "/{project_id}/annotation-sets",
    response_model=AnnotationSetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation set",
    description="BFF adapter for the legacy annotation-set create endpoint.",
)
async def create_annotation_set(
    project_id: UUID,
    request: AnnotationSetCreate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    """Delegate annotation-set create to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_sets.create_annotation_set(
        request=request,
        current_user=current_user,
        service=service,
    )


@router.get(
    "/{project_id}/annotation-sets/{set_id}",
    response_model=AnnotationSetDetailResponse,
    summary="Get annotation set detail",
    description="BFF adapter for the legacy annotation-set detail endpoint.",
)
async def get_annotation_set(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
    locale: str = "en",
) -> AnnotationSetDetailResponse:
    """Delegate annotation-set detail to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_sets.get_annotation_set(
        set_id=set_id,
        current_user=current_user,
        service=service,
        locale=locale,
    )


@router.patch(
    "/{project_id}/annotation-sets/{set_id}",
    response_model=AnnotationSetDetailResponse,
    summary="Update annotation set",
    description="BFF adapter for the legacy annotation-set update endpoint.",
)
async def update_annotation_set(
    project_id: UUID,
    set_id: UUID,
    request: AnnotationSetUpdate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    """Delegate annotation-set update to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_sets.update_annotation_set(
        set_id=set_id,
        request=request,
        current_user=current_user,
        service=service,
    )


@router.delete(
    "/{project_id}/annotation-sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete annotation set",
    description="BFF adapter for the legacy annotation-set delete endpoint.",
)
async def delete_annotation_set(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
) -> None:
    """Delegate annotation-set delete to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_annotation_sets.delete_annotation_set(
        set_id=set_id,
        current_user=current_user,
        service=service,
    )


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/annotation-sets/{set_id}/palette",
    response_model=PaletteEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add species to palette",
    description="BFF adapter for the legacy add-palette endpoint.",
)
async def add_palette_species(
    project_id: UUID,
    set_id: UUID,
    request: PaletteItemCreate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
) -> PaletteEntryResponse:
    """Delegate add-palette to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_sets.add_palette_species(
        set_id=set_id,
        request=request,
        current_user=current_user,
        service=service,
    )


@router.delete(
    "/{project_id}/annotation-sets/{set_id}/palette/{species_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove species from palette",
    description="BFF adapter for the legacy remove-palette endpoint.",
)
async def remove_palette_species(
    project_id: UUID,
    set_id: UUID,
    species_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
) -> None:
    """Delegate remove-palette to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_annotation_sets.remove_palette_species(
        set_id=set_id,
        species_id=species_id,
        current_user=current_user,
        service=service,
    )


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/annotation-sets/{set_id}/segments",
    response_model=AnnotationSegmentListResponse,
    summary="List segments in a set",
    description="BFF adapter for the legacy set-segment list endpoint.",
)
async def list_set_segments(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_annotation_sets.AnnotationSetServiceDep,
    status_filter: AnnotationSegmentStatus | None = Query(
        default=None, alias="status"
    ),
    is_empty: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> AnnotationSegmentListResponse:
    """Delegate set-segment list to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    pagination = PaginationParams(page=page, page_size=page_size)
    return await legacy_annotation_sets.list_set_segments(
        set_id=set_id,
        current_user=current_user,
        service=service,
        pagination=pagination,
        status_filter=status_filter,
        is_empty=is_empty,
    )


@router.get(
    "/{project_id}/segments/{segment_id}",
    response_model=AnnotationSegmentDetailResponse,
    summary="Get segment detail",
    description="BFF adapter for the legacy segment detail endpoint.",
)
async def get_segment(
    project_id: UUID,
    segment_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_segments.SegmentServiceDep,
) -> AnnotationSegmentDetailResponse:
    """Delegate segment detail to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_segments.get_segment(
        segment_id=segment_id,
        current_user=current_user,
        service=service,
    )


@router.patch(
    "/{project_id}/segments/{segment_id}",
    response_model=AnnotationSegmentDetailResponse,
    summary="Update segment lifecycle",
    description="BFF adapter for the legacy segment update endpoint.",
)
async def update_segment(
    project_id: UUID,
    segment_id: UUID,
    request: AnnotationSegmentStatusUpdate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_segments.SegmentServiceDep,
) -> AnnotationSegmentDetailResponse:
    """Delegate segment update to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_segments.update_segment(
        segment_id=segment_id,
        request=request,
        current_user=current_user,
        service=service,
    )


@router.post(
    "/{project_id}/segments/{segment_id}/annotations",
    response_model=TimeRangeAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation in segment",
    description="BFF adapter for the legacy create-annotation endpoint.",
)
async def create_annotation(
    project_id: UUID,
    segment_id: UUID,
    request: TimeRangeAnnotationCreate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_segments.SegmentServiceDep,
) -> TimeRangeAnnotationResponse:
    """Delegate create-annotation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_segments.create_annotation(
        segment_id=segment_id,
        request=request,
        current_user=current_user,
        service=service,
    )


@router.post(
    "/{project_id}/segments/{segment_id}/notes",
    response_model=AnnotationNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach note to segment",
    description="BFF adapter for the legacy segment note endpoint.",
)
async def create_segment_note(
    project_id: UUID,
    segment_id: UUID,
    request: AnnotationNoteCreate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_segments.SegmentServiceDep,
) -> AnnotationNoteResponse:
    """Delegate segment note creation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_NOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_segments.create_segment_note(
        segment_id=segment_id,
        request=request,
        current_user=current_user,
        service=service,
    )


# ---------------------------------------------------------------------------
# TimeRangeAnnotation
# ---------------------------------------------------------------------------


@router.patch(
    "/{project_id}/annotations/{annotation_id}",
    response_model=TimeRangeAnnotationResponse,
    summary="Update annotation",
    description="BFF adapter for the legacy annotation update endpoint.",
)
async def update_annotation(
    project_id: UUID,
    annotation_id: UUID,
    request: TimeRangeAnnotationUpdate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_time_range_annotations.AnnotationServiceDep,
) -> TimeRangeAnnotationResponse:
    """Delegate annotation update to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_time_range_annotations.update_annotation(
        annotation_id=annotation_id,
        request=request,
        current_user=current_user,
        service=service,
    )


@router.delete(
    "/{project_id}/annotations/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete annotation",
    description="BFF adapter for the legacy annotation delete endpoint.",
)
async def delete_annotation(
    project_id: UUID,
    annotation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_time_range_annotations.AnnotationServiceDep,
) -> None:
    """Delegate annotation delete to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_time_range_annotations.delete_annotation(
        annotation_id=annotation_id,
        current_user=current_user,
        service=service,
    )


@router.post(
    "/{project_id}/annotations/{annotation_id}/notes",
    response_model=AnnotationNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach note to annotation",
    description="BFF adapter for the legacy annotation note endpoint.",
)
async def create_annotation_note(
    project_id: UUID,
    annotation_id: UUID,
    request: AnnotationNoteCreate,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_time_range_annotations.AnnotationServiceDep,
) -> AnnotationNoteResponse:
    """Delegate annotation note creation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_NOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_time_range_annotations.create_annotation_note(
        annotation_id=annotation_id,
        request=request,
        current_user=current_user,
        service=service,
    )


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/annotation-sets/{set_id}/evaluate",
    response_model=EvaluationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create evaluation run",
    description="BFF adapter for the legacy evaluation create endpoint.",
)
async def evaluate_annotation_set(
    project_id: UUID,
    set_id: UUID,
    payload: EvaluationRunCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_evaluation.EvaluationServiceDep,
) -> EvaluationRunResponse:
    """Delegate evaluation creation to the legacy handler."""
    await gate_action(
        action=EVALUATION_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_evaluation.create_evaluation_run(
        annotation_set_id=set_id,
        payload=payload,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/annotation-sets/{set_id}/evaluation-runs",
    response_model=EvaluationRunListResponse,
    summary="List evaluation runs for set",
    description="BFF adapter for the legacy evaluation-by-set list endpoint.",
)
async def list_evaluation_runs(
    project_id: UUID,
    set_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_evaluation.EvaluationServiceDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EvaluationRunListResponse:
    """Delegate evaluation-by-set list to the legacy handler."""
    await gate_action(
        action=EVALUATION_RUNS_BY_SET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_evaluation.list_evaluation_runs_for_set(
        annotation_set_id=set_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{project_id}/evaluation-runs/{run_id}",
    response_model=EvaluationSummary,
    summary="Get evaluation run summary",
    description="BFF adapter for the legacy evaluation summary endpoint.",
)
async def get_evaluation_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_evaluation.EvaluationServiceDep,
) -> EvaluationSummary:
    """Delegate evaluation summary to the legacy handler."""
    await gate_action(
        action=EVALUATION_RUN_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_evaluation.get_evaluation_run(
        run_id=run_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/evaluation-runs/{run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete evaluation run",
    description="BFF adapter for the legacy evaluation delete endpoint.",
)
async def delete_evaluation_run(
    project_id: UUID,
    run_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: legacy_evaluation.EvaluationServiceDep,
) -> None:
    """Delegate evaluation delete to the legacy handler."""
    await gate_action(
        action=EVALUATION_RUN_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_evaluation.delete_evaluation_run(
        run_id=run_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
