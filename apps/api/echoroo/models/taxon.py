"""Taxon model for global species taxonomy."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, SmallInteger, String
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
        accepted_scientific_name: Canonical/accepted name (COL XR since WS-A v2
            slice 3; previously reserved for the frozen GBIF backbone)
        col_xr_id: Catalogue of Life XR usage key of the matched name
        col_xr_accepted_id: COL XR usage key of the ACCEPTED name
        col_xr_accepted_rank: Rank of the COL XR accepted usage
        col_xr_status: COL XR usage status (ACCEPTED/SYNONYM/...)
        col_xr_match_type: COL XR matchType (EXACT/VARIANT/FUZZY/HIGHERRANK/NONE)
        col_xr_match_confidence: COL XR match confidence (0..100)
        col_xr_release: COL release alias pinned at match time (e.g. "COL26.6 XR").
            Stamped for EVERY resolved row, rejects included — see below.
        col_xr_clb_dataset_key: ChecklistBank dataset key of that release
        col_xr_resolved_at: When COL XR resolution ran (stamped incl. rejects)
        authorship: Authorship of the matched name
        accepted_authorship: Authorship of the accepted name
        col_xr_classification: ``{rank: {key, name}}`` for the accepted lineage

    Catalogue of Life XR replaces the frozen GBIF backbone as the re-matchable
    external identity (WS-A v2 slice 3). For birds the bundled AviList
    crosswalk remains the *name* authority; COL XR is cross-domain *identity*.

    The release pin (``col_xr_release`` + ``col_xr_clb_dataset_key``) is written
    for every row a resolution pass touches, INCLUDING rows whose match was
    rejected (HIGHERRANK/NONE, which keep ``col_xr_id`` NULL). A reject is a
    result of that particular release, and the pin is what
    ``resolve_col_xr_batch(force=True)`` selects on: rows already stamped with
    the current release drop out of the pass, so a forced re-resolution walks
    the catalogue in resumable chunks instead of grinding the same first rows.
    A COL release bump changes the pin and makes every row eligible again.

    ``accepted_scientific_name`` is always the AUTHORSHIP-FREE canonical name
    ("Acacia acuminata", never "Acacia acuminata Benth."); the authorship lives
    in ``accepted_authorship``.
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
        String(300), nullable=True, doc="Canonical/accepted name (COL XR)",
    )

    # Catalogue of Life XR identity (WS-A v2 slice 3, Alembic 0035). Populated
    # by ``resolve_col_xr_batch``; every processed row gets ``col_xr_resolved_at``
    # (and ``col_xr_match_type``) even when the match was rejected, so a rerun
    # never reprocesses it without ``force``.
    col_xr_id: Mapped[str | None] = mapped_column(
        String(16), nullable=True, doc="COL XR usage key of the matched name",
    )
    col_xr_accepted_id: Mapped[str | None] = mapped_column(
        String(16), nullable=True, doc="COL XR usage key of the accepted name",
    )
    col_xr_accepted_rank: Mapped[str | None] = mapped_column(
        String(20), nullable=True, doc="Rank of the COL XR accepted usage",
    )
    col_xr_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, doc="COL XR usage status (ACCEPTED/SYNONYM/...)",
    )
    col_xr_match_type: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        doc="COL XR matchType (EXACT/VARIANT/FUZZY/HIGHERRANK/NONE)",
    )
    col_xr_match_confidence: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True, doc="COL XR match confidence (0..100)",
    )
    col_xr_release: Mapped[str | None] = mapped_column(
        String(32), nullable=True, doc="COL release alias pinned at match time",
    )
    col_xr_clb_dataset_key: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="ChecklistBank dataset key of the COL release",
    )
    col_xr_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="When COL XR resolution ran",
    )
    authorship: Mapped[str | None] = mapped_column(
        String(200), nullable=True, doc="Authorship of the matched name",
    )
    accepted_authorship: Mapped[str | None] = mapped_column(
        String(200), nullable=True, doc="Authorship of the accepted name",
    )
    col_xr_classification: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True, doc="COL XR accepted lineage as {rank: {key, name}}",
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
        # Non-unique: taxonomic lumps map several taxa onto one COL XR usage.
        Index("ix_taxa_col_xr_id", "col_xr_id"),
        Index("ix_taxa_col_xr_accepted_id", "col_xr_accepted_id"),
    )

    def __repr__(self) -> str:
        return f"<Taxon(id={self.id}, scientific_name={self.scientific_name})>"
