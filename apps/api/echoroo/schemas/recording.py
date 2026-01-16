"""Recording request and response schemas."""

from __future__ import annotations

from datetime import datetime as DatetimeType
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import DatetimeParseStatus


class DatasetSummary(BaseModel):
    """Dataset summary for recording responses."""

    id: UUID
    name: str

    model_config = {"from_attributes": True}


class SiteSummaryForRecording(BaseModel):
    """Site summary for recording responses."""

    id: UUID
    name: str
    h3_index: str

    model_config = {"from_attributes": True}


class RecordingUpdate(BaseModel):
    """Recording update request schema."""

    time_expansion: float | None = Field(None, ge=0.1, le=100.0, description="Time expansion factor")
    note: str | None = Field(None, description="User notes")


class RecordingResponse(BaseModel):
    """Recording response schema."""

    id: UUID
    dataset_id: UUID
    filename: str
    path: str
    hash: str  # noqa: A003
    duration: float
    samplerate: int
    channels: int
    bit_depth: int | None
    datetime: DatetimeType | None  # noqa: A003
    datetime_parse_status: DatetimeParseStatus
    datetime_parse_error: str | None
    time_expansion: float
    note: str | None
    created_at: DatetimeType
    updated_at: DatetimeType

    model_config = {"from_attributes": True}


class RecordingDetailResponse(RecordingResponse):
    """Recording detail response with relationships."""

    dataset: DatasetSummary | None = None
    site: SiteSummaryForRecording | None = None
    clip_count: int = 0
    effective_duration: float = 0.0
    is_ultrasonic: bool = False


class RecordingListResponse(BaseModel):
    """Paginated recording list response."""

    items: list[RecordingResponse]
    total: int
    page: int
    page_size: int
    pages: int


class SpectrogramParams(BaseModel):
    """Spectrogram generation parameters."""

    start: float = Field(default=0, ge=0, description="Start time in seconds")
    end: float | None = Field(None, description="End time in seconds")
    n_fft: int = Field(default=2048, ge=128, le=8192, description="FFT window size")
    hop_length: int = Field(default=512, ge=64, le=4096, description="Hop length between windows")
    freq_min: int = Field(default=0, ge=0, description="Minimum frequency in Hz")
    freq_max: int | None = Field(None, description="Maximum frequency in Hz")
    colormap: str = Field(default="viridis", description="Color map name")
    pcen: bool = Field(default=False, description="Apply PCEN normalization")
    channel: int = Field(default=0, ge=0, description="Audio channel to visualize")
    width: int = Field(default=1200, ge=100, le=4096, description="Output image width")
    height: int = Field(default=400, ge=100, le=2048, description="Output image height")


class PlaybackParams(BaseModel):
    """Audio playback parameters."""

    speed: float = Field(default=1.0, ge=0.1, le=3.0, description="Playback speed multiplier")
    start: float | None = Field(None, ge=0, description="Start time in seconds")
    end: float | None = Field(None, description="End time in seconds")
