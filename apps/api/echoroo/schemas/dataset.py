"""Dataset request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

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


def _validate_iana_timezone(v: str | None) -> str | None:
    """Validate that the given string is a valid IANA timezone identifier."""
    if v is None:
        return v
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid IANA timezone: '{v}'") from None
    return v


class DatasetCreate(BaseModel):
    """Dataset creation request schema."""

    site_id: UUID = Field(..., description="Parent site ID (required)")
    name: str = Field(..., min_length=1, max_length=200, description="Dataset name")
    description: str | None = Field(None, description="Dataset description")
    visibility: DatasetVisibility = Field(default=DatasetVisibility.PRIVATE, description="Dataset visibility")
    recorder_id: str | None = Field(None, description="Recording device ID")
    license_id: str | None = Field(None, description="Content license ID")
    doi: str | None = Field(None, description="Digital Object Identifier")
    gain: float | None = Field(None, ge=-100, le=100, description="Recording gain in dB")
    note: str | None = Field(None, description="Internal notes")
    datetime_pattern: str | None = Field(None, max_length=200, description="Regex pattern for datetime extraction")
    datetime_format: str | None = Field(None, description="strftime format string")
    datetime_timezone: str | None = Field(
        None, max_length=50, description="IANA timezone for interpreting filenames (e.g., 'Asia/Tokyo')"
    )

    @field_validator("datetime_timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate IANA timezone string."""
        return _validate_iana_timezone(v)


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
    datetime_pattern: str | None = Field(None, max_length=200, description="Regex pattern for datetime extraction")
    datetime_format: str | None = Field(None, description="strftime format string")
    datetime_timezone: str | None = Field(
        None, max_length=50, description="IANA timezone for interpreting filenames (e.g., 'Asia/Tokyo')"
    )

    @field_validator("datetime_timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate IANA timezone string."""
        return _validate_iana_timezone(v)


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
    visibility: DatasetVisibility
    status: DatasetStatus
    doi: str | None
    gain: float | None
    note: str | None
    datetime_timezone: str | None = None
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
    """Import request for upload-session based import."""

    source: str | None = Field(
        None,
        description=(
            "Import source URI. Must be an 'upload-session://<session_id>' URI "
            "referencing a validated upload session. "
            "If omitted, the most recent validated upload session for the dataset is used."
        ),
        examples=["upload-session://550e8400-e29b-41d4-a716-446655440000"],
    )
    datetime_pattern: str | None = Field(None, max_length=200, description="Regex pattern for datetime extraction")
    datetime_format: str | None = Field(None, description="strftime format string")
    datetime_timezone: str | None = Field(
        None, max_length=50, description="IANA timezone for interpreting filenames (e.g., 'Asia/Tokyo')"
    )

    @field_validator("datetime_timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate IANA timezone string."""
        return _validate_iana_timezone(v)


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


class ExportRequest(BaseModel):
    """Dataset export request."""

    include_audio: bool = Field(default=False, description="Include audio files in export")


# Datetime configuration schemas


class DatetimeParseSummary(BaseModel):
    """Counts of datetime parse statuses for a dataset."""

    total: int
    success: int
    failed: int
    pending: int


class DatetimeConfigResponse(BaseModel):
    """Current datetime parsing configuration and status for a dataset."""

    datetime_pattern: str | None
    datetime_format: str | None
    datetime_timezone: str | None = None
    sample_filenames: list[str]
    parse_summary: DatetimeParseSummary


class DatetimeTestResult(BaseModel):
    """Result of testing a datetime pattern against a single filename."""

    filename: str
    success: bool
    parsed_datetime: str | None = None  # ISO format string
    error: str | None = None


class DatetimeAutoDetectResponse(BaseModel):
    """Result of auto-detecting a datetime pattern from sample filenames."""

    detected: bool
    pattern: str | None = None
    format_str: str | None = None
    preset_name: str | None = None
    results: list[DatetimeTestResult]


class DatetimeTestRequest(BaseModel):
    """Request to test a datetime pattern against sample filenames."""

    pattern: str = Field(..., max_length=200)
    format_str: str
    timezone: str | None = Field(
        None, max_length=50, description="IANA timezone for interpreting filenames (e.g., 'Asia/Tokyo')"
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate IANA timezone string."""
        return _validate_iana_timezone(v)


class DatetimeApplyRequest(BaseModel):
    """Request to apply a datetime pattern to all recordings in a dataset."""

    pattern: str = Field(..., max_length=200)
    format_str: str
    timezone: str | None = Field(
        None, max_length=50, description="IANA timezone for interpreting filenames (e.g., 'Asia/Tokyo')"
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str | None) -> str | None:
        """Validate IANA timezone string."""
        return _validate_iana_timezone(v)


class DatetimeApplyResponse(BaseModel):
    """Response after dispatching a datetime re-parse task."""

    task_id: str
    total_recordings: int
