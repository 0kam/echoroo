"""Schemas for ML Projects."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.datasets import Dataset
from echoroo.schemas.model_runs import ModelRun
from echoroo.schemas.tags import Tag

__all__ = [
    "MLProjectStatus",
    "MLProject",
    "MLProjectCreate",
    "MLProjectUpdate",
    "MLProjectStats",
]


class MLProjectStatus(str, Enum):
    """Status of an ML project."""

    DRAFT = "draft"
    """Project is being configured, not yet ready for searches."""

    ACTIVE = "active"
    """Project is ready for reference sound collection and searches."""

    TRAINING = "training"
    """A custom model is currently being trained."""

    INFERENCE = "inference"
    """Running batch inference on the dataset."""

    COMPLETED = "completed"
    """Project workflow has been completed."""

    ARCHIVED = "archived"
    """Project has been archived and is read-only."""


class MLProjectCreate(BaseModel):
    """Schema for creating an ML project."""

    name: str = Field(..., min_length=1, max_length=255)
    """Name of the ML project."""

    description: str | None = Field(default=None)
    """A description of the ML project goals and methodology."""

    dataset_uuid: UUID = Field(..., description="Primary dataset UUID")
    """Dataset that contains the audio data for this project."""

    embedding_model_run_id: int | None = Field(
        default=None,
        description="Model run used for generating embeddings",
    )
    """Model run that provides the embeddings for similarity search."""

    default_similarity_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Default similarity threshold for searches",
    )
    """Default threshold for similarity searches (0.0 to 1.0)."""


class MLProject(BaseSchema):
    """Schema for an ML project returned to the user."""

    uuid: UUID
    """UUID of the ML project."""

    id: int = Field(..., exclude=True)
    """Database ID of the ML project."""

    name: str
    """Name of the ML project."""

    description: str | None = None
    """A description of the ML project goals and methodology."""

    status: MLProjectStatus = MLProjectStatus.DRAFT
    """Current status of the ML project."""

    dataset_id: int
    """Dataset identifier containing the audio data."""

    dataset: Dataset | None = None
    """Hydrated dataset information."""

    embedding_model_run_id: int | None = None
    """Model run identifier used for embeddings."""

    embedding_model_run: ModelRun | None = None
    """Hydrated model run information."""

    default_similarity_threshold: float = 0.8
    """Default threshold for similarity searches."""

    created_by_id: UUID
    """User who created the project."""

    target_tags: list[Tag] = Field(default_factory=list)
    """Tags that this project is targeting for detection."""

    reference_sound_count: int = 0
    """Number of reference sounds in the project."""

    search_session_count: int = 0
    """Number of search sessions conducted."""

    custom_model_count: int = 0
    """Number of custom models trained."""

    inference_batch_count: int = 0
    """Number of inference batches processed."""


class MLProjectUpdate(BaseModel):
    """Schema for updating an ML project."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    """Name of the ML project."""

    description: str | None = None
    """A description of the ML project goals and methodology."""

    status: MLProjectStatus | None = None
    """Current status of the ML project."""

    embedding_model_run_id: int | None = None
    """Model run identifier used for embeddings."""

    default_similarity_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    """Default threshold for similarity searches."""


class MLProjectStats(BaseModel):
    """Aggregate statistics for an ML project."""

    total_reference_sounds: int = 0
    """Total number of reference sounds."""

    reference_sounds_by_tag: dict[str, int] = Field(default_factory=dict)
    """Count of reference sounds grouped by tag."""

    total_search_sessions: int = 0
    """Total number of search sessions."""

    total_labeled_results: int = 0
    """Total number of labeled search results."""

    positive_labels: int = 0
    """Number of results labeled as positive."""

    negative_labels: int = 0
    """Number of results labeled as negative."""

    total_custom_models: int = 0
    """Total number of custom models."""

    best_model_f1: float | None = None
    """Best F1 score achieved by custom models."""

    total_inference_batches: int = 0
    """Total number of inference batches."""

    total_predictions: int = 0
    """Total number of predictions made."""

    reviewed_predictions: int = 0
    """Number of predictions that have been reviewed."""

    last_activity: datetime.datetime | None = None
    """Timestamp of the last activity in the project."""
