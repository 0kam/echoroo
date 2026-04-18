"""Note request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    """Note creation request schema."""

    content: str = Field(..., min_length=1, max_length=5000, description="Note text content")
    is_review: bool = Field(default=False, description="Whether this note is a formal review comment")
    is_issue: bool = Field(
        default=False,
        description="Quality-concern flag for ground-truth annotation notes (spec 003-annotation)",
    )


class NoteResponse(BaseModel):
    """Note response schema."""

    id: UUID
    content: str
    is_review: bool
    is_issue: bool = False
    created_by_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}
