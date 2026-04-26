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
    hash: str | None = None  # noqa: A003
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


# ---------------------------------------------------------------------------
# Phase 5 polish — Guest-safe recording list shape
# ---------------------------------------------------------------------------


class PublicRecordingItem(BaseModel):
    """Public-safe recording row embedded in :class:`PublicRecordingListResponse`.

    Phase 5 (US1) polish round 4 (致命 1): the Guest-aware
    ``GET /web-api/v1/projects/{project_id}/recordings`` endpoint exposes a
    *minimal* projection of :class:`Recording` so that signed-out visitors can
    enumerate playable items without leaking internal storage layout (the S3
    object key in ``Recording.path``), MD5-style content hashes, free-form
    user notes, or author attribution.

    The shape covers exactly what the public detail page needs: an opaque ID
    (for the audio stream URL), a display name (filename), the playback
    duration when available, and the H3 cell index of the linked site (FR-030;
    raw lat/lng MUST never reach the wire).

    Adding any further field MUST go through a privacy review — the matrix
    in ``specs/006-permissions-redesign/data-model.md`` is the source of
    truth for what a Guest may observe.
    """

    id: UUID = Field(..., description="Recording UUID, used for audio stream URL")
    project_id: UUID = Field(..., description="Owning project UUID (denormalised for the URL builder)")
    name: str = Field(..., description="Display name (Recording.filename)")
    duration_seconds: float | None = Field(
        None,
        description="Playback duration in seconds with time_expansion applied; None if unknown",
    )
    site_h3_index: str | None = Field(
        None,
        description=(
            "H3 cell index of the linked Site, when present. NEVER raw "
            "latitude/longitude — FR-030 anti-precision."
        ),
    )

    model_config = {"from_attributes": True}


class PublicRecordingListResponse(BaseModel):
    """Paginated Public-safe recording list (Phase 5 US1 polish round 4)."""

    items: list[PublicRecordingItem]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    limit: int = Field(..., ge=1)


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
