"""Note repository for database operations."""

from echoroo.models.note import Note
from echoroo.repositories.base import BaseRepository


class NoteRepository(BaseRepository[Note]):
    """Repository for Note entity operations."""

    model = Note

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
