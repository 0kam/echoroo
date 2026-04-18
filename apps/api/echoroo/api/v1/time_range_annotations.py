"""HTTP router for :class:`TimeRangeAnnotation` update/delete and notes.

Endpoints follow ``specs/003-annotation/contracts/annotations.yaml``.
Creation is handled by ``POST /segments/{id}/annotations``.
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
    TimeRangeAnnotationResponse,
    TimeRangeAnnotationUpdate,
)
from echoroo.services.annotation_set import AnnotationSetService
from echoroo.services.time_range_annotation import TimeRangeAnnotationService

router = APIRouter(prefix="/annotations", tags=["time-range-annotations"])


def get_annotation_service(db: DbSession) -> TimeRangeAnnotationService:
    set_repo = AnnotationSetRepository(db)
    segment_repo = AnnotationSegmentRepository(db)
    annotation_repo = TimeRangeAnnotationRepository(db)
    set_service = AnnotationSetService(set_repo=set_repo, segment_repo=segment_repo)
    return TimeRangeAnnotationService(
        annotation_repo=annotation_repo,
        segment_repo=segment_repo,
        set_service=set_service,
    )


AnnotationServiceDep = Annotated[
    TimeRangeAnnotationService, Depends(get_annotation_service)
]


@router.patch(
    "/{annotation_id}",
    response_model=TimeRangeAnnotationResponse,
    summary="Update a TimeRangeAnnotation",
)
async def update_annotation(
    annotation_id: UUID,
    request: TimeRangeAnnotationUpdate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> TimeRangeAnnotationResponse:
    return await service.update(annotation_id, request)


@router.delete(
    "/{annotation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a TimeRangeAnnotation",
)
async def delete_annotation(
    annotation_id: UUID,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> None:
    await service.delete(annotation_id)


@router.post(
    "/{annotation_id}/notes",
    response_model=AnnotationNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Attach a note to a TimeRangeAnnotation",
)
async def create_annotation_note(
    annotation_id: UUID,
    request: AnnotationNoteCreate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> AnnotationNoteResponse:
    return await service.create_note(
        annotation_id, user_id=current_user.id, request=request,
    )
