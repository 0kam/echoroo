"""Species cache for GBIF resolution results.

This module provides a database model for caching GBIF species resolution
results. The cache reduces redundant API calls and improves performance
when resolving the same species names across multiple detection jobs.

The cache key is (scientific_name, locale) to support different vernacular
names for the same species in different languages.
"""

from __future__ import annotations

import datetime

import sqlalchemy.orm as orm
from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from echoroo.models.base import Base

__all__ = ["SpeciesCache"]


class SpeciesCache(Base):
    """Cache for GBIF species resolution results.

    This table stores resolved GBIF taxon information to avoid
    repeated API calls for the same species. The cache is keyed
    by scientific name and locale, storing the resolved taxon ID
    and vernacular name.

    Entries can be refreshed periodically to ensure data freshness,
    though GBIF data changes infrequently.
    """

    __tablename__ = "species_cache"
    __table_args__ = (
        UniqueConstraint(
            "scientific_name",
            name="uq_species_cache_scientific_name",
        ),
        Index(
            "ix_species_cache_gbif_taxon_id",
            "gbif_taxon_id",
        ),
        Index(
            "ix_species_cache_scientific_name",
            "scientific_name",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database ID of the cache entry."""

    # Required fields (no defaults) must come first for dataclass ordering
    scientific_name: orm.Mapped[str] = orm.mapped_column(
        String(255), nullable=False
    )
    """Original scientific name used for lookup."""

    canonical_name: orm.Mapped[str] = orm.mapped_column(
        String(255), nullable=False
    )
    """Canonical scientific name from GBIF or fallback to input."""

    # Optional fields with defaults
    gbif_taxon_id: orm.Mapped[str | None] = orm.mapped_column(
        String(64), nullable=True, default=None
    )
    """GBIF taxon key if resolved (e.g., '2493098')."""

    vernacular_names_json: orm.Mapped[dict | None] = orm.mapped_column(
        JSONB, nullable=True, default=None
    )
    """All vernacular names from GBIF in JSON format.

    Structure: {"en": "Common name", "ja": "一般名", ...}
    Language codes are 2-letter ISO 639-1 codes (e.g., "ja", "en").
    """

    is_non_species: orm.Mapped[bool] = orm.mapped_column(default=False)
    """True if this is a non-species environmental sound label."""

    created_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
        nullable=False,
        init=False,
    )
    """Timestamp when this cache entry was created."""

    updated_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
        onupdate=lambda: datetime.datetime.now(datetime.UTC),
        nullable=False,
        init=False,
    )
    """Timestamp when this cache entry was last updated."""
