"""Directed taxon-concept relations (WS-A v2 slice 5).

An identity-history row answers "what changed on this taxon". This table
answers the other half: "where did this concept GO". When COL XR reports a
local taxon as a ``SYNONYM``, the accepted usage it points at is a *different
concept* — e.g. ``Accipiter badius`` -> COL ``CVWCS`` ``Tachyspiza badia``, or
``Parus minor`` -> ``VC6HB`` ``Parus cinereus minor``.

Critically, on the real dev catalogue **none** of the 302 synonym targets is
itself a local taxon: the accepted usage key does not appear as any
``taxa.col_xr_id``. So the edge cannot be keyed by a local FK — ``to_taxon_id``
is nullable and the durable key is ``to_col_xr_id`` (plus the human-readable
``to_scientific_name``). ``relink_concept_relations`` fills ``to_taxon_id`` in
later, idempotently, if and when the accepted concept is added locally.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

#: Directed relation kinds. Plain strings (not a DB enum) so a new kind is a
#: code change rather than an ``ALTER TYPE`` on a live table.
CONCEPT_RELATIONS: tuple[str, ...] = (
    "synonym_of",
    "lumped_into",
    "split_into",
    "renamed_to",
)

#: How the edge got here. ``col_xr_auto`` is seeded by the COL XR resolver.
CONCEPT_RELATION_SOURCES: tuple[str, ...] = ("col_xr_auto", "operator", "import")

#: The one relation the COL XR resolver seeds automatically.
CONCEPT_RELATION_SYNONYM_OF = "synonym_of"

#: Source marker for auto-seeded edges.
CONCEPT_RELATION_SOURCE_COL_XR_AUTO = "col_xr_auto"


class TaxonConceptRelation(UUIDMixin, TimestampMixin, Base):
    """One directed edge from a local taxon to another taxonomic concept.

    Attributes:
        from_taxon_id: Local taxon the edge starts at.
        to_taxon_id: Local taxon the edge points at, when the target concept
            exists locally. NULL is the common case today.
        to_col_xr_id: COL XR usage key of the target concept — the durable key.
        to_scientific_name: Accepted name of the target, for human readers.
        relation: One of ``CONCEPT_RELATIONS``.
        release: COL release the edge was derived from.
        authority: Authority that asserts the edge (COL release alias for
            auto-seeded edges, a checklist name for operator edges).
        evidence: Free text supporting the edge.
        notes: Operator notes.
        source: ``col_xr_auto`` / ``operator`` / ``import``.
        created_by_id: Operator who added the edge, when a human did.
    """

    __tablename__ = "taxon_concept_relations"

    from_taxon_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        # RESTRICT for the same reason as the history journal: an edge is the
        # explanation of where a concept went, so it must not vanish silently.
        ForeignKey("taxa.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Local taxon the edge starts at",
    )
    to_taxon_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="RESTRICT"),
        nullable=True,
        doc="Local taxon the edge points at, when the target exists locally",
    )
    to_col_xr_id: Mapped[str | None] = mapped_column(
        String(16), nullable=True, doc="COL XR usage key of the target concept",
    )
    to_scientific_name: Mapped[str | None] = mapped_column(
        String(300), nullable=True, doc="Accepted name of the target concept",
    )
    relation: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="synonym_of / lumped_into / split_into / renamed_to",
    )
    release: Mapped[str | None] = mapped_column(
        String(32), nullable=True, doc="COL release the edge was derived from",
    )
    authority: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="Authority asserting the edge",
    )
    evidence: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Free-text evidence for the edge",
    )
    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Operator notes",
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, doc="col_xr_auto / operator / import",
    )
    created_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Operator who created the edge, when a human did",
    )

    __table_args__ = (
        # The idempotency key of the auto-seeder: one edge per
        # (source taxon, relation, external target). NULLs never collide in a
        # UNIQUE index, so the partial index below covers the local-only case.
        Index(
            "ux_taxon_concept_relations_edge",
            "from_taxon_id",
            "relation",
            "to_col_xr_id",
            unique=True,
        ),
        # Local-target edges (operator-entered, no COL key) get their own
        # uniqueness rule; without it the UNIQUE above would let unlimited
        # duplicates through on the NULL ``to_col_xr_id`` side.
        Index(
            "ux_taxon_concept_relations_local_edge",
            "from_taxon_id",
            "relation",
            "to_taxon_id",
            unique=True,
            postgresql_where=text("to_col_xr_id IS NULL"),
        ),
        Index("ix_taxon_concept_relations_from_taxon_id", "from_taxon_id"),
        Index(
            "ix_taxon_concept_relations_to_taxon_id",
            "to_taxon_id",
            postgresql_where=text("to_taxon_id IS NOT NULL"),
        ),
        Index("ix_taxon_concept_relations_to_col_xr_id", "to_col_xr_id"),
        # An edge with no target at all says nothing.
        CheckConstraint(
            "to_taxon_id IS NOT NULL OR to_col_xr_id IS NOT NULL",
            name="ck_taxon_concept_relations_target_present",
        ),
        # A concept is not a synonym of itself.
        CheckConstraint(
            "to_taxon_id IS NULL OR to_taxon_id <> from_taxon_id",
            name="ck_taxon_concept_relations_no_self_edge",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TaxonConceptRelation({self.from_taxon_id} -{self.relation}-> "
            f"{self.to_col_xr_id or self.to_taxon_id})>"
        )
