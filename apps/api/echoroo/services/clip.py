"""Clip service for business logic."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.clip import Clip
from echoroo.repositories.clip import ClipRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.services.audio import AudioService


class ClipService:
    """Service for Clip operations."""

    def __init__(self, db: AsyncSession, audio_service: AudioService | None = None) -> None:
        """Initialize service with database session.

        Args:
            db: Database session
            audio_service: Audio service instance (optional)
        """
        self.db = db
        self.repo = ClipRepository(db)
        self.recording_repo = RecordingRepository(db)
        self.audio_service = audio_service

    async def get_by_id(self, clip_id: UUID) -> Clip | None:
        """Get clip by ID.

        Args:
            clip_id: Clip's UUID

        Returns:
            Clip instance or None if not found
        """
        return await self.repo.get_by_id(clip_id)

    async def list_by_recording(
        self,
        recording_id: UUID,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "start_time",
        sort_order: str = "asc",
    ) -> tuple[list[Clip], int]:
        """List clips for a recording.

        Args:
            recording_id: Recording's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            sort_by: Sort column name
            sort_order: Sort order (asc/desc)

        Returns:
            Tuple of (list of clips, total count)
        """
        return await self.repo.list_by_recording(
            recording_id, page, page_size, sort_by, sort_order
        )

    async def create(
        self,
        recording_id: UUID,
        start_time: float,
        end_time: float,
        note: str | None = None,
    ) -> Clip:
        """Create a new clip.

        Args:
            recording_id: Recording's UUID
            start_time: Start time in seconds
            end_time: End time in seconds
            note: User notes (optional)

        Returns:
            Created clip instance

        Raises:
            ValueError: If validation fails
        """
        # Validate recording exists
        recording = await self.recording_repo.get_by_id(recording_id)
        if not recording:
            raise ValueError("Recording not found")

        # Validate time range
        if start_time < 0:
            raise ValueError("Start time must be non-negative")
        if end_time <= start_time:
            raise ValueError("End time must be greater than start time")
        if end_time > recording.duration:
            raise ValueError("End time exceeds recording duration")

        # Check for overlapping clips (prevent duplicates)
        existing = await self.repo.get_by_recording_and_time(recording_id, start_time, end_time)
        if existing:
            raise ValueError("Clip with same time range already exists")

        clip = Clip(
            recording_id=recording_id,
            start_time=start_time,
            end_time=end_time,
            note=note,
        )
        return await self.repo.create(clip)

    async def update(
        self,
        clip_id: UUID,
        start_time: float | None = None,
        end_time: float | None = None,
        note: str | None = None,
    ) -> Clip | None:
        """Update clip.

        Args:
            clip_id: Clip's UUID
            start_time: New start time (optional)
            end_time: New end time (optional)
            note: New note (optional)

        Returns:
            Updated clip instance or None if not found

        Raises:
            ValueError: If validation fails
        """
        clip = await self.repo.get_by_id(clip_id)
        if not clip:
            return None

        if start_time is not None:
            clip.start_time = start_time
        if end_time is not None:
            clip.end_time = end_time
        if note is not None:
            clip.note = note

        # Validate time range
        if clip.end_time <= clip.start_time:
            raise ValueError("End time must be greater than start time")

        return await self.repo.update(clip)

    async def delete(self, clip_id: UUID) -> bool:
        """Delete clip.

        Args:
            clip_id: Clip's UUID

        Returns:
            True if deleted, False if not found
        """
        clip = await self.repo.get_by_id(clip_id)
        if not clip:
            return False
        await self.repo.delete(clip_id)
        return True

    def get_duration(self, clip: Clip) -> float:
        """Get clip duration in seconds.

        Args:
            clip: Clip instance

        Returns:
            Duration in seconds
        """
        return clip.end_time - clip.start_time

    async def generate_clips(
        self,
        recording_id: UUID,
        clip_length: float,
        overlap: float = 0.0,
        start_time: float = 0.0,
        end_time: float | None = None,
    ) -> list[Clip]:
        """Auto-generate clips from recording.

        Args:
            recording_id: Recording's UUID
            clip_length: Duration of each clip in seconds
            overlap: Overlap between clips in seconds (default 0)
            start_time: Start generating from this time
            end_time: Stop generating at this time (None = end of recording)

        Returns:
            List of created clips

        Raises:
            ValueError: If validation fails
        """
        recording = await self.recording_repo.get_by_id(recording_id)
        if not recording:
            raise ValueError("Recording not found")

        if clip_length <= 0:
            raise ValueError("Clip length must be positive")
        if overlap < 0 or overlap >= clip_length:
            raise ValueError("Overlap must be between 0 and clip_length")

        actual_end = end_time if end_time is not None else recording.duration
        if actual_end > recording.duration:
            actual_end = recording.duration

        # Generate clip boundaries
        clips_to_create: list[Clip] = []
        current_start = start_time
        step = clip_length - overlap

        while current_start + clip_length <= actual_end:
            clips_to_create.append(
                Clip(
                    recording_id=recording_id,
                    start_time=current_start,
                    end_time=current_start + clip_length,
                )
            )
            current_start += step

        # Batch create
        if clips_to_create:
            return await self.repo.create_many(clips_to_create)
        return []
