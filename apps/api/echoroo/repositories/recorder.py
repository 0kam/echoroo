"""Recorder repository for database operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.recorder import Recorder
from echoroo.schemas.recorder import RecorderCreate, RecorderUpdate


class RecorderRepository:
    """Repository for Recorder entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, recorder_id: str) -> Recorder | None:
        """Get recorder by ID.

        Args:
            recorder_id: Recorder's unique identifier

        Returns:
            Recorder instance or None if not found
        """
        result = await self.db.execute(
            select(Recorder).where(Recorder.id == recorder_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, offset: int = 0, limit: int = 100) -> list[Recorder]:
        """Get all recorders with pagination.

        Args:
            offset: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            List of Recorder instances
        """
        result = await self.db.execute(
            select(Recorder)
            .order_by(Recorder.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total number of recorders.

        Returns:
            Total count of recorders
        """
        from sqlalchemy import func

        result = await self.db.execute(
            select(func.count()).select_from(Recorder)
        )
        count: int = result.scalar_one()
        return count

    async def create(self, data: RecorderCreate) -> Recorder:
        """Create a new recorder.

        Args:
            data: Recorder creation data

        Returns:
            Created recorder instance
        """
        recorder = Recorder(
            id=data.id,
            manufacturer=data.manufacturer,
            recorder_name=data.recorder_name,
            version=data.version,
        )
        self.db.add(recorder)
        await self.db.flush()
        await self.db.refresh(recorder)
        return recorder

    async def update(self, recorder_id: str, data: RecorderUpdate) -> Recorder | None:
        """Update an existing recorder.

        Args:
            recorder_id: Recorder's unique identifier
            data: Recorder update data

        Returns:
            Updated recorder instance or None if not found
        """
        recorder = await self.get_by_id(recorder_id)
        if not recorder:
            return None

        # Update only provided fields
        if data.manufacturer is not None:
            recorder.manufacturer = data.manufacturer
        if data.recorder_name is not None:
            recorder.recorder_name = data.recorder_name
        if data.version is not None:
            recorder.version = data.version

        await self.db.flush()
        await self.db.refresh(recorder)
        return recorder

    async def delete(self, recorder_id: str) -> bool:
        """Delete a recorder.

        Args:
            recorder_id: Recorder's unique identifier

        Returns:
            True if deleted, False if not found
        """
        recorder = await self.get_by_id(recorder_id)
        if not recorder:
            return False

        await self.db.delete(recorder)
        await self.db.flush()
        return True
