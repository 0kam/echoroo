"""Site request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SiteCreate(BaseModel):
    """Site creation request schema.

    Phase 13 P4 / T807: ``h3_index_member`` is the canonical field name
    matching ORM ``Site.h3_index_member`` and the spec data-model §3.10.
    """

    name: str = Field(..., min_length=1, max_length=200, description="Human-readable site name")
    h3_index_member: str = Field(
        ...,
        description="Valid H3 cell index at member precision (resolution 5-15; FR-028 / NFR-003)",
    )


class SiteUpdate(BaseModel):
    """Site update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Human-readable site name")
    h3_index_member: str | None = Field(
        None,
        description="Valid H3 cell index at member precision (resolution 5-15)",
    )


class SiteResponse(BaseModel):
    """Site response schema.

    Phase 13 P4 / T807 (2026-04-28): the response field is named
    ``h3_index_member`` (full rename). Stage-2 response filtering
    (``apply_response_filter``) coarsens this field in place when the
    caller is below member precision (FR-021 / FR-029 / FR-086); the
    field name does not change between the precise and coarsened
    representations — only the H3 resolution embedded in the cell does.
    """

    id: UUID
    project_id: UUID
    name: str
    h3_index_member: str
    h3_index_member_resolution: int = 15
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SiteDetailResponse(SiteResponse):
    """Site detail response with statistics.

    Round 1 review C3 / FR-030: ``latitude`` / ``longitude`` are intentionally
    absent. The site location is conveyed solely via ``h3_index_member``
    (inherited from :class:`SiteResponse`). Callers needing a coarsened cell
    can pass the response through the canonical Stage-2 response filter,
    which generalises ``h3_index_member`` to the appropriate parent
    resolution. ``coordinate_uncertainty`` is also dropped because deriving
    it requires the H3 cell area at the *member* resolution and was
    previously emitted regardless of the viewer's role — exposing it to
    non-members would defeat the auto-obscure pipeline.
    """

    dataset_count: int = 0
    recording_count: int = 0
    total_duration: float = 0.0
    boundary: list[list[float]] | None = None


class SiteListResponse(BaseModel):
    """Paginated site list response."""

    items: list[SiteResponse]
    total: int
    page: int
    page_size: int
    pages: int


class H3ValidationRequest(BaseModel):
    """H3 index validation request (general H3 utility, not Site-bound)."""

    h3_index: str = Field(..., description="H3 cell index to validate")


class H3ValidationResponse(BaseModel):
    """H3 index validation result."""

    valid: bool
    resolution: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    error: str | None = None


class H3FromCoordinatesRequest(BaseModel):
    """Request to get H3 index from coordinates (admin-only utility)."""

    latitude: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees")
    resolution: int = Field(..., ge=5, le=15, description="H3 resolution (5-15)")


class H3FromCoordinatesResponse(BaseModel):
    """H3 index from coordinates result (admin-only utility)."""

    h3_index: str
    resolution: int
    latitude: float
    longitude: float
    boundary: list[list[float]]
