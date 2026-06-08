"""HTTP router for individual :class:`AnnotationSegment` operations.

Endpoints follow ``specs/003-annotation/contracts/segments.yaml``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.annotation_set import (
    AnnotationSegmentRepository,
    AnnotationSetRepository,
    TimeRangeAnnotationRepository,
)
from echoroo.schemas.annotation_set import (
    AnnotationNoteCreate,
    AnnotationNoteResponse,
    AnnotationSegmentDetailResponse,
    AnnotationSegmentStatusUpdate,
    TimeRangeAnnotationCreate,
    TimeRangeAnnotationResponse,
)
from echoroo.services.annotation_segment import AnnotationSegmentService
from echoroo.services.annotation_set import AnnotationSetService

router = APIRouter(prefix="/segments", tags=["annotation-segments"])


def get_segment_service(db: DbSession) -> AnnotationSegmentService:
    set_repo = AnnotationSetRepository(db)
    segment_repo = AnnotationSegmentRepository(db)
    annotation_repo = TimeRangeAnnotationRepository(db)
    set_service = AnnotationSetService(set_repo=set_repo, segment_repo=segment_repo)
    return AnnotationSegmentService(
        segment_repo=segment_repo,
        annotation_repo=annotation_repo,
        set_service=set_service,
    )


SegmentServiceDep = Annotated[AnnotationSegmentService, Depends(get_segment_service)]


@router.get(
    "/{segment_id}",
    response_model=AnnotationSegmentDetailResponse,
    summary="Get segment detail with annotations and notes",
)
async def get_segment(
    segment_id: UUID,
    current_user: CurrentUser,
    service: SegmentServiceDep,
) -> AnnotationSegmentDetailResponse:
    return await service.get_detail(segment_id)


@router.patch(
    "/{segment_id}",
    response_model=AnnotationSegmentDetailResponse,
    summary="Update segment lifecycle (status, is_empty)",
)
async def update_segment(
    segment_id: UUID,
    request: AnnotationSegmentStatusUpdate,
    current_user: CurrentUser,
    service: SegmentServiceDep,
) -> AnnotationSegmentDetailResponse:
    return await service.update(
        segment_id, user_id=current_user.id, request=request,
    )


@router.post(
    "/{segment_id}/annotations",
    response_model=TimeRangeAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a TimeRangeAnnotation inside a segment",
)
async def create_annotation(
    segment_id: UUID,
    request: TimeRangeAnnotationCreate,
    current_user: CurrentUser,
    service: SegmentServiceDep,
    project_id: UUID | None = None,
) -> TimeRangeAnnotationResponse:
    return await service.create_annotation(
        segment_id,
        user_id=current_user.id,
        request=request,
        project_id=project_id,
    )


@router.post(
    "/{segment_id}/notes",
    response_model=AnnotationNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a note to a segment",
)
async def create_segment_note(
    segment_id: UUID,
    request: AnnotationNoteCreate,
    current_user: CurrentUser,
    service: SegmentServiceDep,
) -> AnnotationNoteResponse:
    return await service.create_note(
        segment_id, user_id=current_user.id, request=request,
    )
