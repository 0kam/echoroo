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
    "SpeciesDetectionJobStatus",
    "DetectionReviewStatus",
    "SpeciesDetectionJob",
    "SpeciesDetectionJobCreate",
    "SpeciesDetectionJobUpdate",
    "SpeciesDetectionJobProgress",
    "DetectionResult",
    "DetectionReview",
    "DetectionReviewUpdate",
    "DetectionSummary",
    "SpeciesSummary",
    "RecordingFilter",
    "ConversionResult",
]


class SpeciesDetectionJobStatus(str, Enum):
    """Status of a species detection job."""

    PENDING = "pending"
    """Job is queued and waiting to start."""

    RUNNING = "running"
    """Job is currently being processed."""

    COMPLETED = "completed"
    """Job finished successfully."""

    FAILED = "failed"
    """Job encountered an error and stopped."""

    CANCELLED = "cancelled"
    """Job was manually cancelled."""


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


class RecordingFilter(BaseModel):
    """Filters for selecting recordings to process."""

    date_from: datetime.date | None = Field(default=None, description="Start date filter")
    """Include recordings from this date onwards."""

    date_to: datetime.date | None = Field(default=None, description="End date filter")
    """Include recordings up to this date."""

    h3_indices: list[str] | None = Field(default=None, description="H3 spatial indices")
    """H3 spatial indices for location filtering."""

    tag_ids: list[int] | None = Field(default=None, description="Tag IDs to filter by")
    """Only include recordings with these tags."""

    recording_uuids: list[UUID] | None = Field(default=None, description="Specific recording UUIDs")
    """Specific recordings to process."""


class SpeciesDetectionJobCreate(BaseModel):
    """Schema for creating a species detection job."""

    model_config = {"protected_namespaces": ()}

    name: str = Field(..., min_length=1, max_length=255)
    """Name of the detection job."""

    dataset_uuid: UUID = Field(..., description="Dataset to process")
    """Dataset containing the recordings to analyze."""

    model_name: str = Field(..., description="Model to use (birdnet or perch)")
    """Model name: 'birdnet' or 'perch'."""

    model_version: str = Field(default="latest", description="Model version")
    """Model version to use."""

    confidence_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for detections",
    )
    """Minimum confidence score for detections to be saved."""

    overlap: float = Field(
        default=0.0,
        ge=0.0,
        le=0.9,
        description="Overlap between analysis windows",
    )
    """Overlap between consecutive analysis windows (0.0 to 0.9)."""

    use_metadata_filter: bool = Field(
        default=True,
        description="Use eBird occurrence data to filter species",
    )
    """Whether to filter predictions using location/date metadata."""

    custom_species_list: list[str] | None = Field(
        default=None,
        description="Custom list of species to detect",
    )
    """Optional list of specific species to detect."""

    recording_filters: RecordingFilter | None = Field(
        default=None,
        description="Filters for selecting recordings",
    )
    """Optional filters to select which recordings to process."""


class SpeciesDetectionJobUpdate(BaseModel):
    """Schema for updating a species detection job."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    """Updated name for the job."""

    status: SpeciesDetectionJobStatus | None = Field(default=None)
    """Updated status (for cancellation)."""


class SpeciesDetectionJob(BaseSchema):
    """Schema for a species detection job returned to the user."""

    model_config = {"protected_namespaces": ()}

    uuid: UUID
    """UUID of the detection job."""

    id: int = Field(..., exclude=True)
    """Database ID of the detection job."""

    name: str
    """Name of the detection job."""

    dataset_id: int = Field(..., exclude=True)
    """Dataset identifier."""

    dataset: Dataset | None = None
    """Hydrated dataset information."""

    created_by_id: UUID | None = None
    """User who created the job."""

    # Model configuration
    model_name: str
    """Model used for detection (birdnet or perch)."""

    model_version: str
    """Version of the model used."""

    confidence_threshold: float
    """Minimum confidence threshold for detections."""

    overlap: float = 0.0
    """Overlap between analysis windows."""

    use_metadata_filter: bool = True
    """Whether eBird filtering was enabled."""

    custom_species_list: list[str] | None = None
    """Custom species list if specified."""

    recording_filters: dict[str, Any] | None = None
    """Recording filters applied to the job."""

    # Status tracking
    status: SpeciesDetectionJobStatus = SpeciesDetectionJobStatus.PENDING
    """Current job status."""

    progress: float = 0.0
    """Job progress (0.0 to 1.0)."""

    total_recordings: int = 0
    """Total number of recordings to process."""

    processed_recordings: int = 0
    """Number of recordings processed so far."""

    total_clips: int = 0
    """Total number of clips analyzed."""

    total_detections: int = 0
    """Total number of species detections found."""

    # Error handling
    error_message: str | None = None
    """Error message if job failed."""

    # Timestamps
    started_on: datetime.datetime | None = None
    """Timestamp when job started."""

    completed_on: datetime.datetime | None = None
    """Timestamp when job completed."""

    # Result link
    model_run_id: int | None = Field(default=None, exclude=True)
    """Model run containing the predictions."""

    model_run: ModelRun | None = None
    """Hydrated model run information."""


class SpeciesDetectionJobProgress(BaseModel):
    """Schema for tracking detection job progress."""

    status: SpeciesDetectionJobStatus
    """Current job status."""

    progress: float = 0.0
    """Progress percentage (0.0 to 1.0)."""

    total_recordings: int = 0
    """Total recordings to process."""

    processed_recordings: int = 0
    """Recordings processed so far."""

    total_clips: int = 0
    """Total clips analyzed."""

    total_detections: int = 0
    """Detections found so far."""

    recordings_per_second: float | None = None
    """Processing speed."""

    estimated_time_remaining_seconds: float | None = None
    """Estimated time remaining."""

    message: str | None = None
    """Human-readable status message."""


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

    species_detection_job_id: int = Field(..., exclude=True)
    """Associated detection job."""

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
