"""Schemas for ML inference jobs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.datasets import Dataset
from echoroo.schemas.model_runs import ModelRun
from echoroo.schemas.recordings import Recording

__all__ = [
    "InferenceConfig",
    "InferenceJob",
    "InferenceJobCreate",
    "InferenceJobUpdate",
    "InferenceStatus",
    "JobQueueStatus",
]


InferenceStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
"""Status of an inference job."""


class InferenceConfig(BaseModel):
    """Model-specific inference configuration."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: Literal["birdnet", "perch"]
    """Name of the ML model to use for inference."""

    model_version: str = "latest"
    """Version of the model to use."""

    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    """Minimum confidence score to include in results."""

    overlap: float = Field(default=0.0, ge=0.0, lt=1.0)
    """Overlap between consecutive audio segments (0.0 to 1.0)."""

    batch_size: int = Field(default=32, ge=1, le=256)
    """Number of audio segments to process in a single batch."""

    use_gpu: bool = True
    """Whether to use GPU acceleration if available."""

    use_metadata_filter: bool = False
    """Apply species filters explicitly after the run (BirdNET)."""

    custom_species_list: list[str] | None = None
    """Custom list of species to detect (limits predictions to these species)."""

    store_embeddings: bool = True
    """Whether to store computed embeddings in the database."""

    store_predictions: bool = True
    """Whether to store model predictions in the database."""


class InferenceJobCreate(BaseModel):
    """Request to create a new inference job."""

    dataset_uuid: UUID | None = None
    """UUID of the dataset to run inference on (mutually exclusive with recording_uuid)."""

    recording_uuid: UUID | None = None
    """UUID of a single recording to run inference on (mutually exclusive with dataset_uuid)."""

    config: InferenceConfig
    """Inference configuration for the job."""


class InferenceJob(BaseSchema):
    """Inference job response returned to the user."""

    model_config = ConfigDict(protected_namespaces=())

    uuid: UUID
    """The unique identifier of the inference job."""

    id: int = Field(..., exclude=True)
    """The database id of the inference job."""

    status: InferenceStatus
    """Current status of the inference job."""

    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    """Progress of the inference job (0.0 to 1.0)."""

    total_items: int = Field(default=0, ge=0)
    """Total number of items to process."""

    processed_items: int = Field(default=0, ge=0)
    """Number of items processed so far."""

    error_message: str | None = None
    """Error message if the job failed."""

    config: InferenceConfig
    """Inference configuration used for this job."""

    started_on: datetime | None = None
    """Timestamp when the job started processing."""

    completed_on: datetime | None = None
    """Timestamp when the job completed."""

    model_run: ModelRun | None = None
    """Associated model run for storing results."""

    dataset: Dataset | None = None
    """Dataset being processed (if applicable)."""

    recording: Recording | None = None
    """Single recording being processed (if applicable)."""


class InferenceJobUpdate(BaseModel):
    """Update inference job status."""

    status: InferenceStatus | None = None
    """New status for the inference job."""

    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    """Updated progress value."""

    processed_items: int | None = Field(default=None, ge=0)
    """Updated count of processed items."""

    error_message: str | None = None
    """Error message to set (if job failed)."""


class JobQueueStatus(BaseModel):
    """Status of the job queue."""

    pending: int = 0
    """Number of jobs waiting to be processed."""

    running: int = 0
    """Number of jobs currently being processed."""

    completed: int = 0
    """Number of completed jobs."""

    failed: int = 0
    """Number of failed jobs."""
