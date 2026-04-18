"""Request and response schemas for custom SVM classifier models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from echoroo.models.custom_model import CustomModelStatus
from echoroo.models.enums import DetectionRunStatus


class CustomModelCreate(BaseModel):
    """Request body for creating a new custom model."""

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable model name")
    description: str | None = Field(default=None, description="Optional description of the model's purpose")
    target_tag_id: UUID = Field(
        ...,
        description="Target species/sound type tag UUID this model classifies for",
    )
    embedding_model_name: str = Field(
        default="perch",
        description="Which embedding model's vectors to use for training",
    )
    search_session_id: UUID | None = Field(
        default=None,
        description="Source search session for this model",
    )


class CustomModelUpdate(BaseModel):
    """Request body for updating a custom model's metadata."""

    name: str | None = Field(default=None, min_length=1, max_length=200, description="Human-readable model name")
    description: str | None = Field(default=None, description="Optional description of the model's purpose")


class CustomModelTrainRequest(BaseModel):
    """Request body for triggering model training."""

    use_unlabeled: bool = Field(
        default=True,
        description="Whether to incorporate unlabeled samples via self-training",
    )
    max_unlabeled_samples: int = Field(
        default=2000,
        ge=0,
        le=50000,
        description="Maximum number of unlabeled samples to include in self-training",
    )


class CustomModelResponse(BaseModel):
    """Full custom model response including metrics and training details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    user_id: UUID | None
    name: str
    description: str | None
    target_tag_id: UUID
    model_type: str
    status: CustomModelStatus
    training_config: dict[str, object] | None
    hyperparameters: dict[str, object] | None
    metrics: dict[str, object] | None
    training_stats: dict[str, object] | None
    model_artifact_key: str | None
    embedding_model_name: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    search_session_id: UUID | None = None
    dataset_id: UUID | None = None


class CustomModelListItem(BaseModel):
    """Custom model list item (summary, no detailed metrics)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    target_tag_id: UUID | None
    model_type: str
    status: CustomModelStatus
    embedding_model_name: str
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    search_session_id: UUID | None = None
    dataset_id: UUID | None = None


class CustomModelListResponse(BaseModel):
    """Paginated list of custom models."""

    models: list[CustomModelListItem]
    total: int


class CustomModelApplyResponse(BaseModel):
    """Response for applying a custom model to a dataset."""

    detection_run_id: UUID = Field(..., description="UUID of the created DetectionRun")
    status: DetectionRunStatus = Field(..., description="Initial status of the detection run")


class CustomModelDetectionRunItem(BaseModel):
    """A DetectionRun created by applying a custom model, with dataset context."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(..., description="DetectionRun UUID")
    dataset_id: UUID | None = Field(None, description="Target dataset UUID, if any")
    dataset_name: str | None = Field(None, description="Human-readable dataset name")
    status: DetectionRunStatus = Field(..., description="Current execution status")
    annotation_count: int = Field(..., description="Annotations produced (so far)")
    started_at: datetime | None = Field(None, description="When the run started executing")
    completed_at: datetime | None = Field(None, description="When the run finished")
    error_message: str | None = Field(None, description="Error details if the run failed")
    created_at: datetime = Field(..., description="When the run was queued")


class CustomModelDetectionRunListResponse(BaseModel):
    """List response for recent detection runs of a custom model."""

    runs: list[CustomModelDetectionRunItem]
    total: int
