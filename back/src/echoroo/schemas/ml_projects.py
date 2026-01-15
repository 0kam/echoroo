"""Schemas for ML Projects."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.datasets import Dataset
from echoroo.schemas.foundation_models import FoundationModel, FoundationModelRun
from echoroo.schemas.model_runs import ModelRun
from echoroo.schemas.tags import Tag

__all__ = [
    "MLProjectStatus",
    "MLProject",
    "MLProjectCreate",
    "MLProjectUpdate",
    "MLProjectStats",
    "MLProjectDatasetScope",
    "MLProjectDatasetScopeCreate",
]


class MLProjectStatus(str, Enum):
    """Status of an ML project - matches model definition."""

    SETUP = "setup"
    """Initial setup phase - defining targets and references."""

    SEARCHING = "searching"
    """Similarity search in progress."""

    LABELING = "labeling"
    """Reviewing and labeling search results."""

    TRAINING = "training"
    """Training a custom classifier."""

    INFERENCE = "inference"
    """Running inference on unlabeled data."""

    REVIEW = "review"
    """Reviewing model predictions."""

    COMPLETED = "completed"
    """Workflow completed, ready for export."""

    ARCHIVED = "archived"
    """Project archived and no longer active."""


class MLProjectCreate(BaseModel):
    """Schema for creating an ML project.

    Datasets are added separately via the Datasets tab after project creation.
    """

    name: str = Field(..., min_length=1, max_length=255)
    """Name of the ML project."""

    description: str | None = Field(default=None)
    """A description of the ML project goals and methodology."""


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

    status: MLProjectStatus = MLProjectStatus.SETUP
    """Current status of the ML project."""

    project_id: str
    """Project identifier for access control."""

    foundation_model_id: int | None = None
    """Foundation model identifier used for embeddings."""

    foundation_model: FoundationModel | None = None
    """Hydrated foundation model information."""

    default_similarity_threshold: float = 0.8
    """Default threshold for similarity searches."""

    created_by_id: UUID
    """User who created the project."""

    target_tags: list[Tag] = Field(default_factory=list)
    """Tags that this project is targeting for detection."""

    dataset_scope_count: int = 0
    """Number of dataset scopes in the project."""

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

    last_activity: datetime.datetime | None = None
    """Timestamp of the last activity in the project."""


class MLProjectDatasetScopeCreate(BaseModel):
    """Schema for adding a dataset scope to an ML project."""

    dataset_uuid: UUID = Field(..., description="UUID of the dataset to add")
    """UUID of the dataset to include in the project."""

    foundation_model_run_uuid: UUID = Field(
        ...,
        description="UUID of the foundation model run providing embeddings",
    )
    """UUID of the foundation model run that provides embeddings for this dataset."""


class MLProjectDatasetScope(BaseSchema):
    """Schema for an ML project dataset scope returned to the user."""

    uuid: UUID
    """UUID of the dataset scope."""

    dataset: Dataset
    """The dataset included in this scope."""

    foundation_model_run: FoundationModelRun
    """The foundation model run providing embeddings."""
