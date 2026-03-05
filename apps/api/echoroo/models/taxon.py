"""Taxon model for global species taxonomy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.taxon_vernacular_name import TaxonVernacularName


class Taxon(UUIDMixin, TimestampMixin, Base):
    """Global taxon record linked to GBIF taxonomy.

    Attributes:
        scientific_name: Canonical scientific name (e.g. "Turdus merula")
        gbif_taxon_key: GBIF species key (nullable, resolved asynchronously)
        rank: Taxonomic rank (e.g. "SPECIES", "GENUS")
        is_non_biological: True for non-species labels (Engine, Noise, etc.)
        gbif_metadata: JSONB with kingdom/phylum/class/order/family/genus
        gbif_resolved_at: When GBIF resolution completed
    """

    __tablename__ = "taxa"

    scientific_name: Mapped[str] = mapped_column(
        String(300), nullable=False, unique=True, doc="Canonical scientific name",
    )
    gbif_taxon_key: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="GBIF species key",
    )
    rank: Mapped[str | None] = mapped_column(
        String(50), nullable=True, doc="Taxonomic rank (SPECIES, GENUS, etc.)",
    )
    is_non_biological: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, doc="Non-biological label (noise, engine, etc.)",
    )
    gbif_metadata: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True, doc="GBIF classification metadata",
    )
    gbif_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When GBIF resolution was completed",
    )

    # Relationships
    vernacular_names: Mapped[list[TaxonVernacularName]] = relationship(
        "TaxonVernacularName",
        back_populates="taxon",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_taxa_gbif_taxon_key", "gbif_taxon_key", unique=True, postgresql_where=gbif_taxon_key.isnot(None)),
        Index("ix_taxa_scientific_name", "scientific_name"),
        Index("ix_taxa_is_non_biological", "is_non_biological"),
    )

    def __repr__(self) -> str:
        return f"<Taxon(id={self.id}, scientific_name={self.scientific_name})>"
