"""Schemas for Inference Batches and Predictions."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.custom_models import CustomModel

__all__ = [
    "InferenceBatchStatus",
    "InferenceBatch",
    "InferenceBatchCreate",
    "InferencePrediction",
    "InferenceProgress",
    "InferenceBatchStats",
    "ConvertToAnnotationProjectRequest",
]


class InferenceBatchStatus(str, Enum):
    """Status of an inference batch."""

    PENDING = "pending"
    """Batch is queued for processing."""

    RUNNING = "running"
    """Inference is currently running."""

    COMPLETED = "completed"
    """Inference completed successfully."""

    FAILED = "failed"
    """Inference failed due to an error."""

    CANCELLED = "cancelled"
    """Inference was cancelled by the user."""


class InferenceBatchCreate(BaseModel):
    """Schema for creating an inference batch."""

    name: str | None = Field(default=None, max_length=255)
    """Optional name for the inference batch."""

    custom_model_id: int | None = Field(
        default=None,
        description="Custom model ID to use for inference",
    )
    """Custom model ID to use for running inference."""

    custom_model_uuid: UUID | None = Field(
        default=None,
        description="Custom model UUID to use for inference (alternative to custom_model_id)",
    )
    """Custom model UUID to use for running inference."""

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

    description: str | None = Field(default=None, max_length=2000)
    """Optional description of the inference batch."""


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

    confidence: float = Field(ge=0.0, le=1.0)
    """Confidence score for the prediction."""

    predicted_positive: bool
    """Whether the model predicted positive for target sound."""


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

    positive_predictions_count: int = 0
    """Number of predictions with positive label."""

    negative_predictions_count: int = 0
    """Number of predictions with negative label."""

    average_confidence: float | None = None
    """Average confidence score across all predictions (0.0 to 1.0)."""

    started_at: datetime.datetime | None = None
    """Timestamp when inference started."""

    completed_at: datetime.datetime | None = None
    """Timestamp when inference completed."""

    duration_seconds: float | None = None
    """Total inference duration in seconds."""

    error_message: str | None = None
    """Error message if inference failed."""

    description: str | None = None
    """Optional description of the inference batch."""

    created_by_id: UUID
    """User who created the inference batch."""


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

    confidence_histogram: list[int] = Field(default_factory=list)
    """Histogram of confidence scores (10 buckets, 0.0-1.0)."""

    average_confidence: float | None = None
    """Average confidence score across all predictions."""

    median_confidence: float | None = None
    """Median confidence score."""


class ConvertToAnnotationProjectRequest(BaseModel):
    """Request payload for converting inference batch to annotation project."""

    name: str = Field(..., min_length=1, max_length=255)
    """Name of the annotation project to create."""

    description: str | None = None
    """Optional description of the annotation project."""

    confidence_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Override confidence threshold (uses batch threshold if not provided)",
    )
    """Optional override for confidence threshold."""

    include_only_positive: bool = Field(
        default=True,
        description="Only include predictions where predicted_positive is True",
    )
    """Whether to filter to only positive predictions."""


class ConvertToAnnotationProjectResponse(BaseModel):
    """Response from converting inference batch to annotation project."""

    annotation_project_uuid: UUID
    """UUID of the created annotation project."""

    annotation_project_name: str
    """Name of the created annotation project."""

    total_tasks_created: int
    """Total number of annotation tasks created."""

    total_annotations_created: int
    """Total number of clip annotations created."""

    total_tags_added: int = 1
    """Total number of species tags added to the project."""
