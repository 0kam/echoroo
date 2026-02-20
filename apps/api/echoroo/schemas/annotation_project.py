"""AnnotationProject request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import AnnotationProjectVisibility


class DatasetSummary(BaseModel):
    """Dataset summary for annotation project responses."""

    id: UUID = Field(..., description="Dataset ID")
    name: str = Field(..., description="Dataset name")

    model_config = {"from_attributes": True}


class TagSummary(BaseModel):
    """Tag summary for annotation project responses."""

    id: UUID = Field(..., description="Tag ID")
    name: str = Field(..., description="Tag name")
    category: str = Field(..., description="Tag category")

    model_config = {"from_attributes": True}


class AnnotationProgress(BaseModel):
    """Annotation task completion progress."""

    total_tasks: int = Field(..., description="Total number of tasks")
    completed_tasks: int = Field(..., description="Number of completed tasks")
    in_progress_tasks: int = Field(..., description="Number of tasks in progress")
    pending_tasks: int = Field(..., description="Number of pending tasks")
    review_pending_tasks: int = Field(..., description="Number of tasks awaiting review")


class AnnotationProjectCreate(BaseModel):
    """Annotation project creation request schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Annotation project name")
    description: str | None = Field(None, description="Annotation project description")
    instructions: str | None = Field(None, description="Instructions for annotators")
    visibility: AnnotationProjectVisibility = Field(
        default=AnnotationProjectVisibility.PRIVATE,
        description="Annotation project visibility level",
    )
    dataset_ids: list[UUID] | None = Field(None, description="Dataset IDs to include in this project")
    tag_ids: list[UUID] | None = Field(None, description="Tag IDs available for annotation")


class AnnotationProjectUpdate(BaseModel):
    """Annotation project update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Annotation project name")
    description: str | None = Field(None, description="Annotation project description")
    instructions: str | None = Field(None, description="Instructions for annotators")
    visibility: AnnotationProjectVisibility | None = Field(None, description="Annotation project visibility level")
    dataset_ids: list[UUID] | None = Field(None, description="Dataset IDs to include in this project")
    tag_ids: list[UUID] | None = Field(None, description="Tag IDs available for annotation")


class AnnotationProjectResponse(BaseModel):
    """Annotation project response schema."""

    id: UUID
    project_id: UUID
    created_by_id: UUID
    name: str
    description: str | None
    instructions: str | None
    visibility: AnnotationProjectVisibility
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnotationProjectDetailResponse(AnnotationProjectResponse):
    """Annotation project detail response with related data."""

    datasets: list[DatasetSummary] = Field(default_factory=list, description="Associated datasets")
    tags: list[TagSummary] = Field(default_factory=list, description="Available annotation tags")
    progress: AnnotationProgress | None = Field(None, description="Task completion progress")


class AnnotationProjectListResponse(BaseModel):
    """Paginated annotation project list response."""

    items: list[AnnotationProjectDetailResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TaskGenerationResponse(BaseModel):
    """Response for task generation Celery job."""

    task_id: str = Field(..., description="Celery task ID for tracking progress")
    message: str = Field(..., description="Human-readable status message")
