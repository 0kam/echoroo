"""Dataset request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import DatasetStatus, DatasetVisibility


class RecorderSummary(BaseModel):
    """Recorder summary for dataset responses."""

    id: str
    manufacturer: str
    recorder_name: str

    model_config = {"from_attributes": True}


class LicenseSummary(BaseModel):
    """License summary for dataset responses."""

    id: str
    name: str
    short_name: str

    model_config = {"from_attributes": True}


class UserSummary(BaseModel):
    """User summary for dataset responses."""

    id: UUID
    email: str
    display_name: str | None = None

    model_config = {"from_attributes": True}


class SiteSummary(BaseModel):
    """Site summary for dataset responses."""

    id: UUID
    name: str
    h3_index: str

    model_config = {"from_attributes": True}


class DatasetCreate(BaseModel):
    """Dataset creation request schema."""

    site_id: UUID = Field(..., description="Parent site ID (required)")
    name: str = Field(..., min_length=1, max_length=200, description="Dataset name")
    description: str | None = Field(None, description="Dataset description")
    audio_dir: str = Field(..., description="Relative path to audio directory")
    visibility: DatasetVisibility = Field(default=DatasetVisibility.PRIVATE, description="Dataset visibility")
    recorder_id: str | None = Field(None, description="Recording device ID")
    license_id: str | None = Field(None, description="Content license ID")
    doi: str | None = Field(None, description="Digital Object Identifier")
    gain: float | None = Field(None, ge=-100, le=100, description="Recording gain in dB")
    note: str | None = Field(None, description="Internal notes")
    datetime_pattern: str | None = Field(None, description="Regex pattern for datetime extraction")
    datetime_format: str | None = Field(None, description="strftime format string")


class DatasetUpdate(BaseModel):
    """Dataset update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Dataset name")
    description: str | None = Field(None, description="Dataset description")
    visibility: DatasetVisibility | None = Field(None, description="Dataset visibility")
    recorder_id: str | None = Field(None, description="Recording device ID")
    license_id: str | None = Field(None, description="Content license ID")
    doi: str | None = Field(None, description="Digital Object Identifier")
    gain: float | None = Field(None, ge=-100, le=100, description="Recording gain in dB")
    note: str | None = Field(None, description="Internal notes")
    datetime_pattern: str | None = Field(None, description="Regex pattern for datetime extraction")
    datetime_format: str | None = Field(None, description="strftime format string")


class DatasetResponse(BaseModel):
    """Dataset response schema."""

    id: UUID
    site_id: UUID
    project_id: UUID
    recorder_id: str | None
    license_id: str | None
    created_by_id: UUID
    name: str
    description: str | None
    audio_dir: str
    visibility: DatasetVisibility
    status: DatasetStatus
    doi: str | None
    gain: float | None
    note: str | None
    total_files: int
    processed_files: int
    processing_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DatasetDetailResponse(DatasetResponse):
    """Dataset detail response with relationships."""

    site: SiteSummary | None = None
    recorder: RecorderSummary | None = None
    license: LicenseSummary | None = None
    created_by: UserSummary | None = None
    recording_count: int = 0
    total_duration: float = 0.0
    start_date: datetime | None = None
    end_date: datetime | None = None


class DatasetListResponse(BaseModel):
    """Paginated dataset list response."""

    items: list[DatasetResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ImportRequest(BaseModel):
    """Dataset import request."""

    datetime_pattern: str | None = Field(None, description="Regex pattern for datetime extraction")
    datetime_format: str | None = Field(None, description="strftime format string")


class ImportStatusResponse(BaseModel):
    """Dataset import status."""

    status: DatasetStatus
    total_files: int
    processed_files: int
    progress_percent: float
    error: str | None = None


class DateRangeStats(BaseModel):
    """Date range statistics."""

    start: datetime
    end: datetime


class RecordingsByDate(BaseModel):
    """Recordings count by date."""

    date: str
    count: int
    duration: float


class RecordingsByHour(BaseModel):
    """Recordings count by hour."""

    hour: int
    count: int


class DatasetStatisticsResponse(BaseModel):
    """Dataset statistics response."""

    recording_count: int
    total_duration: float
    date_range: DateRangeStats | None = None
    samplerate_distribution: dict[int, int] = {}
    format_distribution: dict[str, int] = {}
    recordings_by_date: list[RecordingsByDate] = []
    recordings_by_hour: list[RecordingsByHour] = []


class DirectoryInfo(BaseModel):
    """Directory information for import."""

    name: str
    path: str
    audio_file_count: int
    formats: list[str]


class DirectoryListResponse(BaseModel):
    """Directory listing response."""

    path: str
    directories: list[DirectoryInfo]


class ExportRequest(BaseModel):
    """Dataset export request."""

    include_audio: bool = Field(default=False, description="Include audio files in export")
