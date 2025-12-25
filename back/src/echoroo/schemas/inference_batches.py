"""Schemas for Inference Batches and Predictions."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.custom_models import CustomModel
from echoroo.schemas.tags import Tag

__all__ = [
    "InferenceBatchStatus",
    "InferencePredictionReviewStatus",
    "InferenceBatch",
    "InferenceBatchCreate",
    "InferencePrediction",
    "InferencePredictionReview",
    "InferenceProgress",
    "InferenceBatchStats",
]


class InferenceBatchStatus(str, Enum):
    """Status of an inference batch."""

    PENDING = "pending"
    """Batch is queued for processing."""

    PREPARING = "preparing"
    """Preparing data for inference."""

    RUNNING = "running"
    """Inference is currently running."""

    COMPLETED = "completed"
    """Inference completed successfully."""

    FAILED = "failed"
    """Inference failed due to an error."""

    CANCELLED = "cancelled"
    """Inference was cancelled by the user."""


class InferencePredictionReviewStatus(str, Enum):
    """Review status for an inference prediction."""

    UNREVIEWED = "unreviewed"
    """Prediction has not been reviewed."""

    CONFIRMED = "confirmed"
    """Prediction has been confirmed as correct."""

    REJECTED = "rejected"
    """Prediction has been rejected as incorrect."""

    UNCERTAIN = "uncertain"
    """Reviewer is uncertain about the prediction."""


class InferenceBatchCreate(BaseModel):
    """Schema for creating an inference batch."""

    name: str | None = Field(default=None, max_length=255)
    """Optional name for the inference batch."""

    custom_model_id: int = Field(
        ...,
        description="Custom model to use for inference",
    )
    """Custom model to use for running inference."""

    confidence_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for predictions",
    )
    """Minimum confidence score to include predictions."""

    clip_ids: list[int] | None = Field(
        default=None,
        description="Specific clips to run inference on",
    )
    """Optional list of specific clip IDs to process."""

    include_all_clips: bool = Field(
        default=False,
        description="Run inference on all clips in the dataset",
    )
    """Whether to run inference on all clips in the dataset."""

    exclude_already_labeled: bool = Field(
        default=True,
        description="Skip clips that already have labels",
    )
    """Whether to skip clips that already have labels from search sessions."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the inference batch."""


class InferencePrediction(BaseSchema):
    """Schema for an inference prediction returned to the user."""

    uuid: UUID
    """UUID of the prediction."""

    id: int = Field(..., exclude=True)
    """Database ID of the prediction."""

    inference_batch_id: int = Field(..., exclude=True)
    """Inference batch that produced this prediction."""

    inference_batch_uuid: UUID
    """UUID of the owning inference batch."""

    clip_id: int = Field(..., exclude=True)
    """Clip identifier for this prediction."""

    clip: Clip
    """Hydrated clip information."""

    tag_id: int = Field(..., exclude=True)
    """Predicted tag identifier."""

    tag: Tag
    """Predicted tag."""

    confidence: float = Field(ge=0.0, le=1.0)
    """Confidence score for the prediction."""

    rank: int = Field(ge=1)
    """Rank of this prediction within the batch (by confidence)."""

    review_status: InferencePredictionReviewStatus = (
        InferencePredictionReviewStatus.UNREVIEWED
    )
    """Current review status."""

    reviewed_at: datetime.datetime | None = None
    """Timestamp when the prediction was reviewed."""

    reviewed_by_id: UUID | None = None
    """User who reviewed the prediction."""

    notes: str | None = None
    """Optional notes about this prediction."""


class InferenceBatch(BaseSchema):
    """Schema for an inference batch returned to the user."""

    uuid: UUID
    """UUID of the inference batch."""

    id: int = Field(..., exclude=True)
    """Database ID of the inference batch."""

    name: str | None = None
    """Optional name for the inference batch."""

    ml_project_id: int = Field(..., exclude=True)
    """ML project that owns this batch."""

    ml_project_uuid: UUID
    """UUID of the owning ML project."""

    custom_model_id: int = Field(..., exclude=True)
    """Custom model identifier used for inference."""

    custom_model: CustomModel | None = None
    """Hydrated custom model information."""

    status: InferenceBatchStatus = InferenceBatchStatus.PENDING
    """Current batch status."""

    confidence_threshold: float
    """Confidence threshold used for predictions."""

    total_clips: int = 0
    """Total number of clips to process."""

    processed_clips: int = 0
    """Number of clips processed so far."""

    total_predictions: int = 0
    """Total number of predictions generated."""

    reviewed_count: int = 0
    """Number of predictions that have been reviewed."""

    confirmed_count: int = 0
    """Number of predictions confirmed as correct."""

    rejected_count: int = 0
    """Number of predictions rejected as incorrect."""

    uncertain_count: int = 0
    """Number of predictions marked as uncertain."""

    started_at: datetime.datetime | None = None
    """Timestamp when inference started."""

    completed_at: datetime.datetime | None = None
    """Timestamp when inference completed."""

    duration_seconds: float | None = None
    """Total inference duration in seconds."""

    error_message: str | None = None
    """Error message if inference failed."""

    notes: str | None = None
    """Optional notes about the inference batch."""

    created_by_id: UUID
    """User who created the inference batch."""


class InferencePredictionReview(BaseModel):
    """Schema for reviewing an inference prediction."""

    review_status: InferencePredictionReviewStatus = Field(
        ...,
        description="New review status for the prediction",
    )
    """New review status to assign."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the review decision."""


class InferenceProgress(BaseModel):
    """Schema for tracking inference progress."""

    status: InferenceBatchStatus
    """Current batch status."""

    total_clips: int = 0
    """Total number of clips to process."""

    processed_clips: int = 0
    """Number of clips processed so far."""

    predictions_generated: int = 0
    """Number of predictions generated so far."""

    progress_percent: float = 0.0
    """Processing progress percentage."""

    clips_per_second: float | None = None
    """Processing speed in clips per second."""

    estimated_time_remaining_seconds: float | None = None
    """Estimated time remaining for inference."""

    message: str | None = None
    """Human-readable status message."""


class InferenceBatchStats(BaseModel):
    """Aggregate statistics for an inference batch."""

    total_predictions: int = 0
    """Total number of predictions."""

    predictions_by_confidence: dict[str, int] = Field(default_factory=dict)
    """Count of predictions by confidence range (e.g., '0.9-1.0': 150)."""

    reviewed: int = 0
    """Number of reviewed predictions."""

    unreviewed: int = 0
    """Number of unreviewed predictions."""

    confirmed: int = 0
    """Number of confirmed predictions."""

    rejected: int = 0
    """Number of rejected predictions."""

    uncertain: int = 0
    """Number of uncertain predictions."""

    precision: float | None = None
    """Precision based on reviewed predictions."""

    confidence_histogram: list[int] = Field(default_factory=list)
    """Histogram of confidence scores (10 buckets, 0.0-1.0)."""

    average_confidence: float | None = None
    """Average confidence score across all predictions."""

    median_confidence: float | None = None
    """Median confidence score."""
