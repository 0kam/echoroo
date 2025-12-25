"""Species occurrence cache for geo-filtered BirdNET predictions."""

from __future__ import annotations

import datetime
import enum

import sqlalchemy.orm as orm
from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from echoroo.models.base import Base

__all__ = [
    "GBIFResolutionStatus",
    "SpeciesOccurrenceCache",
]


class GBIFResolutionStatus(str, enum.Enum):
    """Status of GBIF taxon key resolution."""

    PENDING = "pending"
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    ERROR = "error"


gbif_resolution_status_enum = PgEnum(
    "pending",
    "resolved",
    "not_found",
    "error",
    name="gbif_resolution_status",
    create_type=False,
)


class SpeciesOccurrenceCache(Base):
    """Cache for geo-filtered species occurrence data.

    This table caches the output of geographic filters (e.g., BirdNET labels
    to GBIF taxon keys) to avoid repeated API calls for the same location/week
    combinations.

    The latitude and longitude are bucketed to 0.1 degree resolution (approx 11km)
    to reduce cache size while maintaining useful geographic precision.
    """

    __tablename__ = "species_occurrence_cache"
    __table_args__ = (
        UniqueConstraint(
            "latitude_bucket",
            "longitude_bucket",
            "week",
            "original_label",
            name="uq_species_occurrence_cache_location_week_label",
        ),
        Index(
            "ix_species_occurrence_cache_location_week",
            "latitude_bucket",
            "longitude_bucket",
            "week",
        ),
        Index(
            "ix_species_occurrence_cache_gbif_taxon_key",
            "gbif_taxon_key",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)

    latitude_bucket: orm.Mapped[int]
    """Latitude multiplied by 10 (0.1 degree resolution, ~11km)."""

    longitude_bucket: orm.Mapped[int]
    """Longitude multiplied by 10 (0.1 degree resolution, ~11km)."""

    week: orm.Mapped[int]
    """Week of the year (1-48)."""

    original_label: orm.Mapped[str] = orm.mapped_column(String(255))
    """Original BirdNET label (e.g., 'Parus minor_Japanese Tit')."""

    scientific_name: orm.Mapped[str] = orm.mapped_column(String(255))
    """Scientific name extracted from label (e.g., 'Parus minor')."""

    occurrence_probability: orm.Mapped[float]
    """Probability of species occurrence at this location/week."""

    gbif_taxon_key: orm.Mapped[str | None] = orm.mapped_column(
        String(64),
        default=None,
        kw_only=True,
    )
    """GBIF taxon key if resolved (e.g., '2493098')."""

    gbif_canonical_name: orm.Mapped[str | None] = orm.mapped_column(
        String(255),
        default=None,
        kw_only=True,
    )
    """GBIF canonical name if resolved."""

    gbif_resolution_status: orm.Mapped[str] = orm.mapped_column(
        String(32),
        default="pending",
        kw_only=True,
    )
    """Status of GBIF resolution: pending, resolved, not_found, error."""

    resolved_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        default=None,
        kw_only=True,
    )
    """Timestamp when GBIF resolution was completed."""
