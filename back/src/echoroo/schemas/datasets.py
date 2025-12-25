"""Schemas for handling Datasets."""

import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, DirectoryPath, Field, model_validator

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.metadata import License, Project, Recorder, Site
from echoroo.schemas.recordings import Recording
from echoroo.models.dataset import VisibilityLevel
from echoroo.models.datetime_pattern import DatetimePatternType

__all__ = [
    "VisibilityLevel",
    "Dataset",
    "DatasetRecording",
    "DatasetCreate",
    "DatasetUpdate",
    "DatasetRecordingCreate",
    "FileState",
    "DatasetCandidate",
    "DatasetCandidateInfo",
    "DatasetDatetimePattern",
    "DatasetDatetimePatternUpdate",
    "DatasetRecordingSite",
    "DatasetRecordingCalendarBucket",
    "DatasetRecordingHeatmapCell",
    "DatasetRecordingTimelineSegment",
    "DatasetOverviewStats",
]


class DatasetCreate(BaseModel):
    """Schema for Dataset objects created by the user."""

    audio_dir: DirectoryPath
    """The path to the directory containing the audio files."""

    name: str = Field(..., min_length=1)
    """The name of the dataset."""

    description: str | None = Field(None)
    """The description of the dataset."""

    visibility: VisibilityLevel = VisibilityLevel.RESTRICTED
    """Visibility level for the dataset."""

    project_id: str = Field(...)
    """Project identifier associated with the dataset."""

    primary_site_id: str | None = Field(default=None)
    """Primary site identifier."""

    primary_recorder_id: str | None = Field(default=None)
    """Primary recorder identifier."""

    license_id: str | None = Field(default=None)
    """License identifier."""

    doi: str | None = Field(default=None)
    """Optional DOI reference."""

    note: str | None = Field(default=None)
    """Optional free-form note."""

    gain: float | None = Field(default=None)
    """Recorder gain in dB."""

    @model_validator(mode="after")
    def _ensure_project_binding(self):
        if not self.project_id:
            raise ValueError("project_id is required for dataset creation")
        return self


class Dataset(BaseSchema):
    """Schema for Dataset objects returned to the user."""

    uuid: UUID
    """The uuid of the dataset."""

    id: int
    """The database id of the dataset."""

    audio_dir: Path
    """The path to the directory containing the audio files."""

    name: str
    """The name of the dataset."""

    description: str | None
    """The description of the dataset."""

    recording_count: int = 0
    """The number of recordings in the dataset."""

    recording_start_date: datetime.datetime | None = None
    """Earliest recording datetime in the dataset."""

    recording_end_date: datetime.datetime | None = None
    """Latest recording datetime in the dataset."""

    visibility: VisibilityLevel
    """Visibility level for the dataset."""

    created_by_id: UUID
    """User who created the dataset."""

    project_id: str
    """Project identifier associated with the dataset."""

    primary_site_id: str | None = None
    """Primary site identifier."""

    primary_recorder_id: str | None = None
    """Primary recorder identifier."""

    license_id: str | None = None
    """License identifier."""

    doi: str | None = None
    """Optional DOI reference."""

    note: str | None = None
    """Optional free-form note."""

    gain: float | None = None
    """Recorder gain in dB."""

    project: Project | None = None
    """Hydrated project metadata."""

    primary_site: Site | None = None
    """Hydrated site metadata."""

    primary_recorder: Recorder | None = None
    """Hydrated recorder metadata."""

    license: License | None = None
    """Hydrated license metadata."""


class DatasetUpdate(BaseModel):
    """Schema for Dataset objects updated by the user."""

    audio_dir: DirectoryPath | None = None
    """The path to the directory containing the audio files."""

    name: str | None = Field(default=None, min_length=1)
    """The name of the dataset."""

    description: str | None = None
    """The description of the dataset."""

    visibility: VisibilityLevel | None = None
    """Updated visibility level."""

    project_id: str | None = None
    """Project identifier associated with the dataset."""

    primary_site_id: str | None = None
    """Primary site identifier."""

    primary_recorder_id: str | None = None
    """Primary recorder identifier."""

    license_id: str | None = None
    """License identifier."""

    doi: str | None = None
    """Optional DOI reference."""

    note: str | None = None
    """Optional free-form note."""

    gain: float | None = None
    """Recorder gain in dB."""


