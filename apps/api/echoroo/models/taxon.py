"""Taxon model for global species taxonomy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.taxon_vernacular_name import TaxonVernacularName


class Taxon(UUIDMixin, TimestampMixin, Base):
    """Global taxon record linked to GBIF taxonomy.

    The local UUID (``id``) is the immutable identity used throughout the
    platform; GBIF keys and the reconciliation columns below are re-matchable
    metadata that support GBIF-backbone reconciliation (a name can be re-matched
    against a newer backbone version without changing the local identity).

    Attributes:
        scientific_name: Canonical scientific name (e.g. "Turdus merula")
        gbif_taxon_key: GBIF species key (nullable, resolved asynchronously)
        rank: Taxonomic rank (e.g. "SPECIES", "GENUS")
        is_non_biological: True for non-species labels (Engine, Noise, etc.)
        gbif_metadata: JSONB with kingdom/phylum/class/order/family/genus
        gbif_resolved_at: When GBIF resolution completed
        gbif_accepted_usage_key: GBIF accepted usageKey when this taxon is a synonym
        gbif_match_type: GBIF /species/match matchType (EXACT/FUZZY/HIGHERRANK/NONE)
        gbif_match_confidence: GBIF match confidence (0..100)
        gbif_backbone_version: GBIF/COL backbone version pinned at match time
        verbatim_scientific_name: Original name as supplied before normalization
        accepted_scientific_name: GBIF canonical/accepted name
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

    # GBIF-backbone reconciliation metadata (additive, populated by later PRs).
    gbif_accepted_usage_key: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="GBIF accepted usageKey when this taxon is a synonym",
    )
    gbif_match_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, doc="GBIF /species/match matchType (EXACT/FUZZY/HIGHERRANK/NONE)",
    )
    gbif_match_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True, doc="GBIF match confidence (0..100)",
    )
    gbif_backbone_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True, doc="GBIF/COL backbone version pinned at match time",
    )
    verbatim_scientific_name: Mapped[str | None] = mapped_column(
        String(300), nullable=True, doc="Original name as supplied (BirdNET/user) before normalization",
    )
    accepted_scientific_name: Mapped[str | None] = mapped_column(
        String(300), nullable=True, doc="GBIF canonical/accepted name",
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
