"""Note repository for database operations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.note import Note


class NoteRepository:
    """Repository for Note entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def create(self, note: Note) -> Note:
        """Create a new note.

        Args:
            note: Note instance to create

        Returns:
            Created note instance
        """
        self.db.add(note)
        await self.db.flush()
        await self.db.refresh(note, ["created_by"])
        return note

    async def list_by_clip_annotation(self, clip_annotation_id: UUID) -> list[Note]:
        """List all notes attached to a clip annotation.

        Args:
            clip_annotation_id: ClipAnnotation's UUID

        Returns:
            List of Note instances ordered by creation time ascending
        """
        result = await self.db.execute(
            select(Note)
            .where(Note.clip_annotation_id == clip_annotation_id)
            .order_by(Note.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_by_sound_event(self, sound_event_annotation_id: UUID) -> list[Note]:
        """List all notes attached to a sound event annotation.

        Args:
            sound_event_annotation_id: SoundEventAnnotation's UUID

        Returns:
            List of Note instances ordered by creation time ascending
        """
        result = await self.db.execute(
            select(Note)
            .where(Note.sound_event_annotation_id == sound_event_annotation_id)
            .order_by(Note.created_at.asc())
        )
        return list(result.scalars().all())
