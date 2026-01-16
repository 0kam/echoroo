"""Clip repository for database operations."""

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.clip import Clip


class ClipRepository:
    """Repository for Clip entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, clip_id: UUID) -> Clip | None:
        """Get clip by ID with recording relationship loaded.

        Args:
            clip_id: Clip's UUID

        Returns:
            Clip instance or None if not found
        """
        result = await self.db.execute(
            select(Clip).where(Clip.id == clip_id).options(selectinload(Clip.recording))
        )
        return result.scalar_one_or_none()

    async def get_by_recording_and_time(
        self, recording_id: UUID, start_time: float, end_time: float
    ) -> Clip | None:
        """Get clip by recording ID and time range.

        Args:
            recording_id: Recording's UUID
            start_time: Start time in seconds
            end_time: End time in seconds

        Returns:
            Clip instance or None if not found
        """
        result = await self.db.execute(
            select(Clip).where(
                Clip.recording_id == recording_id,
                Clip.start_time == start_time,
                Clip.end_time == end_time,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_recording(
        self,
        recording_id: UUID,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "start_time",
        sort_order: str = "asc",
    ) -> tuple[list[Clip], int]:
        """List clips for a recording with pagination.

        Args:
            recording_id: Recording's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            sort_by: Sort column name
            sort_order: Sort order (asc/desc)

        Returns:
            Tuple of (list of clips, total count)
        """
        # Get total count
        count_result = await self.db.execute(
            select(func.count()).select_from(Clip).where(Clip.recording_id == recording_id)
        )
        total: int = count_result.scalar_one()

        # Build query with sorting
        query = select(Clip).where(Clip.recording_id == recording_id)
        sort_column = getattr(Clip, sort_by, Clip.start_time)
        if sort_order == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        clips = list(result.scalars().all())

        return clips, total

    async def create(self, clip: Clip) -> Clip:
        """Create a new clip.

        Args:
            clip: Clip instance to create

        Returns:
            Created clip instance
        """
        self.db.add(clip)
        await self.db.flush()
        await self.db.refresh(clip)
        return clip

    async def create_many(self, clips: list[Clip]) -> list[Clip]:
        """Create multiple clips in batch.

        Args:
            clips: List of Clip instances to create

        Returns:
            List of created clip instances
        """
        self.db.add_all(clips)
        await self.db.flush()
        return clips

    async def update(self, clip: Clip) -> Clip:
        """Update an existing clip.

        Args:
            clip: Clip instance to update

        Returns:
            Updated clip instance
        """
        await self.db.flush()
        await self.db.refresh(clip)
        return clip

    async def delete(self, clip_id: UUID) -> None:
        """Delete a clip by ID.

        Args:
            clip_id: Clip's UUID
        """
        await self.db.execute(delete(Clip).where(Clip.id == clip_id))
        await self.db.flush()

    async def delete_by_recording(self, recording_id: UUID) -> None:
        """Delete all clips for a recording.

        Args:
            recording_id: Recording's UUID
        """
        await self.db.execute(delete(Clip).where(Clip.recording_id == recording_id))
        await self.db.flush()

    async def count_by_recording(self, recording_id: UUID) -> int:
        """Count clips in a recording.

        Args:
            recording_id: Recording's UUID

        Returns:
            Number of clips
        """
        result = await self.db.execute(
            select(func.count()).select_from(Clip).where(Clip.recording_id == recording_id)
        )
        return result.scalar_one()
