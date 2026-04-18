"""HTTP router for ground-truth AnnotationSet management (spec 003-annotation).

Endpoints follow ``specs/003-annotation/contracts/annotation-sets.yaml``.
Segment and TimeRangeAnnotation routes live in sibling modules.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from echoroo.core.database import DbSession
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

router = APIRouter(prefix="/annotation-sets", tags=["annotation-sets"])


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


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=AnnotationSetListResponse,
    summary="List annotation sets",
)
async def list_annotation_sets(
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
    project_id: UUID = Query(..., description="Owning project ID"),
    dataset_id: UUID | None = Query(default=None),
    status_filter: AnnotationSetStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
) -> AnnotationSetListResponse:
    return await service.list(
        project_id=project_id,
        dataset_id=dataset_id,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=AnnotationSetDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an annotation set",
)
async def create_annotation_set(
    request: AnnotationSetCreate,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    return await service.create(user_id=current_user.id, request=request)


@router.get(
    "/{set_id}",
    response_model=AnnotationSetDetailResponse,
    summary="Get annotation set detail",
)
async def get_annotation_set(
    set_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    return await service.get_detail(set_id)


@router.patch(
    "/{set_id}",
    response_model=AnnotationSetDetailResponse,
    summary="Update annotation set metadata",
)
async def update_annotation_set(
    set_id: UUID,
    request: AnnotationSetUpdate,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> AnnotationSetDetailResponse:
    return await service.update(set_id, request)


@router.delete(
    "/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an annotation set",
)
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


@router.get(
    "/{set_id}/segments",
    response_model=AnnotationSegmentListResponse,
    summary="List segments in a set",
)
async def list_set_segments(
    set_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
    status_filter: AnnotationSegmentStatus | None = Query(default=None, alias="status"),
    is_empty: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
) -> AnnotationSegmentListResponse:
    return await service.list_segments(
        set_id,
        status_filter=status_filter,
        is_empty=is_empty,
        page=page,
        page_size=page_size,
    )


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


@router.post(
    "/{set_id}/palette",
    response_model=PaletteEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a species to the palette",
)
async def add_palette_species(
    set_id: UUID,
    request: PaletteItemCreate,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> PaletteEntryResponse:
    return await service.add_palette(set_id, request)


@router.delete(
    "/{set_id}/palette/{species_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a species from the palette",
)
async def remove_palette_species(
    set_id: UUID,
    species_id: UUID,
    current_user: CurrentUser,
    service: AnnotationSetServiceDep,
) -> None:
    await service.remove_palette(set_id, species_id)
