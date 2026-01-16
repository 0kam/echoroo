"""Clip request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class RecordingSummary(BaseModel):
    """Recording summary for clip responses."""

    id: UUID
    filename: str
    duration: float
    samplerate: int
    time_expansion: float

    model_config = {"from_attributes": True}


class ClipCreate(BaseModel):
    """Clip creation request schema."""

    start_time: float = Field(..., ge=0, description="Start time in seconds")
    end_time: float = Field(..., description="End time in seconds")
    note: str | None = Field(None, description="User notes")

    @model_validator(mode="after")
    def validate_time_range(self) -> "ClipCreate":
        """Validate that end_time > start_time."""
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        return self


class ClipUpdate(BaseModel):
    """Clip update request schema."""

    start_time: float | None = Field(None, ge=0, description="Start time in seconds")
    end_time: float | None = Field(None, description="End time in seconds")
    note: str | None = Field(None, description="User notes")

    @model_validator(mode="after")
    def validate_time_range(self) -> "ClipUpdate":
        """Validate time range if both provided."""
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be greater than start_time")
        return self


class ClipResponse(BaseModel):
    """Clip response schema."""

    id: UUID
    recording_id: UUID
    start_time: float
    end_time: float
    note: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClipDetailResponse(ClipResponse):
    """Clip detail response with relationships."""

    duration: float = 0.0
    recording: RecordingSummary | None = None


class ClipListResponse(BaseModel):
    """Paginated clip list response."""

    items: list[ClipResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ClipGenerateRequest(BaseModel):
    """Auto-generate clips request."""

    clip_length: float = Field(..., ge=0.1, le=300, description="Length of each clip in seconds")
    overlap: float = Field(default=0, ge=0, le=0.99, description="Overlap ratio between clips")
    start_time: float = Field(default=0, ge=0, description="Start time for clip generation")
    end_time: float | None = Field(None, description="End time for clip generation")


class ClipGenerateResponse(BaseModel):
    """Auto-generate clips response."""

    clips_created: int
    clips: list[ClipResponse]
