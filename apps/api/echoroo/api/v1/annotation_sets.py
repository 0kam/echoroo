"""HTTP router for ground-truth AnnotationSet management (spec 003-annotation).

Endpoints follow ``specs/003-annotation/contracts/annotation-sets.yaml``.
Segment and TimeRangeAnnotation routes live in sibling modules.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from echoroo.core.database import DbSession
from echoroo.core.pagination import PaginationParams, make_pagination_dep
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import AnnotationSegmentStatus, AnnotationSetStatus
from echoroo.repositories.annotation_set import (
    AnnotationSegmentRepository,
    AnnotationSetRepository,
)
from echoroo.schemas.annotation_set import (
    AnnotationSegmentListResponse,
    AnnotationSetCreate,
    AnnotationSetDetailResponse,
    AnnotationSetListResponse,
    AnnotationSetSampleDispatchResponse,
    AnnotationSetUpdate,
    PaletteEntryResponse,
    PaletteItemCreate,
)
from echoroo.services.annotation_set import AnnotationSetService

router = APIRouter(prefix="/annotation-sets", tags=["Programmatic API — Annotation Sets"])


# ---------------------------------------------------------------------------
# Dependency factory
# ---------------------------------------------------------------------------


def get_annotation_set_service(db: DbSession) -> AnnotationSetService:
    return AnnotationSetService(
        set_repo=AnnotationSetRepository(db),
        segment_repo=AnnotationSegmentRepository(db),
    )


AnnotationSetServiceDep = Annotated[
    AnnotationSetService, Depends(get_annotation_set_service)
]


# Pagination dependencies: different endpoints have different bounds, so we
# build dedicated dependencies via :func:`make_pagination_dep` to preserve the
# existing API contract (Query defaults and upper limits).
AnnotationSetListPaginationDep = Annotated[
    PaginationParams,
    Depends(make_pagination_dep(default_page_size=20, max_page_size=200)),
]
AnnotationSegmentListPaginationDep = Annotated[
    PaginationParams,
    Depends(make_pagination_dep(default_page_size=50, max_page_size=500)),
]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


# W2-3 PR-6: the browser-facing ``/api/v1/annotation-sets/*`` CRUD + palette +
# nested-segments routes were unmounted in favour of the project-scoped
# ``/web-api/v1/projects/{project_id}/annotation-sets/*`` BFF surface
# (``echoroo.api.web_v1.projects._annotation_sets``). The eight handlers below
# are left as plain importable functions (no ``@router`` decorators) because the
# BFF delegates to them via ``legacy_annotation_sets.<fn>(...)`` and reuses
# ``AnnotationSetServiceDep``. The ``dispatch_sampling`` route (POST
# ``/{set_id}/sample``) is KEPT mounted — it has no BFF twin yet — so this is a
# MIXED router: ``router``/``include_router`` stay in place.
async def list_annotation_sets(
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
    pagination: AnnotationSetListPaginationDep,
    project_id: UUID = Query(..., description="Owning project ID"),
    dataset_id: UUID | None = Query(default=None),
    status_filter: AnnotationSetStatus | None = Query(default=None, alias="status"),
) -> AnnotationSetListResponse:
    return await service.list(
        project_id=project_id,
        dataset_id=dataset_id,
        status_filter=status_filter,
        page=pagination.page,
        page_size=pagination.page_size,
    )


async def create_annotation_set(
    request: AnnotationSetCreate,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    return await service.create(user_id=current_user.id, request=request)


async def get_annotation_set(
    set_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
    locale: str = Query(
        default="en",
        description="Display locale for palette common names (e.g. en, ja).",
    ),
) -> AnnotationSetDetailResponse:
    return await service.get_detail(set_id, locale=locale)


async def update_annotation_set(
    set_id: UUID,
    request: AnnotationSetUpdate,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    return await service.update(set_id, request)


async def delete_annotation_set(
    set_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> None:
    await service.delete(set_id)


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


@router.post(
    "/{set_id}/sample",
    response_model=AnnotationSetSampleDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dispatch the sampling job",
)
async def dispatch_sampling(
    set_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> AnnotationSetSampleDispatchResponse:
    return await service.dispatch_sample(set_id)


# ---------------------------------------------------------------------------
# Segments nested under a set
# ---------------------------------------------------------------------------


async def list_set_segments(
    set_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
    pagination: AnnotationSegmentListPaginationDep,
    status_filter: AnnotationSegmentStatus | None = Query(default=None, alias="status"),
    is_empty: bool | None = Query(default=None),
) -> AnnotationSegmentListResponse:
    return await service.list_segments(
        set_id,
        status_filter=status_filter,
        is_empty=is_empty,
        page=pagination.page,
        page_size=pagination.page_size,
    )


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


async def add_palette_species(
    set_id: UUID,
    request: PaletteItemCreate,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> PaletteEntryResponse:
    return await service.add_palette(set_id, request)


async def remove_palette_species(
    set_id: UUID,
    species_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> None:
    await service.remove_palette(set_id, species_id)
