"""Annotation comment request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from echoroo.models.enums import AnnotationVoteSource


class AnnotationCommentCreate(BaseModel):
    """Request body for creating an annotation comment."""

    body: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Comment body, 1-2000 chars after stripping whitespace",
    )

    @field_validator("body")
    @classmethod
    def _validate_body_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("body must not be blank or whitespace only")
        return v


class AnnotationCommentResponse(BaseModel):
    """Single annotation comment response."""

    id: UUID
    annotation_id: UUID
    commenter_user_id: UUID
    body: str
    source: AnnotationVoteSource
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnotationCommentListResponse(BaseModel):
    """Annotation comment list response wrapper."""

    items: list[AnnotationCommentResponse] = Field(default_factory=list)
