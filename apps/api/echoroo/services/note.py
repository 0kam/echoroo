"""Note service for business logic."""

from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.note import Note
from echoroo.repositories.note import NoteRepository
from echoroo.schemas.note import NoteCreate, NoteResponse


class NoteService:
    """Service for note management business logic."""

    def __init__(self, note_repo: NoteRepository) -> None:
        """Initialize service with repository.

        Args:
            note_repo: Note repository instance
        """
        self.note_repo = note_repo

    async def create(
        self,
        user_id: UUID,
        request: NoteCreate,
        clip_annotation_id: UUID | None = None,
        sound_event_annotation_id: UUID | None = None,
    ) -> NoteResponse:
        """Create a new note attached to exactly one parent entity.

        Exactly one of clip_annotation_id or sound_event_annotation_id must be provided.

        Args:
            user_id: User creating the note
            request: Note creation data
            clip_annotation_id: Optional ClipAnnotation to attach the note to
            sound_event_annotation_id: Optional SoundEventAnnotation to attach the note to

        Returns:
            Created NoteResponse

        Raises:
            HTTPException: 400 if not exactly one parent is provided
        """
        provided = sum(
            [
                clip_annotation_id is not None,
                sound_event_annotation_id is not None,
            ]
        )
        if provided != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exactly one of clip_annotation_id or sound_event_annotation_id must be provided",
            )

        note = Note(
            created_by_id=user_id,
            clip_annotation_id=clip_annotation_id,
            sound_event_annotation_id=sound_event_annotation_id,
            content=request.content,
            is_review=request.is_review,
        )

        created = await self.note_repo.create(note)
        return NoteResponse.model_validate(created)
