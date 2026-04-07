"""Tag request and response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.enums import TagCategory


class TagCreate(BaseModel):
    """Tag creation request schema."""

    name: str = Field(..., min_length=1, max_length=200, description="Tag name")
    category: TagCategory = Field(..., description="Tag classification category")
    parent_id: UUID | None = Field(None, description="Parent tag ID for hierarchical taxonomy")
    gbif_taxon_key: int | None = Field(None, description="GBIF taxonomic key for species tags")
    scientific_name: str | None = Field(None, max_length=300, description="Scientific name (for species tags)")
    common_name: str | None = Field(None, max_length=300, description="Common name (for species tags)")


class TagUpdate(BaseModel):
    """Tag update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Tag name")
    parent_id: UUID | None = Field(None, description="Parent tag ID for hierarchical taxonomy")
    common_name: str | None = Field(None, max_length=300, description="Common name (for species tags)")


class TagResponse(BaseModel):
    """Tag response schema."""

    id: UUID
    project_id: UUID
    parent_id: UUID | None
    name: str
    category: TagCategory
    gbif_taxon_key: int | None
    scientific_name: str | None
    common_name: str | None
    taxon_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TagDetailResponse(TagResponse):
    """Tag detail response with children and usage statistics."""

    children: list[TagResponse] = Field(default_factory=list, description="Child tags in hierarchy")
    usage_count: int = Field(default=0, description="Number of annotations using this tag")


class TagListResponse(BaseModel):
    """Paginated tag list response."""

    items: list[TagResponse]
    total: int
    page: int
    page_size: int
    pages: int


class GBIFSuggestion(BaseModel):
    """GBIF species suggestion from autocomplete."""

    key: int = Field(..., description="GBIF taxon key")
    canonical_name: str = Field(..., description="Canonical scientific name")
    scientific_name: str = Field(..., description="Full scientific name with authorship")
    rank: str = Field(..., description="Taxonomic rank (e.g., SPECIES, GENUS)")
    kingdom: str | None = Field(None, description="Kingdom classification")
    phylum: str | None = Field(None, description="Phylum classification")
    class_name: str | None = Field(None, description="Class classification")
    order: str | None = Field(None, description="Order classification")
    family: str | None = Field(None, description="Family classification")


class TagStatistic(BaseModel):
    """Tag usage statistics."""

    tag: TagResponse = Field(..., description="Tag details")
    usage_count: int = Field(..., description="Number of annotations using this tag")
