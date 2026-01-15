"""Schemas for Species Detection Jobs and Reviews."""

import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.datasets import Dataset
from echoroo.schemas.model_runs import ModelRun
from echoroo.schemas.tags import Tag

__all__ = [
    "DetectionReviewStatus",
    "DetectionResult",
    "DetectionReview",
    "DetectionReviewUpdate",
    "DetectionSummary",
    "SpeciesSummary",
    "ConversionResult",
]


class DetectionReviewStatus(str, Enum):
    """Review status for a detection."""

    UNREVIEWED = "unreviewed"
    """Detection has not been reviewed."""

    CONFIRMED = "confirmed"
    """Detection has been confirmed as correct."""

    REJECTED = "rejected"
    """Detection has been rejected as incorrect."""

    UNCERTAIN = "uncertain"
    """Reviewer is uncertain about the detection."""


class DetectionResult(BaseSchema):
    """Schema for a detection result (ClipPrediction with review status)."""

    uuid: UUID
    """UUID of the clip prediction."""

    id: int = Field(..., exclude=True)
    """Database ID."""

    clip_id: int = Field(..., exclude=True)
    """Clip identifier."""

    clip: Clip
    """Hydrated clip information."""

    species_tag: Tag
    """Detected species tag."""

    confidence: float = Field(ge=0.0, le=1.0)
    """Detection confidence score."""

    # Review status (from DetectionReview if exists)
    review_status: DetectionReviewStatus = DetectionReviewStatus.UNREVIEWED
    """Current review status."""

    reviewed_on: datetime.datetime | None = None
    """Timestamp when reviewed."""

    reviewed_by_id: UUID | None = None
    """User who reviewed."""

    notes: str | None = None
    """Review notes."""

    converted_to_annotation: bool = False
    """Whether this detection was converted to an annotation."""

    is_included: bool | None = None
    """Whether the detection passed the species filter (None if no filter applied)."""

    occurrence_probability: float | None = None
    """Occurrence probability from the species filter (if applied)."""


class DetectionReview(BaseSchema):
    """Schema for a detection review record."""

    uuid: UUID
    """UUID of the review."""

    id: int = Field(..., exclude=True)
    """Database ID."""

    clip_prediction_id: int = Field(..., exclude=True)
    """Associated clip prediction."""

    foundation_model_run_id: int = Field(..., exclude=True)
    """Associated foundation model run."""

    status: DetectionReviewStatus = DetectionReviewStatus.UNREVIEWED
    """Review status."""

    reviewed_by_id: UUID | None = None
    """Reviewer user ID."""

    reviewed_on: datetime.datetime | None = None
    """Review timestamp."""

    notes: str | None = None
    """Review notes."""

    converted_to_annotation: bool = False
    """Whether converted to annotation."""

    clip_annotation_id: int | None = Field(default=None, exclude=True)
    """Associated annotation if converted."""


class DetectionReviewUpdate(BaseModel):
    """Schema for updating a detection review."""

    status: DetectionReviewStatus = Field(
        ...,
        description="New review status",
    )
    """New review status to assign."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the review."""


class SpeciesSummary(BaseModel):
    """Summary statistics for a single species."""

    tag_id: int
    """Tag ID for the species."""

    tag_value: str
    """Species name/label."""

    total_detections: int = 0
    """Total detections for this species."""

    confirmed_count: int = 0
    """Confirmed detections."""

    rejected_count: int = 0
    """Rejected detections."""

    uncertain_count: int = 0
    """Uncertain detections."""

    unreviewed_count: int = 0
    """Unreviewed detections."""

    average_confidence: float | None = None
    """Average confidence score."""


class DetectionSummary(BaseModel):
    """Summary statistics for detection job results."""

    total_detections: int = 0
    """Total number of detections."""

    unique_species: int = 0
    """Number of unique species detected."""

    species_summary: list[SpeciesSummary] = Field(default_factory=list)
    """Per-species statistics."""

    total_reviewed: int = 0
    """Total reviewed detections."""

    total_confirmed: int = 0
    """Total confirmed detections."""

    total_rejected: int = 0
    """Total rejected detections."""

    total_uncertain: int = 0
    """Total uncertain detections."""

    total_unreviewed: int = 0
    """Total unreviewed detections."""

    confidence_histogram: list[int] = Field(default_factory=list)
    """Histogram of confidence scores (10 buckets)."""

    detections_by_date: dict[str, int] = Field(default_factory=dict)
    """Detections grouped by date."""

    detections_by_location: dict[str, int] = Field(default_factory=dict)
    """Detections grouped by H3 index."""


class ConversionResult(BaseModel):
    """Result of converting detections to annotations."""

    total_converted: int = 0
    """Total detections converted."""

    clips_annotated: int = 0
    """Number of clips that received annotations."""

    tags_added: int = 0
    """Total tags added to annotations."""

    skipped_already_converted: int = 0
    """Detections skipped (already converted)."""

    errors: list[str] = Field(default_factory=list)
    """Any errors encountered during conversion."""
