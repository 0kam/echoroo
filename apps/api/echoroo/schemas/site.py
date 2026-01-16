"""Site request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SiteCreate(BaseModel):
    """Site creation request schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable site name")
    h3_index: str = Field(..., description="Valid H3 cell index (resolution 5-15)")


class SiteUpdate(BaseModel):
    """Site update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Human-readable site name")
    h3_index: str | None = Field(None, description="Valid H3 cell index (resolution 5-15)")


class SiteResponse(BaseModel):
    """Site response schema."""

    id: UUID
    project_id: UUID
    name: str
    h3_index: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SiteDetailResponse(SiteResponse):
    """Site detail response with statistics."""

    dataset_count: int = 0
    recording_count: int = 0
    total_duration: float = 0.0
    latitude: float | None = None
    longitude: float | None = None
    coordinate_uncertainty: float | None = None
    boundary: list[list[float]] | None = None


class SiteListResponse(BaseModel):
    """Paginated site list response."""

    items: list[SiteResponse]
    total: int
    page: int
    page_size: int
    pages: int


class H3ValidationRequest(BaseModel):
    """H3 index validation request."""

    h3_index: str = Field(..., description="H3 cell index to validate")


class H3ValidationResponse(BaseModel):
    """H3 index validation result."""

    valid: bool
    resolution: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    error: str | None = None


class H3FromCoordinatesRequest(BaseModel):
    """Request to get H3 index from coordinates."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")
    resolution: int = Field(..., ge=5, le=15, description="H3 resolution (5-15)")


class H3FromCoordinatesResponse(BaseModel):
    """H3 index from coordinates result."""

    h3_index: str
    resolution: int
    latitude: float
    longitude: float
    boundary: list[list[float]]
