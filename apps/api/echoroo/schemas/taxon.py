"""Taxon request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class VernacularNameResponse(BaseModel):
    """Vernacular name for a taxon in a specific locale."""

    id: UUID
    locale: str
    name: str
    source: str
    is_primary: bool

    model_config = {"from_attributes": True}


class TaxonResponse(BaseModel):
    """Taxon response schema (compact)."""

    id: UUID
    scientific_name: str
    gbif_taxon_key: int | None
    rank: str | None
    is_non_biological: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TaxonDetailResponse(TaxonResponse):
    """Taxon detail response with vernacular names and GBIF metadata."""

    gbif_metadata: dict[str, object] | None = None
    gbif_resolved_at: datetime | None = None
    vernacular_names: list[VernacularNameResponse] = Field(default_factory=list)
    updated_at: datetime


class TaxonListResponse(BaseModel):
    """Paginated taxon list response."""

    items: list[TaxonResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TaxonSearchResult(BaseModel):
    """Search result for taxon autocomplete."""

    id: UUID
    scientific_name: str
    gbif_taxon_key: int | None
    rank: str | None
    is_non_biological: bool
    common_name: str | None = Field(None, description="Best matching vernacular name")
