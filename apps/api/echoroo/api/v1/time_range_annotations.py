"""HTTP router for :class:`TimeRangeAnnotation` update/delete and notes.

Endpoints follow ``specs/003-annotation/contracts/annotations.yaml``.
Creation is handled by ``POST /segments/{id}/annotations``.
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


# W2-3 PR-4: the public ``/api/v1/annotations/*`` routes were unmounted in favour
# of the project-scoped ``/web-api/v1/projects/{project_id}/annotations/*`` BFF
# surface (``echoroo.api.web_v1.projects._annotation_sets``). The handlers below
# are left as plain importable functions (no ``@router`` decorators) because the
# BFF delegates to them via ``legacy_time_range_annotations.{update_annotation,
# delete_annotation,create_annotation_note}(...)`` and reuses ``AnnotationServiceDep``.
async def update_annotation(
    annotation_id: UUID,
    request: TimeRangeAnnotationUpdate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> TimeRangeAnnotationResponse:
    return await service.update(annotation_id, request)


async def delete_annotation(
    annotation_id: UUID,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> None:
    await service.delete(annotation_id)


async def create_annotation_note(
    annotation_id: UUID,
    request: AnnotationNoteCreate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> AnnotationNoteResponse:
    return await service.create_note(
        annotation_id, user_id=current_user.id, request=request,
    )
