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


class TaxonFromGBIFRequest(BaseModel):
    """Request body for materialising a GBIF search pick into a local taxon.

    The first-party annotation-set palette lets users pick a species from a
    live GBIF search (``GBIFSpeciesResult``) and add it to the project. This
    request carries the minimal fields needed to get-or-create the matching
    local ``taxa`` row: the canonical scientific name, the optional GBIF
    backbone key, and an optional vernacular (common) name.
    """

    scientific_name: str = Field(
        ..., min_length=1, description="Canonical scientific name of the species"
    )
    gbif_taxon_key: int | None = Field(
        None, description="GBIF backbone taxon key, when known"
    )
    common_name: str | None = Field(
        None, description="Vernacular name to seed when creating a new taxon"
    )


class GBIFSpeciesResult(BaseModel):
    """A single species result from the GBIF real-time search API."""

    gbif_key: int
    scientific_name: str
    canonical_name: str
    rank: str | None = None
    vernacular_name: str | None = Field(
        None, description="Best matching vernacular name from available vernacular names"
    )
    vernacular_names: list[dict[str, str]] | None = Field(
        None,
        description="All vernacular names as list of {name, language} dicts",
    )
    kingdom: str | None = None
    phylum: str | None = None
    class_name: str | None = None
    order: str | None = None
    family: str | None = None
