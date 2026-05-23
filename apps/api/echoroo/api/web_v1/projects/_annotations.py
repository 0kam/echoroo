"""Project annotation BFF adapters.

Spec/009 PR D introduced ``batch_tag_clips`` (the original "annotation
batch tag" mutation that the project list / detection-review screens
needed before export). Spec/009 PR 2.5 extends this module to cover the
remaining 8 annotation surface endpoints used by the annotation task UI:

* GET    ``/{pid}/annotation-tasks/{tid}/clip-annotation``
* POST   ``/{pid}/clip-annotations/{cid}/tags``
* DELETE ``/{pid}/clip-annotations/{cid}/tags/{tid}``
* POST   ``/{pid}/clip-annotations/{cid}/sound-events``
* DELETE ``/{pid}/sound-events/{sid}``
* POST   ``/{pid}/sound-events/{sid}/tags``
* DELETE ``/{pid}/sound-events/{sid}/tags/{tid}``
* POST   ``/{pid}/clip-annotations/{cid}/review``

Each handler is a thin adapter: it re-uses the existing per-endpoint
``Action`` registered for the legacy ``/api/v1`` route and delegates the
real work to the legacy handler so schema validation, service
orchestration, and any response shaping continue to live in one place.
This keeps the BFF surface auditable as a 1:1 mirror of the legacy
contract while moving the browser surface onto the Cookie + CSRF
session boundary.

None of these endpoints declare a ``Recording`` / ``Detection`` / ``Site``
response model, so ``scripts/lint_response_filter.py`` does not require
an allowlist entry (legacy ``api/v1/annotations.py`` is similarly outside
its scope).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import annotations as legacy_annotations
from echoroo.core.actions import (
    ANNOTATION_BATCH_TAG_ACTION,
    ANNOTATION_CLIP_GET_ACTION,
    ANNOTATION_CLIP_TAG_CREATE_ACTION,
    ANNOTATION_CLIP_TAG_DELETE_ACTION,
    ANNOTATION_REVIEW_ACTION,
    ANNOTATION_SOUND_EVENT_CREATE_ACTION,
    ANNOTATION_SOUND_EVENT_DELETE_ACTION,
    ANNOTATION_SOUND_EVENT_TAG_CREATE_ACTION,
    ANNOTATION_SOUND_EVENT_TAG_DELETE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.annotation import (
    AddTagRequest,
    ClipAnnotationDetailResponse,
    ReviewRequest,
    SoundEventAnnotationCreate,
    SoundEventAnnotationResponse,
)

router = APIRouter()


@router.post(
    "/{project_id}/clip-annotations/batch-tag",
    response_model=legacy_annotations.BatchTagResponse,
    summary="Batch tag clips",
    description="BFF adapter for the legacy batch clip-tagging endpoint.",
)
async def batch_tag_clips(
    project_id: UUID,
    request: legacy_annotations.BatchTagRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> legacy_annotations.BatchTagResponse:
    """Delegate batch clip tagging to the legacy handler."""
    await gate_action(
        action=ANNOTATION_BATCH_TAG_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.batch_tag_clips(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/annotation-tasks/{task_id}/clip-annotation",
    response_model=ClipAnnotationDetailResponse,
    summary="Get or create clip annotation",
    description="BFF adapter for the legacy get-or-create clip-annotation endpoint.",
)
async def get_or_create_clip_annotation(
    project_id: UUID,
    task_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> ClipAnnotationDetailResponse:
    """Delegate get-or-create clip annotation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.get_or_create_clip_annotation(
        project_id=project_id,
        task_id=task_id,
        request=http_request,  # legacy ``request: Request`` param
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/clip-annotations/{clip_annotation_id}/tags",
    response_model=ClipAnnotationDetailResponse,
    summary="Add tag to clip annotation",
    description="BFF adapter for the legacy add-clip-tag endpoint.",
)
async def add_clip_tag(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: AddTagRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> ClipAnnotationDetailResponse:
    """Delegate add-clip-tag to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_TAG_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.add_clip_tag(
        project_id=project_id,
        clip_annotation_id=clip_annotation_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/clip-annotations/{clip_annotation_id}/tags/{tag_id}",
    response_model=ClipAnnotationDetailResponse,
    summary="Remove tag from clip annotation",
    description="BFF adapter for the legacy remove-clip-tag endpoint.",
)
async def remove_clip_tag(
    project_id: UUID,
    clip_annotation_id: UUID,
    tag_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> ClipAnnotationDetailResponse:
    """Delegate remove-clip-tag to the legacy handler."""
    await gate_action(
        action=ANNOTATION_CLIP_TAG_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.remove_clip_tag(
        project_id=project_id,
        clip_annotation_id=clip_annotation_id,
        tag_id=tag_id,
        request=http_request,  # legacy ``request: Request`` param
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/clip-annotations/{clip_annotation_id}/sound-events",
    response_model=SoundEventAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create sound event annotation",
    description="BFF adapter for the legacy create-sound-event endpoint.",
)
async def create_sound_event(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: SoundEventAnnotationCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> SoundEventAnnotationResponse:
    """Delegate create-sound-event to the legacy handler."""
    await gate_action(
        action=ANNOTATION_SOUND_EVENT_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.create_sound_event(
        project_id=project_id,
        clip_annotation_id=clip_annotation_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/sound-events/{sound_event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete sound event annotation",
    description="BFF adapter for the legacy delete-sound-event endpoint.",
)
async def delete_sound_event(
    project_id: UUID,
    sound_event_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> None:
    """Delegate delete-sound-event to the legacy handler."""
    await gate_action(
        action=ANNOTATION_SOUND_EVENT_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    await legacy_annotations.delete_sound_event(
        project_id=project_id,
        sound_event_id=sound_event_id,
        request=http_request,  # legacy ``request: Request`` param
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/sound-events/{sound_event_id}/tags",
    status_code=status.HTTP_200_OK,
    summary="Add tag to sound event annotation",
    description="BFF adapter for the legacy add-sound-event-tag endpoint.",
)
async def add_sound_event_tag(
    project_id: UUID,
    sound_event_id: UUID,
    request: AddTagRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> dict[str, object]:
    """Delegate add-sound-event-tag to the legacy handler."""
    await gate_action(
        action=ANNOTATION_SOUND_EVENT_TAG_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.add_sound_event_tag(
        project_id=project_id,
        sound_event_id=sound_event_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/sound-events/{sound_event_id}/tags/{tag_id}",
    status_code=status.HTTP_200_OK,
    summary="Remove tag from sound event annotation",
    description="BFF adapter for the legacy remove-sound-event-tag endpoint.",
)
async def remove_sound_event_tag(
    project_id: UUID,
    sound_event_id: UUID,
    tag_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> dict[str, object]:
    """Delegate remove-sound-event-tag to the legacy handler."""
    await gate_action(
        action=ANNOTATION_SOUND_EVENT_TAG_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.remove_sound_event_tag(
        project_id=project_id,
        sound_event_id=sound_event_id,
        tag_id=tag_id,
        request=http_request,  # legacy ``request: Request`` param
        current_user=current_user,
        service=service,
        db=db,
    )


@router.post(
    "/{project_id}/clip-annotations/{clip_annotation_id}/review",
    response_model=ClipAnnotationDetailResponse,
    summary="Review a clip annotation",
    description="BFF adapter for the legacy review-clip-annotation endpoint.",
)
async def review_clip_annotation(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: ReviewRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> ClipAnnotationDetailResponse:
    """Delegate review-clip-annotation to the legacy handler."""
    await gate_action(
        action=ANNOTATION_REVIEW_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotations.review_clip_annotation(
        project_id=project_id,
        clip_annotation_id=clip_annotation_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
