"""Annotations API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.clip_annotation import ClipAnnotationRepository
from echoroo.repositories.note import NoteRepository
from echoroo.repositories.sound_event_annotation import SoundEventAnnotationRepository
from echoroo.schemas.annotation import (
    AddTagRequest,
    BatchTagRequest,
    BatchTagResponse,
    ClipAnnotationDetailResponse,
    ReviewRequest,
    SoundEventAnnotationCreate,
    SoundEventAnnotationResponse,
    SoundEventAnnotationUpdate,
)
from echoroo.schemas.note import NoteCreate, NoteResponse
from echoroo.services.annotation import AnnotationService

router = APIRouter(tags=["annotations"])


def get_annotation_service(db: DbSession) -> AnnotationService:
    """Get AnnotationService instance.

    Args:
        db: Database session

    Returns:
        AnnotationService instance
    """
    return AnnotationService(
        clip_annotation_repo=ClipAnnotationRepository(db),
        sound_event_repo=SoundEventAnnotationRepository(db),
        note_repo=NoteRepository(db),
    )


AnnotationServiceDep = Annotated[AnnotationService, Depends(get_annotation_service)]


@router.get(
    "/projects/{project_id}/annotation-tasks/{task_id}/clip-annotation",
    response_model=ClipAnnotationDetailResponse,
    summary="Get or create clip annotation",
    description="Get existing clip annotation for an annotation task, or create a new one if none exists",
)
async def get_or_create_clip_annotation(
    project_id: UUID,
    task_id: UUID,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> ClipAnnotationDetailResponse:
    """Get or create a clip annotation for an annotation task.

    Args:
        project_id: Parent project's UUID
        task_id: AnnotationTask's UUID
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        ClipAnnotationDetailResponse for the existing or new clip annotation

    Raises:
        401: Not authenticated
        404: Annotation task not found
    """
    return await service.get_or_create_clip_annotation(task_id, current_user.id)


@router.post(
    "/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags",
    response_model=ClipAnnotationDetailResponse,
    summary="Add tag to clip annotation",
    description="Add a tag to a clip annotation",
)
async def add_clip_tag(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: AddTagRequest,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> ClipAnnotationDetailResponse:
    """Add a tag to a clip annotation.

    Args:
        project_id: Parent project's UUID
        clip_annotation_id: ClipAnnotation's UUID
        request: Tag addition request with tag_id
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Updated ClipAnnotationDetailResponse

    Raises:
        401: Not authenticated
        404: Clip annotation not found
    """
    return await service.add_clip_tag(clip_annotation_id, request.tag_id)


@router.delete(
    "/projects/{project_id}/clip-annotations/{clip_annotation_id}/tags",
    response_model=ClipAnnotationDetailResponse,
    summary="Remove tag from clip annotation",
    description="Remove a tag from a clip annotation",
)
async def remove_clip_tag(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: AddTagRequest,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> ClipAnnotationDetailResponse:
    """Remove a tag from a clip annotation.

    Args:
        project_id: Parent project's UUID
        clip_annotation_id: ClipAnnotation's UUID
        request: Tag removal request with tag_id
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Updated ClipAnnotationDetailResponse

    Raises:
        401: Not authenticated
        404: Clip annotation not found
    """
    await service.remove_clip_tag(clip_annotation_id, request.tag_id)
    # Return updated clip annotation
    updated = await service.clip_annotation_repo.get_by_id(clip_annotation_id)
    if updated is None:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip annotation not found",
        )
    return ClipAnnotationDetailResponse.model_validate(updated)


@router.get(
    "/projects/{project_id}/clip-annotations/{clip_annotation_id}/sound-events",
    response_model=list[SoundEventAnnotationResponse],
    summary="List sound events",
    description="List all sound event annotations belonging to a clip annotation",
)
async def list_sound_events(
    project_id: UUID,
    clip_annotation_id: UUID,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> list[SoundEventAnnotationResponse]:
    """List sound event annotations for a clip annotation.

    Args:
        project_id: Parent project's UUID
        clip_annotation_id: ClipAnnotation's UUID
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        List of SoundEventAnnotationResponse

    Raises:
        401: Not authenticated
    """
    sound_events = await service.sound_event_repo.list_by_clip_annotation(clip_annotation_id)
    return [SoundEventAnnotationResponse.model_validate(se) for se in sound_events]


@router.post(
    "/projects/{project_id}/clip-annotations/{clip_annotation_id}/sound-events",
    response_model=SoundEventAnnotationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create sound event annotation",
    description="Create a new sound event annotation within a clip annotation",
)
async def create_sound_event(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: SoundEventAnnotationCreate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> SoundEventAnnotationResponse:
    """Create a new sound event annotation.

    Args:
        project_id: Parent project's UUID
        clip_annotation_id: ClipAnnotation's UUID
        request: Sound event creation data
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Created SoundEventAnnotationResponse

    Raises:
        401: Not authenticated
        404: Clip annotation not found
    """
    return await service.create_sound_event(clip_annotation_id, current_user.id, request)


@router.patch(
    "/projects/{project_id}/sound-events/{sound_event_id}",
    response_model=SoundEventAnnotationResponse,
    summary="Update sound event annotation",
    description="Update a sound event annotation's geometry or confidence",
)
async def update_sound_event(
    project_id: UUID,
    sound_event_id: UUID,
    request: SoundEventAnnotationUpdate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> SoundEventAnnotationResponse:
    """Update a sound event annotation.

    Args:
        project_id: Parent project's UUID
        sound_event_id: SoundEventAnnotation's UUID
        request: Update data
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Updated SoundEventAnnotationResponse

    Raises:
        401: Not authenticated
        404: Sound event annotation not found
    """
    return await service.update_sound_event(sound_event_id, request)


@router.delete(
    "/projects/{project_id}/sound-events/{sound_event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete sound event annotation",
    description="Delete a sound event annotation by ID",
)
async def delete_sound_event(
    project_id: UUID,
    sound_event_id: UUID,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> None:
    """Delete a sound event annotation.

    Args:
        project_id: Parent project's UUID
        sound_event_id: SoundEventAnnotation's UUID
        current_user: Current authenticated user
        service: Annotation service instance

    Raises:
        401: Not authenticated
        404: Sound event annotation not found
    """
    await service.delete_sound_event(sound_event_id)


@router.post(
    "/projects/{project_id}/sound-events/{sound_event_id}/tags",
    status_code=status.HTTP_200_OK,
    summary="Add tag to sound event annotation",
    description="Add a tag to a sound event annotation",
)
async def add_sound_event_tag(
    project_id: UUID,
    sound_event_id: UUID,
    request: AddTagRequest,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> dict[str, object]:
    """Add a tag to a sound event annotation.

    Args:
        project_id: Parent project's UUID
        sound_event_id: SoundEventAnnotation's UUID
        request: Tag addition request with tag_id
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Empty success response

    Raises:
        401: Not authenticated
        404: Sound event annotation not found
    """
    await service.add_sound_event_tag(sound_event_id, request.tag_id)
    return dict()


@router.delete(
    "/projects/{project_id}/sound-events/{sound_event_id}/tags",
    status_code=status.HTTP_200_OK,
    summary="Remove tag from sound event annotation",
    description="Remove a tag from a sound event annotation",
)
async def remove_sound_event_tag(
    project_id: UUID,
    sound_event_id: UUID,
    request: AddTagRequest,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> dict[str, object]:
    """Remove a tag from a sound event annotation.

    Args:
        project_id: Parent project's UUID
        sound_event_id: SoundEventAnnotation's UUID
        request: Tag removal request with tag_id
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Empty success response

    Raises:
        401: Not authenticated
        404: Sound event annotation not found
    """
    await service.remove_sound_event_tag(sound_event_id, request.tag_id)
    return dict()


@router.post(
    "/projects/{project_id}/clip-annotations/batch-tag",
    response_model=BatchTagResponse,
    summary="Batch tag clips",
    description="Create clip annotations for multiple tasks and add a tag to all",
)
async def batch_tag_clips(
    project_id: UUID,
    request: BatchTagRequest,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> BatchTagResponse:
    """Batch-tag multiple clips by task IDs.

    Args:
        project_id: Parent project's UUID
        request: Batch tag request with task_ids and tag_id
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        BatchTagResponse with updated_count and clip_annotations list

    Raises:
        401: Not authenticated
        404: Any referenced annotation task not found
        422: task_ids is empty
    """
    return await service.batch_tag_clips(request.task_ids, request.tag_id, current_user.id)


@router.post(
    "/projects/{project_id}/clip-annotations/{clip_annotation_id}/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add note to clip annotation",
    description="Add a note or review comment to a clip annotation",
)
async def add_note(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: NoteCreate,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> NoteResponse:
    """Add a note to a clip annotation.

    Args:
        project_id: Parent project's UUID
        clip_annotation_id: ClipAnnotation's UUID
        request: Note creation data
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Created NoteResponse

    Raises:
        401: Not authenticated
        404: Clip annotation not found
    """
    return await service.add_note(clip_annotation_id, current_user.id, request)


@router.post(
    "/projects/{project_id}/clip-annotations/{clip_annotation_id}/review",
    response_model=ClipAnnotationDetailResponse,
    summary="Review a clip annotation",
    description="Approve or reject a clip annotation with optional comment",
)
async def review_clip_annotation(
    project_id: UUID,
    clip_annotation_id: UUID,
    request: ReviewRequest,
    current_user: CurrentUser,
    service: AnnotationServiceDep,
) -> ClipAnnotationDetailResponse:
    """Review a clip annotation (approve or reject).

    Args:
        project_id: Parent project's UUID
        clip_annotation_id: ClipAnnotation's UUID
        request: Review request with status and optional comment
        current_user: Current authenticated user
        service: Annotation service instance

    Returns:
        Updated ClipAnnotationDetailResponse

    Raises:
        401: Not authenticated
        404: Clip annotation not found
        422: Invalid review status
    """
    return await service.review_clip_annotation(
        clip_annotation_id, current_user.id, request.status, request.comment
    )
