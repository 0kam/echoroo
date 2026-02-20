"""Annotation service for business logic."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.clip_annotation import ClipAnnotation
from echoroo.models.enums import ReviewStatus
from echoroo.models.note import Note
from echoroo.models.sound_event_annotation import SoundEventAnnotation
from echoroo.repositories.clip_annotation import ClipAnnotationRepository
from echoroo.repositories.note import NoteRepository
from echoroo.repositories.sound_event_annotation import SoundEventAnnotationRepository
from echoroo.schemas.annotation import (
    BatchTagResponse,
    ClipAnnotationDetailResponse,
    SoundEventAnnotationCreate,
    SoundEventAnnotationResponse,
    SoundEventAnnotationUpdate,
)
from echoroo.schemas.note import NoteCreate, NoteResponse


class AnnotationService:
    """Service for annotation management business logic."""

    def __init__(
        self,
        clip_annotation_repo: ClipAnnotationRepository,
        sound_event_repo: SoundEventAnnotationRepository,
        note_repo: NoteRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            clip_annotation_repo: ClipAnnotation repository instance
            sound_event_repo: SoundEventAnnotation repository instance
            note_repo: Note repository instance
        """
        self.clip_annotation_repo = clip_annotation_repo
        self.sound_event_repo = sound_event_repo
        self.note_repo = note_repo

    async def get_or_create_clip_annotation(
        self,
        task_id: UUID,
        user_id: UUID,
    ) -> ClipAnnotationDetailResponse:
        """Get existing or create a new clip annotation for a task.

        If a clip annotation already exists for the given task, it is returned.
        Otherwise a new one is created associated with the task.

        Args:
            task_id: AnnotationTask's UUID
            user_id: User requesting or creating the annotation

        Returns:
            ClipAnnotationDetailResponse for the existing or newly created annotation

        Raises:
            HTTPException: 404 if the referenced task does not exist
        """
        from echoroo.models.annotation_task import AnnotationTask
        from sqlalchemy import select

        # Verify task exists and retrieve clip_id
        task_result = await self.clip_annotation_repo.db.execute(
            select(AnnotationTask).where(AnnotationTask.id == task_id)
        )
        task = task_result.scalar_one_or_none()
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation task not found",
            )

        existing = await self.clip_annotation_repo.get_by_task_id(task_id)
        if existing is not None:
            return ClipAnnotationDetailResponse.model_validate(existing)

        clip_annotation = ClipAnnotation(
            task_id=task_id,
            clip_id=task.clip_id,
            created_by_id=user_id,
        )
        created = await self.clip_annotation_repo.create(clip_annotation)
        return ClipAnnotationDetailResponse.model_validate(created)

    async def add_clip_tag(
        self,
        clip_annotation_id: UUID,
        tag_id: UUID,
    ) -> ClipAnnotationDetailResponse:
        """Add a tag to a clip annotation.

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            tag_id: Tag's UUID to add

        Returns:
            Updated ClipAnnotationDetailResponse

        Raises:
            HTTPException: 404 if clip annotation not found
        """
        clip_annotation = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
        if clip_annotation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clip annotation not found",
            )

        await self.clip_annotation_repo.add_tag(clip_annotation_id, tag_id)

        # Reload to get updated tags
        updated = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
        assert updated is not None
        return ClipAnnotationDetailResponse.model_validate(updated)

    async def remove_clip_tag(
        self,
        clip_annotation_id: UUID,
        tag_id: UUID,
    ) -> None:
        """Remove a tag from a clip annotation.

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            tag_id: Tag's UUID to remove

        Raises:
            HTTPException: 404 if clip annotation not found
        """
        clip_annotation = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
        if clip_annotation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clip annotation not found",
            )

        await self.clip_annotation_repo.remove_tag(clip_annotation_id, tag_id)

    async def create_sound_event(
        self,
        clip_annotation_id: UUID,
        user_id: UUID,
        request: SoundEventAnnotationCreate,
    ) -> SoundEventAnnotationResponse:
        """Create a new sound event annotation within a clip annotation.

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            user_id: User creating the sound event
            request: Sound event creation data

        Returns:
            Created SoundEventAnnotationResponse

        Raises:
            HTTPException: 404 if clip annotation not found
        """
        clip_annotation = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
        if clip_annotation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clip annotation not found",
            )

        geometry_dict: dict[str, object] = {
            "type": request.geometry.type,
            "coordinates": request.geometry.coordinates,
        }

        sound_event = SoundEventAnnotation(
            clip_annotation_id=clip_annotation_id,
            created_by_id=user_id,
            geometry=geometry_dict,
            source=request.source,
            confidence=request.confidence,
        )

        created = await self.sound_event_repo.create(sound_event)

        # Add tags if provided
        if request.tag_ids:
            for tag_id in request.tag_ids:
                await self.sound_event_repo.add_tag(created.id, tag_id)
            # Reload with updated tags
            reloaded = await self.sound_event_repo.get_by_id(created.id)
            assert reloaded is not None
            return SoundEventAnnotationResponse.model_validate(reloaded)

        return SoundEventAnnotationResponse.model_validate(created)

    async def update_sound_event(
        self,
        sound_event_id: UUID,
        request: SoundEventAnnotationUpdate,
    ) -> SoundEventAnnotationResponse:
        """Update an existing sound event annotation.

        Args:
            sound_event_id: SoundEventAnnotation's UUID
            request: Update data

        Returns:
            Updated SoundEventAnnotationResponse

        Raises:
            HTTPException: 404 if sound event annotation not found
        """
        sound_event = await self.sound_event_repo.get_by_id(sound_event_id)
        if sound_event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sound event annotation not found",
            )

        if request.geometry is not None:
            sound_event.geometry = {
                "type": request.geometry.type,
                "coordinates": request.geometry.coordinates,
            }
        if request.confidence is not None:
            sound_event.confidence = request.confidence

        updated = await self.sound_event_repo.update(sound_event)
        return SoundEventAnnotationResponse.model_validate(updated)

    async def delete_sound_event(self, sound_event_id: UUID) -> None:
        """Delete a sound event annotation.

        Args:
            sound_event_id: SoundEventAnnotation's UUID

        Raises:
            HTTPException: 404 if sound event annotation not found
        """
        sound_event = await self.sound_event_repo.get_by_id(sound_event_id)
        if sound_event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sound event annotation not found",
            )

        await self.sound_event_repo.delete(sound_event_id)

    async def add_sound_event_tag(
        self,
        sound_event_id: UUID,
        tag_id: UUID,
    ) -> None:
        """Add a tag to a sound event annotation.

        Args:
            sound_event_id: SoundEventAnnotation's UUID
            tag_id: Tag's UUID to add

        Raises:
            HTTPException: 404 if sound event annotation not found
        """
        sound_event = await self.sound_event_repo.get_by_id(sound_event_id)
        if sound_event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sound event annotation not found",
            )

        await self.sound_event_repo.add_tag(sound_event_id, tag_id)

    async def remove_sound_event_tag(
        self,
        sound_event_id: UUID,
        tag_id: UUID,
    ) -> None:
        """Remove a tag from a sound event annotation.

        Args:
            sound_event_id: SoundEventAnnotation's UUID
            tag_id: Tag's UUID to remove

        Raises:
            HTTPException: 404 if sound event annotation not found
        """
        sound_event = await self.sound_event_repo.get_by_id(sound_event_id)
        if sound_event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sound event annotation not found",
            )

        await self.sound_event_repo.remove_tag(sound_event_id, tag_id)

    async def batch_tag_clips(
        self,
        task_ids: list[UUID],
        tag_id: UUID,
        user_id: UUID,
    ) -> BatchTagResponse:
        """Create or get clip annotations for multiple tasks and add a tag to all.

        For each task_id:
        1. Get or create a ClipAnnotation
        2. Add the specified tag

        Args:
            task_ids: List of AnnotationTask UUIDs to process
            tag_id: Tag's UUID to apply to all clip annotations
            user_id: User performing the batch operation

        Returns:
            BatchTagResponse with updated_count and clip_annotations list

        Raises:
            HTTPException: 404 if any referenced task does not exist
        """
        from echoroo.models.annotation_task import AnnotationTask
        from sqlalchemy import select

        clip_annotations: list[ClipAnnotationDetailResponse] = []

        for task_id in task_ids:
            # Verify task exists and retrieve clip_id
            task_result = await self.clip_annotation_repo.db.execute(
                select(AnnotationTask).where(AnnotationTask.id == task_id)
            )
            task = task_result.scalar_one_or_none()
            if task is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Annotation task not found: {task_id}",
                )

            # Get or create clip annotation for this task
            existing = await self.clip_annotation_repo.get_by_task_id(task_id)
            if existing is not None:
                clip_annotation_id = existing.id
            else:
                clip_annotation = ClipAnnotation(
                    task_id=task_id,
                    clip_id=task.clip_id,
                    created_by_id=user_id,
                )
                created = await self.clip_annotation_repo.create(clip_annotation)
                clip_annotation_id = created.id

            # Add tag (ignore if already tagged)
            await self.clip_annotation_repo.add_tag(clip_annotation_id, tag_id)

            # Reload with updated relationships
            updated = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
            assert updated is not None
            clip_annotations.append(ClipAnnotationDetailResponse.model_validate(updated))

        return BatchTagResponse(
            updated_count=len(clip_annotations),
            clip_annotations=clip_annotations,
        )

    async def add_note(
        self,
        clip_annotation_id: UUID,
        user_id: UUID,
        request: NoteCreate,
    ) -> NoteResponse:
        """Add a note to a clip annotation.

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            user_id: User creating the note
            request: Note creation data

        Returns:
            Created NoteResponse

        Raises:
            HTTPException: 404 if clip annotation not found
        """
        clip_annotation = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
        if clip_annotation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clip annotation not found",
            )

        note = Note(
            created_by_id=user_id,
            clip_annotation_id=clip_annotation_id,
            content=request.content,
            is_review=request.is_review,
        )

        created = await self.note_repo.create(note)
        return NoteResponse.model_validate(created)

    async def review_clip_annotation(
        self,
        clip_annotation_id: UUID,
        reviewer_id: UUID,
        status_value: str,
        comment: str | None = None,
    ) -> ClipAnnotationDetailResponse:
        """Review a clip annotation (approve or reject).

        1. Validate clip annotation exists
        2. Update review_status, reviewed_by_id, reviewed_at
        3. If comment provided, create a review note
        4. Return updated clip annotation

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            reviewer_id: User performing the review
            status_value: Review decision: 'approved' or 'rejected'
            comment: Optional review comment

        Returns:
            Updated ClipAnnotationDetailResponse

        Raises:
            HTTPException: 404 if clip annotation not found
            HTTPException: 422 if status value is invalid
        """
        clip_annotation = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
        if clip_annotation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clip annotation not found",
            )

        try:
            review_status = ReviewStatus(status_value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid review status: {status_value}. Must be 'approved' or 'rejected'",
            )

        clip_annotation.review_status = review_status
        clip_annotation.reviewed_by_id = reviewer_id
        clip_annotation.reviewed_at = datetime.now(timezone.utc)

        updated = await self.clip_annotation_repo.update_review(clip_annotation)

        if comment:
            note = Note(
                created_by_id=reviewer_id,
                clip_annotation_id=clip_annotation_id,
                content=comment,
                is_review=True,
            )
            await self.note_repo.create(note)
            # Expire the cached instance so the subsequent query fetches fresh data
            self.clip_annotation_repo.db.expire(updated)
            reloaded = await self.clip_annotation_repo.get_by_id(clip_annotation_id)
            assert reloaded is not None
            return ClipAnnotationDetailResponse.model_validate(reloaded)

        return ClipAnnotationDetailResponse.model_validate(updated)
