"""AnnotationTask request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import AnnotationTaskStatus
from echoroo.schemas.annotation_project import TagSummary


class ClipSummary(BaseModel):
    """Basic clip summary for task responses."""

    id: UUID
    recording_id: UUID
    start_time: float
    end_time: float

    model_config = {"from_attributes": True}


class RecordingSummaryForTask(BaseModel):
    """Recording summary embedded in task detail responses."""

    id: UUID
    filename: str
    samplerate: int
    duration: float

    model_config = {"from_attributes": True}


class ClipDetailForTask(BaseModel):
    """Detailed clip information for annotation task responses."""

    id: UUID
    recording_id: UUID
    start_time: float
    end_time: float
    recording: RecordingSummaryForTask | None = None

    model_config = {"from_attributes": True}


class AnnotationProjectSummary(BaseModel):
    """Annotation project summary for task responses."""

    id: UUID
    name: str
    instructions: str | None
    tags: list[TagSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class AnnotationTaskUpdate(BaseModel):
    """Annotation task update request schema."""

    assigned_to_id: UUID | None = Field(None, description="User ID to assign task to")
    status: AnnotationTaskStatus | None = Field(None, description="Task workflow status")
    priority: int | None = Field(None, ge=0, le=100, description="Task priority (0-100)")


class AnnotationTaskResponse(BaseModel):
    """Annotation task response schema."""

    id: UUID
    annotation_project_id: UUID
    clip_id: UUID
    assigned_to_id: UUID | None
    status: AnnotationTaskStatus
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnotationTaskDetailResponse(AnnotationTaskResponse):
    """Annotation task detail response with related data."""

    clip: ClipDetailForTask | None = None
    clip_annotation: dict[str, object] | None = Field(None, description="Associated clip annotation if completed")
    annotation_project: AnnotationProjectSummary | None = None


class AnnotationTaskListResponse(BaseModel):
    """Paginated annotation task list response."""

    items: list[AnnotationTaskResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TaskCompletionResponse(BaseModel):
    """Response after completing an annotation task."""

    completed_task_id: UUID = Field(..., description="ID of the completed task")
    next_task: AnnotationTaskDetailResponse | None = Field(None, description="Next available task for the annotator")