class FileState(Enum):
    """The state of a file in a dataset.

    Datasets can contain files that are not registered in the database. This
    can happen if the file was added to the dataset directory after the
    dataset was registered. Additionally, files can be registered in the
    database but missing from the dataset directory. This can happen if the
    file was removed from the dataset directory after the dataset was
    registered.

    The state of a file can be one of the following:

    - ``missing``: The file is not registered in the database and is missing.

    - ``registered``: The file is registered in the database and is present.

    - ``unregistered``: The file is not registered in the database but is
        present in the dataset directory.
    """

    MISSING = "missing"
    """If the recording is registered but the file is missing."""

    REGISTERED = "registered"
    """If the recording is registered and the file is present."""

    UNREGISTERED = "unregistered"
    """If the recording is not registered but the file is present."""


class DatasetFile(BaseModel):
    """Schema for DatasetFile objects returned to the user."""

    path: Path
    """The path to the file."""

    state: FileState
    """The state of the file."""


class DatasetRecordingCreate(BaseModel):
    """Schema for DatasetRecording objects created by the user."""

    path: Path
    """The path to the recording in the dataset directory."""


class DatasetRecording(BaseSchema):
    """Schema for DatasetRecording objects returned to the user."""

    recording: Recording
    """The uuid of the recording."""

    state: FileState = Field(default=FileState.REGISTERED)
    """The state of the file."""

    path: Path
    """The path to the recording in the dataset directory."""


class DatasetCandidate(BaseModel):
    """Schema for dataset directory candidates detected on disk."""

    name: str
    """Human-friendly label for the directory (folder name)."""

    relative_path: Path
    """Path relative to the configured audio directory."""

    absolute_path: Path
    """Absolute path to the directory on disk."""


class DatasetCandidateInfo(BaseModel):
    """Additional information about a dataset directory candidate."""

    relative_path: Path
    """Path relative to the configured audio directory."""

    absolute_path: Path
    """Absolute path to the directory on disk."""

    has_nested_directories: bool = False
    """True when the directory contains at least one subdirectory."""

    audio_file_count: int = 0
    """Number of audio files detected (wav/mp3/flac and similar)."""


class DatasetRecordingSite(BaseModel):
    """Aggregate information about recording sites for overview maps."""

    h3_index: str | None = None
    """H3 cell identifier if recordings inherit a site hex."""

    latitude: float
    """Latitude of the site centroid."""

    longitude: float
    """Longitude of the site centroid."""

    recording_count: int = 0
    """Number of recordings captured at this site."""

    label: str | None = None
    """Optional human friendly label (e.g. site name)."""


class DatasetRecordingCalendarBucket(BaseModel):
    """Daily recording counts for calendar visualizations."""

    date: datetime.date
    """Day represented by the bucket."""

    count: int = 0
    """Number of recordings captured on that day."""


class DatasetRecordingHeatmapCell(BaseModel):
    """Single cell in the date-time heatmap grid."""

    date: datetime.date
    """Day of the recording."""

    hour: int
    """Hour of day (0-23)."""

    count: int = 0
    """Number of recordings in this date-hour slot."""

    duration_minutes: float = 0.0
    """Total duration of recordings in minutes."""


class DatasetRecordingTimelineSegment(BaseModel):
    """A single recording segment for timeline visualization."""

    recording_uuid: str
    """UUID of the recording."""

    start: datetime.datetime
    """Start datetime of the recording."""

    end: datetime.datetime
    """End datetime of the recording (start + duration)."""

    path: str
    """File path of the recording."""


class DatasetOverviewStats(BaseModel):
    """Roll-up statistics for the dataset overview."""

    recording_sites: list[DatasetRecordingSite] = Field(default_factory=list)
    """Recording site aggregates for the overview map."""

    recording_calendar: list[DatasetRecordingCalendarBucket] = Field(default_factory=list)
    """Daily recording counts for the calendar heatmap."""

    recording_heatmap: list[DatasetRecordingHeatmapCell] = Field(default_factory=list)
    """Date-time heatmap cells for PAM schedule visualization."""

    recording_timeline: list[DatasetRecordingTimelineSegment] = Field(default_factory=list)
    """Timeline segments showing exact recording start/end times."""

    total_duration_seconds: float | None = None
    """Total duration of all recordings in seconds."""

    absolute_path: Path
    """Absolute path to the directory on disk."""

    has_nested_directories: bool = False
    """True when the directory contains at least one subdirectory."""

    audio_file_count: int = 0
    """Number of audio files detected (wav/mp3/flac and similar)."""


class DatasetDatetimePattern(BaseSchema):
    """Persisted datetime parsing configuration for a dataset."""

    dataset_id: int
    pattern_type: DatetimePatternType
    pattern: str
    sample_filename: str | None = None
    sample_result: datetime.datetime | None = None


class DatasetDatetimePatternUpdate(BaseModel):
    """Payload to define or update datetime parsing for a dataset."""

    pattern_type: DatetimePatternType = DatetimePatternType.STRPTIME
    pattern: str = Field(..., min_length=1)
    sample_filename: str | None = None
