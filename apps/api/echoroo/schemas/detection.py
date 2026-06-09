"""Detection annotation request and response schemas."""

from __future__ import annotations

from datetime import date as DateType
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from echoroo.models.enums import DetectionSource, DetectionStatus
from echoroo.schemas.annotation_vote import DetectionVoteCounts
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
    votes: DetectionVoteCounts = Field(
        default_factory=DetectionVoteCounts,
        description="Aggregate vote counts and consensus status for this detection",
    )

    model_config = {"from_attributes": True}


class DetectionListResponse(BaseModel):
    """Paginated detection annotation list response."""

    items: list[DetectionResponse]
    total: int
    page: int
    page_size: int
    pages: int


class SpeciesSummaryItem(BaseModel):
    """Summary statistics for a single species tag or detection run.

    ``common_name`` is the English common name stored directly on the tag
    record. ``vernacular_name`` is resolved from ``taxon_vernacular_names`` for
    the requested locale (mirrors :class:`~echoroo.schemas.tag.TagResponse`);
    it is ``None`` when no entry exists, in which case clients should fall back
    to ``common_name``.
    """

    tag_id: UUID | None = Field(None, description="Species tag ID (None for tag-less sources like custom_svm)")
    tag_name: str = Field(..., description="Species tag name or model name for tag-less sources")
    scientific_name: str | None = Field(None, description="Scientific name")
    common_name: str | None = Field(None, description="Common name (English legacy)")
    vernacular_name: str | None = Field(
        default=None,
        description="Locale-resolved vernacular name; null if not available",
    )
    taxon_id: UUID | None = Field(None, description="Global taxon ID")
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
    """Request schema for confirming a detection.

    Both fields are optional. When omitted, the annotation's existing
    start_time / end_time are preserved (quick-confirm without time adjustment).
    """

    start_time: float | None = Field(None, ge=0.0, description="Confirmed start time in seconds")
    end_time: float | None = Field(None, gt=0.0, description="Confirmed end time in seconds")

    @model_validator(mode="after")
    def validate_time_range(self) -> ConfirmRequest:
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
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


class HourlyDetection(BaseModel):
    """Detection count for a specific date and hour."""

    date: DateType = Field(..., description="Calendar date of the detection")
    hour: int = Field(..., ge=0, le=23, description="Hour of the day (0-23)")
    count: int = Field(..., ge=0, description="Number of detections in this hour")


class SpeciesTemporalData(BaseModel):
    """Temporal detection data for a single species."""

    tag_id: UUID = Field(..., description="Species tag ID")
    scientific_name: str = Field(..., description="Scientific name of the species")
    common_name: str | None = Field(None, description="Common name of the species")
    total_detections: int = Field(..., description="Total number of detections across all dates/hours")
    detections: list[HourlyDetection] = Field(..., description="Hourly detection counts")


class DetectionTemporalDataResponse(BaseModel):
    """Temporal detection data aggregated by species, date, and hour."""

    project_id: UUID = Field(..., description="Project ID")
    dataset_id: UUID | None = Field(None, description="Dataset ID filter, if applied")
    detection_run_id: UUID | None = Field(None, description="Detection run ID filter, if applied")
    date_range: tuple[DateType, DateType] | None = Field(
        None, description="Min and max dates covered by the data"
    )
    species: list[SpeciesTemporalData] = Field(..., description="Per-species temporal data")
