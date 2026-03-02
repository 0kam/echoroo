"""ConfirmedRegion request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ConfirmedRegionCreate(BaseModel):
    """Confirmed region creation request schema."""

    recording_id: UUID = Field(..., description="Source recording ID")
    start_time: float = Field(..., ge=0.0, description="Start time in seconds within the recording")
    end_time: float = Field(..., gt=0.0, description="End time in seconds within the recording")


class ConfirmedRegionResponse(BaseModel):
    """Confirmed region response schema."""

    id: UUID
    recording_id: UUID
    start_time: float
    end_time: float
    reviewed_by_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConfirmedRegionListResponse(BaseModel):
    """Paginated confirmed region list response."""

    items: list[ConfirmedRegionResponse]
    total: int
    page: int
    page_size: int
    pages: int
