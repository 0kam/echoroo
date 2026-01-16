"""Recording service for business logic."""

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.recording import Recording
from echoroo.repositories.clip import ClipRepository
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.services.audio import AudioService


class RecordingService:
    """Service for Recording operations."""

    def __init__(self, db: AsyncSession, audio_service: AudioService | None = None) -> None:
        """Initialize service with database session.

        Args:
            db: Database session
            audio_service: Audio service instance (optional)
        """
        self.db = db
        self.repo = RecordingRepository(db)
        self.dataset_repo = DatasetRepository(db)
        self.clip_repo = ClipRepository(db)
        self.audio_service = audio_service

    async def get_by_id(self, recording_id: UUID) -> Recording | None:
        """Get recording by ID.

        Args:
            recording_id: Recording's UUID

        Returns:
            Recording instance or None if not found
        """
        return await self.repo.get_by_id(recording_id)

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
        """List recordings for a dataset.

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
        return await self.repo.list_by_dataset(
            dataset_id, page, page_size, search, datetime_from, datetime_to, samplerate, sort_by, sort_order
        )

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
        return await self.repo.search_by_project(
            project_id, page, page_size, search, site_id, dataset_id, datetime_from, datetime_to
        )

    async def update(
        self, recording_id: UUID, time_expansion: float | None = None, note: str | None = None
    ) -> Recording | None:
        """Update recording fields (time_expansion, note).

        Args:
            recording_id: Recording's UUID
            time_expansion: Time expansion factor
            note: User notes

        Returns:
            Updated recording instance or None if not found
        """
        recording = await self.repo.get_by_id(recording_id)
        if not recording:
            return None

        if time_expansion is not None:
            recording.time_expansion = time_expansion
        if note is not None:
            recording.note = note

        return await self.repo.update(recording)

    async def delete(self, recording_id: UUID) -> bool:
        """Delete recording (cascade deletes clips).

        Args:
            recording_id: Recording's UUID

        Returns:
            True if deleted, False if not found
        """
        recording = await self.repo.get_by_id(recording_id)
        if not recording:
            return False

        await self.repo.delete(recording_id)
        return True

    def get_effective_duration(self, recording: Recording) -> float:
        """Calculate effective duration considering time expansion.

        Args:
            recording: Recording instance

        Returns:
            Effective duration in seconds
        """
        return recording.duration * recording.time_expansion

    def is_ultrasonic(self, recording: Recording) -> bool:
        """Check if recording is likely ultrasonic (samplerate > 96kHz).

        Args:
            recording: Recording instance

        Returns:
            True if samplerate > 96000 Hz
        """
        return recording.samplerate > 96000
