"""Schemas related to species search."""

from pydantic import BaseModel, Field

__all__ = ["SpeciesCandidate"]


class SpeciesCandidate(BaseModel):
    """Candidate species returned from external taxonomic catalogues."""

    usage_key: str = Field(
        description="GBIF usageKey identifying the taxon.",
        min_length=1,
    )
    canonical_name: str = Field(
        description="Canonical scientific name (without authorship).",
        min_length=1,
        max_length=255,
    )
    scientific_name: str | None = Field(
        default=None,
        description="Full scientific name including authorship.",
    )
    rank: str | None = Field(
        default=None,
        description="Taxonomic rank reported by GBIF.",
    )
    synonym: bool | None = Field(
        default=None,
        description="Whether the record is flagged as a synonym.",
    )
    dataset_key: str | None = Field(
        default=None,
        description="Dataset key provided by GBIF.",
    )
    vernacular_name: str | None = Field(
        default=None,
        description="Primary English vernacular (common) name, if available.",
    )
    vernacular_names: list[dict] | None = Field(
        default=None,
        description="All available vernacular names with language codes.",
    )
