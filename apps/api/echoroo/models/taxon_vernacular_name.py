"""Taxon vernacular name model for multilingual species names."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.taxon import Taxon


class TaxonVernacularName(UUIDMixin, TimestampMixin, Base):
    """Multilingual common name for a taxon.

    Attributes:
        taxon_id: FK to taxa table
        locale: Language code (e.g. "en", "ja")
        name: Vernacular name in the given locale
        source: Origin of the name ("gbif", "birdnet", "user")
        is_primary: Whether this is the primary name for the locale
    """

    __tablename__ = "taxon_vernacular_names"

    taxon_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent taxon ID",
    )
    locale: Mapped[str] = mapped_column(
        String(10), nullable=False, doc="Language/locale code (e.g. en, ja)",
    )
    name: Mapped[str] = mapped_column(
        String(300), nullable=False, doc="Vernacular name",
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, doc="Source of the name (gbif, birdnet, user)",
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, doc="Primary name for the locale",
    )

    # Relationships
    taxon: Mapped[Taxon] = relationship(
        "Taxon",
        back_populates="vernacular_names",
        lazy="joined",
    )

    __table_args__ = (
        UniqueConstraint("taxon_id", "locale", "source", name="uq_taxon_vernacular_locale_source"),
        Index(
            "ix_taxon_vernacular_names_locale_taxon_id",
            "locale",
            "taxon_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<TaxonVernacularName(taxon_id={self.taxon_id}, locale={self.locale}, name={self.name})>"
