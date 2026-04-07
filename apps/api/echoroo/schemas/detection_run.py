"""DetectionRun request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import DetectionRunStatus


class DetectionRunCreate(BaseModel):
    """Detection run creation request schema."""

    dataset_id: UUID = Field(..., description="Dataset ID to scope the run")
    model_name: str = Field(..., min_length=1, max_length=100, description="Name of the detection model")
    model_version: str = Field(..., min_length=1, max_length=50, description="Version of the detection model")
    parameters: dict[str, object] | None = Field(None, description="Optional model parameters")
    embedding_only: bool = Field(False, description="If true, only generate embeddings without running detection")


class DetectionRunUpdate(BaseModel):
    """Detection run update request schema (for status updates)."""

    status: DetectionRunStatus | None = Field(None, description="Updated execution status")
    annotation_count: int | None = Field(None, ge=0, description="Number of annotations created")
    error_message: str | None = Field(None, description="Error details if the run failed")


class DetectionRunResponse(BaseModel):
    """Detection run response schema."""

    id: UUID
    project_id: UUID
    dataset_id: UUID | None
    model_name: str
    model_version: str
    parameters: dict[str, object] | None
    status: DetectionRunStatus
    annotation_count: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DetectionRunListResponse(BaseModel):
    """Paginated detection run list response."""

    items: list[DetectionRunResponse]
    total: int
    page: int
    page_size: int
    pages: int


class AvailableModelsResponse(BaseModel):
    """Response listing available ML detection models."""

    models: list[str] = Field(
        ...,
        description="Names of models registered in the ModelRegistry (e.g. 'birdnet', 'perch')",
    )
