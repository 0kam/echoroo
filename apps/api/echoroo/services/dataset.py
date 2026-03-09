"""Dataset service for business logic."""

import re
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility
from echoroo.models.recording import Recording
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.site import SiteRepository


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
    ) -> None:
        """Initialize service with repositories.

        Args:
            dataset_repo: Dataset repository instance
            site_repo: Site repository instance
            project_repo: Project repository instance
            recording_repo: Recording repository instance
        """
        self.dataset_repo = dataset_repo
        self.site_repo = site_repo
        self.project_repo = project_repo
        self.recording_repo = recording_repo

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
        description: str | None = None,
        visibility: DatasetVisibility = DatasetVisibility.PRIVATE,
        recorder_id: str | None = None,
        license_id: str | None = None,
        doi: str | None = None,
        gain: float | None = None,
        note: str | None = None,
        datetime_pattern: str | None = None,
        datetime_format: str | None = None,
        datetime_timezone: str | None = None,
    ) -> Dataset:
        """Create a new dataset.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            site_id: Site's UUID
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
            datetime_timezone: IANA timezone for datetime parsing

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
            visibility=visibility,
            status=DatasetStatus.PENDING,
            recorder_id=recorder_id,
            license_id=license_id,
            doi=doi,
            gain=gain,
            note=note,
            datetime_pattern=datetime_pattern,
            datetime_format=datetime_format,
            datetime_timezone=datetime_timezone,
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
        datetime_timezone: str | None = None,
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
            datetime_timezone: IANA timezone for datetime parsing

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
        if datetime_timezone is not None:
            dataset.datetime_timezone = datetime_timezone

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
        self, filename: str, pattern: str | None, format_str: str | None, timezone: str | None = None
    ) -> tuple[datetime | None, str | None]:
        """Extract datetime from filename using pattern/format.

        Args:
            filename: Filename to parse
            pattern: Regex pattern to extract datetime string
            format_str: strftime format string
            timezone: Optional IANA timezone string (e.g., 'Asia/Tokyo')

        Returns:
            Tuple of (parsed datetime or None, error message or None)
        """
        if not pattern or not format_str:
            return None, None

        # Guard against excessively long patterns (ReDoS mitigation)
        if len(pattern) > 200:
            return None, "Regex pattern too long (max 200 characters)"

        try:
            match = re.search(pattern, filename)
            if not match:
                return None, "Pattern did not match"

            datetime_str = match.group(0)
            parsed = datetime.strptime(datetime_str, format_str)
            if timezone:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(timezone)
                parsed = parsed.replace(tzinfo=tz)
            return parsed, None
        except Exception as e:
            return None, str(e)

    def test_datetime_pattern(
        self, filename: str, pattern: str, format_str: str, timezone: str | None = None
    ) -> dict[str, bool | str | None]:
        """Test datetime extraction pattern.

        Args:
            filename: Filename to test
            pattern: Regex pattern
            format_str: strftime format string
            timezone: Optional IANA timezone string (e.g., 'Asia/Tokyo')

        Returns:
            Dictionary with test results
        """
        dt, error = self.parse_datetime_from_filename(filename, pattern, format_str, timezone)
        return {
            "success": dt is not None,
            "parsed_datetime": dt.isoformat() if dt else None,
            "error": error,
        }

    async def get_datetime_config(self, dataset_id: UUID) -> dict[str, object]:
        """Get current datetime config with sample filenames and parse summary.

        Args:
            dataset_id: Dataset's UUID

        Returns:
            Dictionary with datetime_pattern, datetime_format, datetime_timezone,
            sample_filenames, and parse_summary
        """
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        sample_filenames = await self.recording_repo.get_sample_filenames(dataset_id)
        parse_summary = await self.recording_repo.get_datetime_parse_summary(dataset_id)

        return {
            "datetime_pattern": dataset.datetime_pattern if dataset else None,
            "datetime_format": dataset.datetime_format if dataset else None,
            "datetime_timezone": dataset.datetime_timezone if dataset else None,
            "sample_filenames": sample_filenames,
            "parse_summary": parse_summary,
        }

    # Known datetime patterns ordered by commonality
    _KNOWN_PATTERNS: list[dict[str, str]] = [
        {"name": "AudioMoth / Wildlife Acoustics", "pattern": r"(\d{8}_\d{6})", "format": "%Y%m%d_%H%M%S"},
        {"name": "AudioMoth (T separator)", "pattern": r"(\d{8}T\d{6})", "format": "%Y%m%dT%H%M%S"},
        {"name": "ISO 8601", "pattern": r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", "format": "%Y-%m-%dT%H:%M:%S"},
        {"name": "ISO 8601 (no T)", "pattern": r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})", "format": "%Y-%m-%d_%H-%M-%S"},
        {"name": "Compact", "pattern": r"(\d{14})", "format": "%Y%m%d%H%M%S"},
        {"name": "Underscore separated", "pattern": r"(\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2})", "format": "%Y_%m_%d_%H_%M_%S"},
        {"name": "Hyphen separated", "pattern": r"(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})", "format": "%Y-%m-%d-%H-%M-%S"},
    ]

    async def auto_detect_datetime_pattern(self, dataset_id: UUID) -> dict[str, object]:
        """Try known patterns against sample filenames and return the best match.

        Tests each known pattern against the dataset's sample filenames and
        returns the first pattern where >= 80% of filenames parse successfully.

        Args:
            dataset_id: Dataset's UUID

        Returns:
            Dictionary with detected, pattern, format_str, preset_name, and results
        """
        sample_filenames = await self.recording_repo.get_sample_filenames(dataset_id)

        if not sample_filenames:
            return {
                "detected": False,
                "pattern": None,
                "format_str": None,
                "preset_name": None,
                "results": [],
            }

        for preset in self._KNOWN_PATTERNS:
            results = await self.test_datetime_pattern_bulk(
                sample_filenames, preset["pattern"], preset["format"]
            )
            success_count = sum(1 for r in results if r["success"])
            if len(sample_filenames) > 0 and success_count / len(sample_filenames) >= 0.8:
                return {
                    "detected": True,
                    "pattern": preset["pattern"],
                    "format_str": preset["format"],
                    "preset_name": preset["name"],
                    "results": results,
                }

        return {
            "detected": False,
            "pattern": None,
            "format_str": None,
            "preset_name": None,
            "results": [],
        }

    async def test_datetime_pattern_bulk(
        self, filenames: list[str], pattern: str, format_str: str, timezone: str | None = None
    ) -> list[dict[str, object]]:
        """Test a pattern against multiple filenames.

        Args:
            filenames: List of filenames to test
            pattern: Regex pattern for datetime extraction
            format_str: strptime format string
            timezone: Optional IANA timezone string (e.g., 'Asia/Tokyo')

        Returns:
            List of result dicts with filename, success, parsed_datetime, error
        """
        results: list[dict[str, object]] = []
        for filename in filenames:
            result = self.test_datetime_pattern(filename, pattern, format_str, timezone)
            results.append(
                {
                    "filename": filename,
                    "success": result["success"],
                    "parsed_datetime": result["parsed_datetime"],
                    "error": result["error"],
                }
            )
        return results

    async def apply_datetime_pattern(
        self, dataset_id: UUID, pattern: str, format_str: str, timezone: str | None = None
    ) -> tuple[str, int]:
        """Save datetime pattern to dataset and dispatch a Celery task to re-parse all recordings.

        Args:
            dataset_id: Dataset's UUID
            pattern: Regex pattern for datetime extraction
            format_str: strptime format string
            timezone: Optional IANA timezone string (e.g., 'Asia/Tokyo')

        Returns:
            Tuple of (task_id, total_recordings)
        """
        from echoroo.workers.upload_tasks import reparse_recording_datetimes

        # Update dataset datetime pattern, format, and timezone
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is not None:
            dataset.datetime_pattern = pattern
            dataset.datetime_format = format_str
            dataset.datetime_timezone = timezone
            await self.dataset_repo.update(dataset)

        # Get total recording count
        total_recordings = await self.recording_repo.count_by_dataset(dataset_id)

        # Dispatch Celery task
        task = reparse_recording_datetimes.delay(str(dataset_id), pattern, format_str, timezone)

        return str(task.id), total_recordings

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
