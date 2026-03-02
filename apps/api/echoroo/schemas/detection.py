"""Detection annotation request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from echoroo.models.enums import DetectionSource, DetectionStatus
from echoroo.schemas.tag import TagResponse


class DetectionCreate(BaseModel):
    """Detection annotation creation request schema."""

    recording_id: UUID = Field(..., description="Source recording ID")
    tag_id: UUID | None = Field(None, description="Species or sound type tag ID")
    detection_run_id: UUID | None = Field(None, description="ML detection run ID")
    source: DetectionSource = Field(..., description="Source of the detection")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Model confidence score (0.0-1.0)")
    start_time: float = Field(..., ge=0.0, description="Start time in seconds within the recording")
    end_time: float = Field(..., gt=0.0, description="End time in seconds within the recording")
    freq_low: float | None = Field(None, ge=0.0, description="Lower frequency bound in Hz")
    freq_high: float | None = Field(None, ge=0.0, description="Upper frequency bound in Hz")

    @model_validator(mode="after")
    def validate_time_range(self) -> DetectionCreate:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        return self


class DetectionUpdate(BaseModel):
    """Detection annotation update request schema."""

    tag_id: UUID | None = Field(None, description="Species or sound type tag ID")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Model confidence score (0.0-1.0)")
    start_time: float | None = Field(None, ge=0.0, description="Start time in seconds within the recording")
    end_time: float | None = Field(None, gt=0.0, description="End time in seconds within the recording")
    freq_low: float | None = Field(None, ge=0.0, description="Lower frequency bound in Hz")
    freq_high: float | None = Field(None, ge=0.0, description="Upper frequency bound in Hz")


class DetectionResponse(BaseModel):
    """Detection annotation response schema."""

    id: UUID
    recording_id: UUID
    tag_id: UUID | None
    detection_run_id: UUID | None
    source: DetectionSource
    status: DetectionStatus
    confidence: float | None
    start_time: float
    end_time: float
    freq_low: float | None
    freq_high: float | None
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    tag: TagResponse | None = None

    model_config = {"from_attributes": True}


class DetectionListResponse(BaseModel):
    """Paginated detection annotation list response."""

    items: list[DetectionResponse]
    total: int
    page: int
    page_size: int
    pages: int


class SpeciesSummaryItem(BaseModel):
    """Summary statistics for a single species tag."""

    tag_id: UUID = Field(..., description="Species tag ID")
    tag_name: str = Field(..., description="Species tag name")
    scientific_name: str | None = Field(None, description="Scientific name")
    common_name: str | None = Field(None, description="Common name")
    total_count: int = Field(..., description="Total number of detections")
    unreviewed_count: int = Field(..., description="Number of unreviewed detections")
    confirmed_count: int = Field(..., description="Number of confirmed detections")
    rejected_count: int = Field(..., description="Number of rejected detections")
    avg_confidence: float | None = Field(None, description="Average model confidence score")


class SpeciesSummaryResponse(BaseModel):
    """Species detection summary response."""

    items: list[SpeciesSummaryItem]
    total_species: int = Field(..., description="Total number of distinct species detected")


class ConfirmRequest(BaseModel):
    """Request schema for confirming a detection."""

    start_time: float = Field(..., ge=0.0, description="Confirmed start time in seconds")
    end_time: float = Field(..., gt=0.0, description="Confirmed end time in seconds")

    @model_validator(mode="after")
    def validate_time_range(self) -> ConfirmRequest:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")
        return self


class RejectRequest(BaseModel):
    """Request schema for rejecting a detection."""

    pass


class ChangeSpeciesRequest(BaseModel):
    """Request schema for changing the species tag of a detection."""

    new_tag_id: UUID = Field(..., description="New species tag ID")
    start_time: float | None = Field(None, ge=0.0, description="Updated start time in seconds")
    end_time: float | None = Field(None, gt=0.0, description="Updated end time in seconds")
