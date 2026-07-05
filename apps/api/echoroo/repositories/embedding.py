"""Repository for embedding vectors."""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult

from echoroo.models.embedding import Embedding
from echoroo.repositories.base import BaseRepository


class EmbeddingRepository(BaseRepository[Embedding]):
    """Repository for Embedding entity operations."""

    model = Embedding

    async def create_batch(self, embeddings: list[Embedding]) -> list[Embedding]:
        """Bulk-insert embedding records.

        Args:
            embeddings: List of Embedding instances to persist

        Returns:
            List of created Embedding instances
        """
        self.db.add_all(embeddings)
        await self.db.flush()
        return embeddings

    async def delete_by_run(self, detection_run_id: uuid.UUID) -> int:
        """Delete all embeddings associated with a detection run.

        Args:
            detection_run_id: Detection run UUID

        Returns:
            Number of rows deleted
        """
        result: CursorResult[tuple[()]] = await self.db.execute(  # type: ignore[assignment]
            delete(Embedding).where(Embedding.detection_run_id == detection_run_id)
        )
        return int(result.rowcount)

    async def get_by_recording(self, recording_id: uuid.UUID) -> list[Embedding]:
        """Return all embeddings for a given recording.

        Args:
            recording_id: Recording UUID

        Returns:
            List of Embedding instances ordered by start_time
        """
        result = await self.db.execute(
            select(Embedding)
            .where(Embedding.recording_id == recording_id)
            .order_by(Embedding.start_time)
        )
        return list(result.scalars().all())
