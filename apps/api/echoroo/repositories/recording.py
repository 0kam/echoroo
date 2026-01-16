"""Recording repository for database operations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.recording import Recording


class RecordingRepository:
    """Repository for Recording entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, recording_id: UUID) -> Recording | None:
        """Get recording by ID with relationships loaded.

        Args:
            recording_id: Recording's UUID

        Returns:
            Recording instance or None if not found
        """
        result = await self.db.execute(
            select(Recording)
            .where(Recording.id == recording_id)
            .options(selectinload(Recording.dataset))
        )
        return result.scalar_one_or_none()

    async def get_by_dataset_and_path(self, dataset_id: UUID, path: str) -> Recording | None:
        """Get recording by dataset ID and path.

        Args:
            dataset_id: Dataset's UUID
            path: Recording path

        Returns:
            Recording instance or None if not found
        """
        result = await self.db.execute(
            select(Recording).where(Recording.dataset_id == dataset_id, Recording.path == path)
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, hash_value: str) -> Recording | None:
        """Get recording by hash.

        Args:
            hash_value: MD5 hash value

        Returns:
            Recording instance or None if not found
        """
        result = await self.db.execute(select(Recording).where(Recording.hash == hash_value))
        return result.scalar_one_or_none()

    async def list_by_dataset(
        self,
        dataset_id: UUID,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        datetime_from: datetime | None = None,
        datetime_to: datetime | None = None,
        samplerate: int | None = None,
        sort_by: str = "datetime",
        sort_order: str = "desc",
    ) -> tuple[list[Recording], int]:
        """List recordings for a dataset with pagination and filters.

        Args:
            dataset_id: Dataset's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            search: Search in filename
            datetime_from: Filter from datetime
            datetime_to: Filter to datetime
            samplerate: Filter by samplerate
            sort_by: Sort column name
            sort_order: Sort order (asc/desc)

        Returns:
            Tuple of (list of recordings, total count)
        """
        query = select(Recording).where(Recording.dataset_id == dataset_id)

        # Apply filters
        if search:
            query = query.where(Recording.filename.ilike(f"%{search}%"))
        if datetime_from:
            query = query.where(Recording.datetime >= datetime_from)
        if datetime_to:
            query = query.where(Recording.datetime <= datetime_to)
        if samplerate:
            query = query.where(Recording.samplerate == samplerate)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total: int = count_result.scalar_one()

        # Apply sorting
        sort_column = getattr(Recording, sort_by, Recording.datetime)
        if sort_order == "asc":
            query = query.order_by(sort_column.asc())
        else:
            query = query.order_by(sort_column.desc())

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        recordings = list(result.scalars().all())

        return recordings, total

    async def search_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        site_id: UUID | None = None,
        dataset_id: UUID | None = None,
        datetime_from: datetime | None = None,
        datetime_to: datetime | None = None,
    ) -> tuple[list[Recording], int]:
        """Search recordings across all datasets in a project.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            search: Search in filename
            site_id: Filter by site ID
            dataset_id: Filter by dataset ID
            datetime_from: Filter from datetime
            datetime_to: Filter to datetime

        Returns:
            Tuple of (list of recordings, total count)
        """
        from echoroo.models.dataset import Dataset

        query = (
            select(Recording)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
        )

        # Apply filters
        if search:
            query = query.where(Recording.filename.ilike(f"%{search}%"))
        if site_id:
            query = query.where(Dataset.site_id == site_id)
        if dataset_id:
            query = query.where(Recording.dataset_id == dataset_id)
        if datetime_from:
            query = query.where(Recording.datetime >= datetime_from)
        if datetime_to:
            query = query.where(Recording.datetime <= datetime_to)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total: int = count_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.order_by(Recording.datetime.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        recordings = list(result.scalars().all())

        return recordings, total

    async def create(self, recording: Recording) -> Recording:
        """Create a new recording.

        Args:
            recording: Recording instance to create

        Returns:
            Created recording instance
        """
        self.db.add(recording)
        await self.db.flush()
        await self.db.refresh(recording)
        return recording

    async def create_many(self, recordings: list[Recording]) -> list[Recording]:
        """Create multiple recordings in batch.

        Args:
            recordings: List of Recording instances to create

        Returns:
            List of created recording instances
        """
        self.db.add_all(recordings)
        await self.db.flush()
        return recordings

    async def update(self, recording: Recording) -> Recording:
        """Update an existing recording.

        Args:
            recording: Recording instance to update

        Returns:
            Updated recording instance
        """
        await self.db.flush()
        await self.db.refresh(recording)
        return recording

    async def delete(self, recording_id: UUID) -> None:
        """Delete a recording by ID.

        Args:
            recording_id: Recording's UUID
        """
        await self.db.execute(delete(Recording).where(Recording.id == recording_id))
        await self.db.flush()

    async def count_by_dataset(self, dataset_id: UUID) -> int:
        """Count recordings in a dataset.

        Args:
            dataset_id: Dataset's UUID

        Returns:
            Number of recordings
        """
        result = await self.db.execute(
            select(func.count()).select_from(Recording).where(Recording.dataset_id == dataset_id)
        )
        return result.scalar_one()

    async def get_total_duration_by_dataset(self, dataset_id: UUID) -> float:
        """Get total duration of recordings in a dataset.

        Args:
            dataset_id: Dataset's UUID

        Returns:
            Total duration in seconds
        """
        result = await self.db.execute(
            select(func.sum(Recording.duration)).where(Recording.dataset_id == dataset_id)
        )
        return result.scalar_one() or 0.0
