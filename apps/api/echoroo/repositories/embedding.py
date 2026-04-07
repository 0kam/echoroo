"""Repository for embedding vectors."""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.embedding import Embedding


class EmbeddingRepository:
    """Repository for Embedding entity operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: SQLAlchemy async session
        """
        self.session = session

    async def create_batch(self, embeddings: list[Embedding]) -> list[Embedding]:
        """Bulk-insert embedding records.

        Args:
            embeddings: List of Embedding instances to persist

        Returns:
            List of created Embedding instances
        """
        self.session.add_all(embeddings)
        await self.session.flush()
        return embeddings

    async def delete_by_run(self, detection_run_id: uuid.UUID) -> int:
        """Delete all embeddings associated with a detection run.

        Args:
            detection_run_id: Detection run UUID

        Returns:
            Number of rows deleted
        """
        result: CursorResult[tuple[()]] = await self.session.execute(  # type: ignore[assignment]
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
        result = await self.session.execute(
            select(Embedding)
            .where(Embedding.recording_id == recording_id)
            .order_by(Embedding.start_time)
        )
        return list(result.scalars().all())
