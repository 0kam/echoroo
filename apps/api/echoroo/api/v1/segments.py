"""HTTP router for individual :class:`AnnotationSegment` operations.

Endpoints follow ``specs/003-annotation/contracts/segments.yaml``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

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


# W2-3 PR-3: the public ``/api/v1/segments/*`` routes were unmounted in favour of
# the project-scoped ``/web-api/v1/projects/{project_id}/segments/*`` BFF surface
# (``echoroo.api.web_v1.projects._annotation_sets``). The handlers below are left
# as plain importable functions (no ``@router`` decorators) because the BFF
# delegates to them via ``legacy_segments.{get_segment,update_segment,
# create_annotation,create_segment_note}(...)`` and reuses ``SegmentServiceDep``.
async def get_segment(
    segment_id: UUID,
    current_user: CurrentUser,
    service: SegmentServiceDep,
) -> AnnotationSegmentDetailResponse:
    return await service.get_detail(segment_id)


async def update_segment(
    segment_id: UUID,
    request: AnnotationSegmentStatusUpdate,
    current_user: CurrentUser,
    service: SegmentServiceDep,
) -> AnnotationSegmentDetailResponse:
    return await service.update(
        segment_id, user_id=current_user.id, request=request,
    )


async def create_annotation(
    segment_id: UUID,
    request: TimeRangeAnnotationCreate,
    current_user: CurrentUser,
    service: SegmentServiceDep,
) -> TimeRangeAnnotationResponse:
    return await service.create_annotation(
        segment_id, user_id=current_user.id, request=request,
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
