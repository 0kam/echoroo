"""Taxon request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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


class VernacularNameInput(BaseModel):
    """A language-tagged vernacular name carried by a from-GBIF materialize.

    Lets the palette persist the locale-resolved name it already obtained from
    the live search (e.g. a Japanese 和名) with the CORRECT ``locale`` instead
    of defaulting everything to English.
    """

    name: str = Field(..., min_length=1, description="Vernacular name text")
    language: str = Field(
        ..., min_length=1, description="Locale code (e.g. en, ja). 'jpn' is normalized to 'ja'."
    )
    source: str | None = Field(
        None, description="Origin of the name (e.g. inaturalist, gbif). Defaults to 'gbif'."
    )


class TaxonFromGBIFRequest(BaseModel):
    """Request body for materialising a GBIF search pick into a local taxon.

    The first-party annotation-set palette lets users pick a species from a
    live GBIF search (``GBIFSpeciesResult``) and add it to the project. This
    request carries the minimal fields needed to get-or-create the matching
    local ``taxa`` row: the canonical scientific name, the optional GBIF
    backbone key, an optional vernacular (common) name, and an optional list of
    language-tagged vernacular names resolved at search time (so a non-English
    name is persisted with its real locale rather than as English).
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
    vernacular_names: list[VernacularNameInput] | None = Field(
        None,
        description=(
            "Language-tagged vernacular names to persist with their real locale "
            "(e.g. a ja 和名 resolved during the live search)."
        ),
    )

    @field_validator("vernacular_names", mode="before")
    @classmethod
    def _drop_blank_vernacular_entries(cls, value: Any) -> Any:
        """Silently drop vernacular entries with a blank name or language.

        GBIF/iNat search payloads occasionally include a vernacular row with a
        null/empty ``language`` (or, rarely, ``name``). The frontend forwards
        ``vernacular_names`` verbatim, so a single junk entry would otherwise
        trip ``VernacularNameInput``'s ``min_length=1`` constraint and 422 the
        whole add. Filter such entries out BEFORE per-item validation so the
        good names (including the ja 和名) still persist. Real constraints on
        the surviving entries are kept intact.
        """
        if not isinstance(value, list):
            return value

        def _is_valid(item: Any) -> bool:
            if isinstance(item, VernacularNameInput):
                return bool(item.name and item.name.strip()) and bool(
                    item.language and item.language.strip()
                )
            if isinstance(item, dict):
                name = item.get("name")
                language = item.get("language")
                name_ok = isinstance(name, str) and bool(name.strip())
                language_ok = isinstance(language, str) and bool(language.strip())
                return name_ok and language_ok
            # Leave non-dict / non-model items untouched so per-item validation
            # still surfaces a clear error for genuinely malformed shapes.
            return True

        return [item for item in value if _is_valid(item)]


class GBIFVernacularName(BaseModel):
    """A single vernacular name attached to a GBIF search result.

    ``source`` carries the origin of a live-enriched name (e.g.
    ``inaturalist`` / ``gbif``). It is optional so inline GBIF-backbone names
    (which have no enrichment source) serialize cleanly, but when an enriched
    name is injected the source MUST survive serialization so the from-GBIF
    materialize can persist it with the right provenance.
    """

    name: str
    language: str
    source: str | None = None


class GBIFSpeciesResult(BaseModel):
    """A single species result from the GBIF real-time search API."""

    gbif_key: int
    scientific_name: str
    canonical_name: str
    rank: str | None = None
    vernacular_name: str | None = Field(
        None, description="Best matching vernacular name from available vernacular names"
    )
    vernacular_names: list[GBIFVernacularName] | None = Field(
        None,
        description="All vernacular names as {name, language, source} entries",
    )
    kingdom: str | None = None
    phylum: str | None = None
    class_name: str | None = None
    order: str | None = None
    family: str | None = None
