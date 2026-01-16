"""Dataset service for business logic."""

from datetime import datetime
import re
from typing import Any, TypedDict
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility, DatetimeParseStatus
from echoroo.models.recording import Recording
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.site import SiteRepository
from echoroo.services.audio import AudioService


class DateRangeDict(TypedDict, total=False):
    """Date range dictionary."""
    start: datetime
    end: datetime


class RecordingByDateDict(TypedDict):
    """Recording by date dictionary."""
    date: str
    count: int
    duration: float


class RecordingByHourDict(TypedDict):
    """Recording by hour dictionary."""
    hour: int
    count: int


class DatasetStatisticsDict(TypedDict):
    """Dataset statistics dictionary."""
    recording_count: int
    total_duration: float
    date_range: DateRangeDict | None
    samplerate_distribution: dict[int, int]
    format_distribution: dict[str, int]
    recordings_by_date: list[RecordingByDateDict]
    recordings_by_hour: list[RecordingByHourDict]


class DatasetService:
    """Service for Dataset operations."""

    def __init__(
        self,
        dataset_repo: DatasetRepository,
        site_repo: SiteRepository,
        project_repo: ProjectRepository,
        recording_repo: RecordingRepository,
        audio_service: AudioService | None = None,
    ) -> None:
        """Initialize service with repositories.

        Args:
            dataset_repo: Dataset repository instance
            site_repo: Site repository instance
            project_repo: Project repository instance
            recording_repo: Recording repository instance
            audio_service: Audio service instance (optional)
        """
        self.dataset_repo = dataset_repo
        self.site_repo = site_repo
        self.project_repo = project_repo
        self.recording_repo = recording_repo
        self.audio_service = audio_service

    async def get_by_id(
        self, user_id: UUID, project_id: UUID, dataset_id: UUID
    ) -> Dataset:
        """Get dataset by ID.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            dataset_id: Dataset's UUID

        Returns:
            Dataset instance

        Raises:
            HTTPException: If access denied or dataset not found
        """
        # Check project access
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to project",
            )

        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        return dataset

    async def list_by_project(
        self,
        user_id: UUID,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
        site_id: UUID | None = None,
        status_filter: DatasetStatus | None = None,
        visibility: DatasetVisibility | None = None,
        search: str | None = None,
    ) -> tuple[list[Dataset], int]:
        """List datasets with pagination.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            site_id: Filter by site ID
            status_filter: Filter by status
            visibility: Filter by visibility
            search: Search in name and description

        Returns:
            Tuple of (list of datasets, total count)

        Raises:
            HTTPException: If access denied
        """
        # Check project access
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to project",
            )

        # Validate pagination
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        # Delegate to repository
        datasets, total = await self.dataset_repo.list_by_project(
            project_id, page, page_size, site_id, status_filter, visibility, search
        )

        return datasets, total

    async def create(
        self,
        user_id: UUID,
        project_id: UUID,
        site_id: UUID,
        name: str,
        audio_dir: str,
        description: str | None = None,
        visibility: DatasetVisibility = DatasetVisibility.PRIVATE,
        recorder_id: str | None = None,
        license_id: str | None = None,
        doi: str | None = None,
        gain: float | None = None,
        note: str | None = None,
        datetime_pattern: str | None = None,
        datetime_format: str | None = None,
    ) -> Dataset:
        """Create a new dataset.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            site_id: Site's UUID
            name: Dataset name
            audio_dir: Relative path to audio directory
            description: Dataset description
            visibility: Dataset visibility
            recorder_id: Recorder ID
            license_id: License ID
            doi: Digital Object Identifier
            gain: Recording gain in dB
            note: Internal notes
            datetime_pattern: Regex pattern for datetime extraction
            datetime_format: strftime format string

        Returns:
            Created dataset

        Raises:
            HTTPException: If not admin, site not found, or duplicate name
        """
        # Check admin access
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to create datasets",
            )

        # Verify site exists and belongs to project
        site = await self.site_repo.get_by_id(site_id)
        if not site or site.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site not found",
            )

        # Check unique name per project
        existing = await self.dataset_repo.get_by_project_and_name(project_id, name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dataset with this name already exists in project",
            )

        # Create dataset with PENDING status
        dataset = Dataset(
            project_id=project_id,
            site_id=site_id,
            created_by_id=user_id,
            name=name,
            description=description,
            audio_dir=audio_dir,
            visibility=visibility,
            status=DatasetStatus.PENDING,
            recorder_id=recorder_id,
            license_id=license_id,
            doi=doi,
            gain=gain,
            note=note,
            datetime_pattern=datetime_pattern,
            datetime_format=datetime_format,
        )

        created_dataset = await self.dataset_repo.create(dataset)
        return created_dataset

    async def update(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        name: str | None = None,
        description: str | None = None,
        visibility: DatasetVisibility | None = None,
        recorder_id: str | None = None,
        license_id: str | None = None,
        doi: str | None = None,
        gain: float | None = None,
        note: str | None = None,
        datetime_pattern: str | None = None,
        datetime_format: str | None = None,
    ) -> Dataset:
        """Update dataset.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            dataset_id: Dataset's UUID
            name: Dataset name
            description: Dataset description
            visibility: Dataset visibility
            recorder_id: Recorder ID
            license_id: License ID
            doi: Digital Object Identifier
            gain: Recording gain in dB
            note: Internal notes
            datetime_pattern: Regex pattern for datetime extraction
            datetime_format: strftime format string

        Returns:
            Updated dataset

        Raises:
            HTTPException: If not admin, dataset not found, or duplicate name
        """
        # Check admin access
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to update datasets",
            )

        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # Update fields if provided
        if name is not None and name != dataset.name:
            # Check for duplicate name
            existing = await self.dataset_repo.get_by_project_and_name(project_id, name)
            if existing and existing.id != dataset_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Dataset with this name already exists in project",
                )
            dataset.name = name

        if description is not None:
            dataset.description = description
        if visibility is not None:
            dataset.visibility = visibility
        if recorder_id is not None:
            dataset.recorder_id = recorder_id
        if license_id is not None:
            dataset.license_id = license_id
        if doi is not None:
            dataset.doi = doi
        if gain is not None:
            dataset.gain = gain
        if note is not None:
            dataset.note = note
        if datetime_pattern is not None:
            dataset.datetime_pattern = datetime_pattern
        if datetime_format is not None:
            dataset.datetime_format = datetime_format

        updated_dataset = await self.dataset_repo.update(dataset)
        return updated_dataset

    async def delete(
        self, user_id: UUID, project_id: UUID, dataset_id: UUID
    ) -> None:
        """Delete dataset and cascade to recordings.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            dataset_id: Dataset's UUID

        Raises:
            HTTPException: If not admin or dataset not found
        """
        # Check admin access
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to delete datasets",
            )

        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        await self.dataset_repo.delete(dataset_id)

    async def start_import(
        self,
        db: AsyncSession,
        dataset_id: UUID,
        datetime_pattern: str | None = None,
        datetime_format: str | None = None,
    ) -> bool:
        """Start importing recordings from audio_dir.

        Args:
            db: Database session
            dataset_id: Dataset's UUID
            datetime_pattern: Override regex pattern for datetime extraction
            datetime_format: Override strftime format string

        Returns:
            True if import started successfully, False otherwise
        """
        if not self.audio_service:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio service not configured",
            )

        # Get dataset
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset:
            return False

        try:
            # Update status to SCANNING
            await self.dataset_repo.update_import_status(
                dataset_id, DatasetStatus.SCANNING
            )
            await db.commit()

            # Use provided patterns or dataset defaults
            pattern = datetime_pattern or dataset.datetime_pattern
            format_str = datetime_format or dataset.datetime_format

            # Scan directory using audio_service
            audio_files = self.audio_service.scan_directory(dataset.audio_dir)
            total_files = len(audio_files)

            # Update total files and set status to PROCESSING
            await self.dataset_repo.update_import_status(
                dataset_id, DatasetStatus.PROCESSING, total_files=total_files
            )
            await db.commit()

            # Process each audio file
            recordings_to_create: list[Recording] = []
            processed_count = 0

            for file_path in audio_files:
                try:
                    # Check if already imported (by path)
                    existing = await self.recording_repo.get_by_dataset_and_path(
                        dataset_id, file_path
                    )
                    if existing:
                        processed_count += 1
                        continue

                    # Extract metadata
                    metadata = self.audio_service.extract_metadata(file_path)

                    # Parse datetime from filename
                    parsed_datetime, parse_error = self.parse_datetime_from_filename(
                        metadata.filename, pattern, format_str
                    )

                    # Determine parse status
                    if parsed_datetime:
                        parse_status = DatetimeParseStatus.SUCCESS
                    elif pattern and format_str:
                        parse_status = DatetimeParseStatus.FAILED
                    else:
                        parse_status = DatetimeParseStatus.PENDING

                    # Create recording
                    recording = Recording(
                        dataset_id=dataset_id,
                        filename=metadata.filename,
                        path=metadata.path,
                        hash=metadata.hash,
                        duration=metadata.duration,
                        samplerate=metadata.samplerate,
                        channels=metadata.channels,
                        bit_depth=metadata.bit_depth,
                        datetime=parsed_datetime,
                        datetime_parse_status=parse_status,
                        datetime_parse_error=parse_error,
                    )

                    recordings_to_create.append(recording)
                    processed_count += 1

                    # Batch insert every 100 recordings
                    if len(recordings_to_create) >= 100:
                        await self.recording_repo.create_many(recordings_to_create)
                        await self.dataset_repo.update_import_status(
                            dataset_id,
                            DatasetStatus.PROCESSING,
                            processed_files=processed_count,
                        )
                        await db.commit()
                        recordings_to_create.clear()

                except Exception as e:
                    # Log error but continue processing
                    print(f"Error processing {file_path}: {e}")
                    processed_count += 1
                    continue

            # Insert remaining recordings
            if recordings_to_create:
                await self.recording_repo.create_many(recordings_to_create)

            # Update status to COMPLETED
            await self.dataset_repo.update_import_status(
                dataset_id,
                DatasetStatus.COMPLETED,
                processed_files=processed_count,
            )
            await db.commit()

            return True

        except Exception as e:
            # Update status to FAILED
            await self.dataset_repo.update_import_status(
                dataset_id, DatasetStatus.FAILED, error=str(e)
            )
            await db.commit()
            return False

    async def rescan(self, db: AsyncSession, dataset_id: UUID) -> bool:
        """Rescan directory for new files.

        Args:
            db: Database session
            dataset_id: Dataset's UUID

        Returns:
            True if rescan completed successfully, False otherwise
        """
        if not self.audio_service:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio service not configured",
            )

        # Get dataset
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if not dataset:
            return False

        try:
            # Update status to SCANNING
            await self.dataset_repo.update_import_status(
                dataset_id, DatasetStatus.SCANNING
            )
            await db.commit()

            # Scan directory
            audio_files = self.audio_service.scan_directory(dataset.audio_dir)
            total_files = len(audio_files)

            # Update total files
            await self.dataset_repo.update_import_status(
                dataset_id, DatasetStatus.PROCESSING, total_files=total_files
            )
            await db.commit()

            # Process only new files (not already in database)
            recordings_to_create: list[Recording] = []
            new_count = 0

            for file_path in audio_files:
                try:
                    # Check if already imported
                    existing = await self.recording_repo.get_by_dataset_and_path(
                        dataset_id, file_path
                    )
                    if existing:
                        continue

                    # Extract metadata
                    metadata = self.audio_service.extract_metadata(file_path)

                    # Parse datetime from filename
                    parsed_datetime, parse_error = self.parse_datetime_from_filename(
                        metadata.filename,
                        dataset.datetime_pattern,
                        dataset.datetime_format,
                    )

                    # Determine parse status
                    if parsed_datetime:
                        parse_status = DatetimeParseStatus.SUCCESS
                    elif dataset.datetime_pattern and dataset.datetime_format:
                        parse_status = DatetimeParseStatus.FAILED
                    else:
                        parse_status = DatetimeParseStatus.PENDING

                    # Create recording
                    recording = Recording(
                        dataset_id=dataset_id,
                        filename=metadata.filename,
                        path=metadata.path,
                        hash=metadata.hash,
                        duration=metadata.duration,
                        samplerate=metadata.samplerate,
                        channels=metadata.channels,
                        bit_depth=metadata.bit_depth,
                        datetime=parsed_datetime,
                        datetime_parse_status=parse_status,
                        datetime_parse_error=parse_error,
                    )

                    recordings_to_create.append(recording)
                    new_count += 1

                    # Batch insert every 100 recordings
                    if len(recordings_to_create) >= 100:
                        await self.recording_repo.create_many(recordings_to_create)
                        await db.commit()
                        recordings_to_create.clear()

                except Exception as e:
                    print(f"Error processing {file_path}: {e}")
                    continue

            # Insert remaining recordings
            if recordings_to_create:
                await self.recording_repo.create_many(recordings_to_create)

            # Update status to COMPLETED
            current_count = await self.recording_repo.count_by_dataset(dataset_id)
            await self.dataset_repo.update_import_status(
                dataset_id,
                DatasetStatus.COMPLETED,
                processed_files=current_count,
            )
            await db.commit()

            return True

        except Exception as e:
            # Update status to FAILED
            await self.dataset_repo.update_import_status(
                dataset_id, DatasetStatus.FAILED, error=str(e)
            )
            await db.commit()
            return False

    def get_import_status(self, dataset: Dataset) -> dict[str, DatasetStatus | int | float | str | None]:
        """Get import progress status.

        Args:
            dataset: Dataset instance

        Returns:
            Dictionary with status information
        """
        progress = 0.0
        if dataset.total_files > 0:
            progress = (dataset.processed_files / dataset.total_files) * 100

        return {
            "status": dataset.status,
            "total_files": dataset.total_files,
            "processed_files": dataset.processed_files,
            "progress_percent": progress,
            "error": dataset.processing_error,
        }

    def parse_datetime_from_filename(
        self, filename: str, pattern: str | None, format_str: str | None
    ) -> tuple[datetime | None, str | None]:
        """Extract datetime from filename using pattern/format.

        Args:
            filename: Filename to parse
            pattern: Regex pattern to extract datetime string
            format_str: strftime format string

        Returns:
            Tuple of (parsed datetime or None, error message or None)
        """
        if not pattern or not format_str:
            return None, None

        try:
            match = re.search(pattern, filename)
            if not match:
                return None, "Pattern did not match"

            datetime_str = match.group(0)
            parsed = datetime.strptime(datetime_str, format_str)
            return parsed, None
        except Exception as e:
            return None, str(e)

    def test_datetime_pattern(
        self, filename: str, pattern: str, format_str: str
    ) -> dict[str, bool | str | None]:
        """Test datetime extraction pattern.

        Args:
            filename: Filename to test
            pattern: Regex pattern
            format_str: strftime format string

        Returns:
            Dictionary with test results
        """
        dt, error = self.parse_datetime_from_filename(filename, pattern, format_str)
        return {
            "success": dt is not None,
            "parsed_datetime": dt.isoformat() if dt else None,
            "error": error,
        }

    async def get_statistics(
        self, db: AsyncSession, dataset_id: UUID
    ) -> DatasetStatisticsDict:
        """Get dataset statistics.

        Args:
            db: Database session
            dataset_id: Dataset's UUID

        Returns:
            Dictionary with statistics
        """
        # Get recording count and total duration
        recording_count = await self.recording_repo.count_by_dataset(dataset_id)
        total_duration = await self.recording_repo.get_total_duration_by_dataset(dataset_id)

        # Get date range
        date_range_query = select(
            func.min(Recording.datetime).label("start"),
            func.max(Recording.datetime).label("end"),
        ).where(Recording.dataset_id == dataset_id, Recording.datetime.isnot(None))

        result = await db.execute(date_range_query)
        date_range_row = result.one_or_none()
        date_range: DateRangeDict | None = None
        if date_range_row and date_range_row.start and date_range_row.end:
            date_range = DateRangeDict(
                start=date_range_row.start,
                end=date_range_row.end,
            )

        # Get samplerate distribution
        samplerate_query = select(
            Recording.samplerate,
            func.count(Recording.id).label("count"),
        ).where(Recording.dataset_id == dataset_id).group_by(Recording.samplerate)

        samplerate_result = await db.execute(samplerate_query)
        samplerate_distribution: dict[int, int] = {}
        for row in samplerate_result:
            samplerate_distribution[row.samplerate] = row.count  # type: ignore[assignment]

        # Get format distribution (from filename extension)
        format_query = select(
            func.substring(Recording.filename, r'\.([^.]+)$').label("format"),
            func.count(Recording.id).label("count"),
        ).where(Recording.dataset_id == dataset_id).group_by("format")

        format_result = await db.execute(format_query)
        format_distribution: dict[str, int] = {}
        for row in format_result:
            if row.format:
                format_distribution[row.format] = row.count  # type: ignore[assignment]

        # Get recordings by date
        recordings_by_date_query = select(
            func.date(Recording.datetime).label("date"),
            func.count(Recording.id).label("count"),
            func.sum(Recording.duration).label("duration"),
        ).where(
            Recording.dataset_id == dataset_id,
            Recording.datetime.isnot(None),
        ).group_by("date").order_by("date")

        recordings_by_date_result = await db.execute(recordings_by_date_query)
        recordings_by_date: list[RecordingByDateDict] = []
        for row in recordings_by_date_result:
            recordings_by_date.append(
                RecordingByDateDict(
                    date=str(row.date),
                    count=row.count,  # type: ignore[typeddict-item]
                    duration=float(row.duration or 0),
                )
            )

        # Get recordings by hour
        recordings_by_hour_query = select(
            func.extract("hour", Recording.datetime).label("hour"),
            func.count(Recording.id).label("count"),
        ).where(
            Recording.dataset_id == dataset_id,
            Recording.datetime.isnot(None),
        ).group_by("hour").order_by("hour")

        recordings_by_hour_result = await db.execute(recordings_by_hour_query)
        recordings_by_hour: list[RecordingByHourDict] = []
        for row in recordings_by_hour_result:
            recordings_by_hour.append(
                RecordingByHourDict(
                    hour=int(row.hour),
                    count=row.count,  # type: ignore[typeddict-item]
                )
            )

        return DatasetStatisticsDict(
            recording_count=recording_count,
            total_duration=total_duration,
            date_range=date_range,
            samplerate_distribution=samplerate_distribution,
            format_distribution=format_distribution,
            recordings_by_date=recordings_by_date,
            recordings_by_hour=recordings_by_hour,
        )
