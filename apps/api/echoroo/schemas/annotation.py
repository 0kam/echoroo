"""Annotation request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from echoroo.models.enums import AnnotationSource, ReviewStatus
from echoroo.schemas.note import NoteCreate, NoteResponse  # noqa: F401 - re-exported for convenience
from echoroo.schemas.tag import TagResponse  # noqa: F401 - re-exported for convenience


class TagSummary(BaseModel):
    """Tag summary for annotation responses."""

    id: UUID
    name: str
    category: str

    model_config = {"from_attributes": True}


class GeometrySchema(BaseModel):
    """Sound event geometry descriptor.

    Supports two geometry types:
    - BoundingBox: [t1, f1, t2, f2] where t2 > t1 and f2 > f1
    - TimeInterval: [t1, t2] where t2 > t1
    """

    type: str = Field(..., description="Geometry type: BoundingBox or TimeInterval")
    coordinates: list[float] = Field(..., description="Geometry coordinates")


class SoundEventAnnotationCreate(BaseModel):
    """Sound event annotation creation request schema."""

    geometry: GeometrySchema = Field(..., description="Sound event geometry")
    tag_ids: list[UUID] | None = Field(None, description="Tag IDs to attach to this sound event")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Confidence score (0.0 to 1.0)")
    source: AnnotationSource = Field(default=AnnotationSource.HUMAN, description="Source of annotation")

    @model_validator(mode="after")
    def validate_geometry(self) -> SoundEventAnnotationCreate:
        """Validate geometry coordinates match the geometry type."""
        geometry = self.geometry
        if geometry.type == "BoundingBox":
            if len(geometry.coordinates) != 4:
                raise ValueError("BoundingBox requires exactly 4 coordinates [t1, f1, t2, f2]")
            t1, f1, t2, f2 = geometry.coordinates
            if t2 <= t1:
                raise ValueError("BoundingBox requires t2 > t1 (end time must be after start time)")
            if f2 <= f1:
                raise ValueError("BoundingBox requires f2 > f1 (max frequency must be above min frequency)")
        elif geometry.type == "TimeInterval":
            if len(geometry.coordinates) != 2:
                raise ValueError("TimeInterval requires exactly 2 coordinates [t1, t2]")
            t1, t2 = geometry.coordinates
            if t2 <= t1:
                raise ValueError("TimeInterval requires t2 > t1 (end time must be after start time)")
        else:
            raise ValueError(f"Unknown geometry type: {geometry.type}. Must be 'BoundingBox' or 'TimeInterval'")
        return self


class SoundEventAnnotationUpdate(BaseModel):
    """Sound event annotation update request schema."""

    geometry: GeometrySchema | None = Field(None, description="Sound event geometry")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="Confidence score (0.0 to 1.0)")


class SoundEventAnnotationResponse(BaseModel):
    """Sound event annotation response schema."""

    id: UUID
    clip_annotation_id: UUID
    geometry: dict[str, object]
    source: AnnotationSource
    confidence: float | None
    tags: list[TagSummary] = Field(default_factory=list)
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClipAnnotationDetailResponse(BaseModel):
    """Detailed clip annotation response with all related data."""

    id: UUID
    task_id: UUID
    clip_id: UUID
    review_status: ReviewStatus
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    tags: list[TagSummary] = Field(default_factory=list)
    sound_events: list[SoundEventAnnotationResponse] = Field(default_factory=list)
    notes: list[NoteResponse] = Field(default_factory=list)
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewRequest(BaseModel):
    """Request to review a clip annotation."""

    status: str = Field(..., description="Review decision: 'approved' or 'rejected'")
    comment: str | None = Field(None, max_length=5000, description="Optional review comment")


class AddTagRequest(BaseModel):
    """Request to add a tag to an annotation."""

    tag_id: UUID = Field(..., description="Tag ID to add")


class BatchTagRequest(BaseModel):
    """Request to batch-tag multiple clips."""

    task_ids: list[UUID] = Field(..., min_length=1, description="Task IDs to tag")
    tag_id: UUID = Field(..., description="Tag ID to apply")


class BatchTagResponse(BaseModel):
    """Response for batch tagging operation."""

    updated_count: int = Field(..., description="Number of clips tagged")
    clip_annotations: list[ClipAnnotationDetailResponse] = Field(default_factory=list)
