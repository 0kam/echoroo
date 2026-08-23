"""Global taxon sensitivity row (006-permissions-redesign, FR-032).

A :class:`TaxonSensitivity` records the *recommended* H3 masking resolution
for a single taxon as published by an external authority (IUCN, Japanese MoE
Red Data Book) or as overridden globally by an Echoroo platform operator.

``taxon_id`` is a UUID FK to ``taxa.id`` — the platform's immutable species
identity (migration 0034, taxonomy WS-A v2 slice 4). It used to be a
``VARCHAR(64)`` "GBIF species key", but the three writers involved (IUCN sync,
MoE seeder, detections reader) each populated a different key-space, so
IUCN-sourced rows never matched a detection. Every writer now resolves its
incoming rows to a local taxon by scientific name before upserting; see
:func:`echoroo.services.taxon_resolution.resolve_taxon_ids_by_scientific_name`.

The auto-obscure pipeline (FR-029..032, spec L313-365
``compute_effective_resolution``) ranks rows by ``source`` so that ``manual``
wins over ``moe_rdb`` which wins over ``iucn`` when more than one source
emits an opinion for the same ``taxon_id``. Per-project escalation /
relaxation is layered on top via
:class:`echoroo.models.project_taxon_override.ProjectTaxonSensitivityOverride`
(FR-033).

The IUCN sync worker (FR-036) snapshots a run into
:class:`echoroo.models.iucn_sync_attempt.IucnSyncAttempt` and is the only
mutator of rows whose ``source = 'iucn'``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import TaxonSensitivitySource


class TaxonSensitivity(UUIDMixin, TimestampMixin, Base):
    """Global recommendation row for a taxon's masking resolution.

    See module docstring for the full FR mapping. ``__table_args__`` mirror
    the baseline Alembic migration:

    * ``ck_taxon_sensitivities_h3_discrete`` — ``sensitivity_h3_res`` must
      be one of the discrete values defined by FR-027
      (``2 / 5 / 7 / 9 / 15``). Continuous values would not align with the
      H3 hierarchy used by the masking utility.
    * ``ux_taxon_sensitivities_taxon_source`` — at most one row per
      ``(taxon_id, source)`` pair. The masking pipeline expects to read at
      most one row per source for a given taxon when picking the strictest
      recommendation (FR-032).
    """

    __tablename__ = "taxon_sensitivities"

    taxon_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="RESTRICT"),
        nullable=False,
        doc=(
            "Local taxon identity (``taxa.id``). Matches ``tags.taxon_id``, "
            "which is what the detections reader feeds into the masking "
            "pipeline. ON DELETE RESTRICT: this is a masking *guard* table, "
            "so a taxa delete / re-seed must never silently empty it and "
            "unmask the protected species. Retire the sensitivity rows "
            "explicitly first."
        ),
    )
    source: Mapped[TaxonSensitivitySource] = mapped_column(
        Enum(
            TaxonSensitivitySource,
            name="taxonsensitivitysource",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc=(
            "Authority that produced this row (FR-032). The auto-obscure "
            "pipeline ranks manual > moe_rdb > iucn when reconciling."
        ),
    )
    category: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
        doc=(
            "Optional Red List / RDB category (e.g. 'CR', 'EN', 'VU', 'NT', "
            "'LC'). The recommended H3 resolution is normally derived from "
            "this category, but ``sensitivity_h3_res`` is the authoritative "
            "field actually consumed by masking."
        ),
    )
    sensitivity_h3_res: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc=(
            "Recommended H3 resolution for masking detections of this taxon "
            "to public viewers. Must be one of {2, 5, 7, 9, 15} (FR-027)."
        ),
    )
    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Free-form note (e.g. 'overridden by ops on 2026-04-28 because ...').",
    )

    __table_args__ = (
        CheckConstraint(
            "sensitivity_h3_res IN (2, 5, 7, 9, 15)",
            name="ck_taxon_sensitivities_h3_discrete",
        ),
        UniqueConstraint(
            "taxon_id",
            "source",
            name="ux_taxon_sensitivities_taxon_source",
        ),
        Index("ix_taxon_sensitivities_taxon", "taxon_id"),
        # IUCN diff worker reads "rows from source=iucn updated since X" —
        # mirrors the index in the baseline migration.
        Index(
            "ix_taxon_sensitivities_source_updated",
            "source",
            text("updated_at DESC"),
        ),
    )

    def __repr__(self) -> str:
        """String representation of TaxonSensitivity."""
        return (
            "<TaxonSensitivity("
            f"id={self.id}, taxon_id={self.taxon_id}, "
            f"source={self.source}, sensitivity_h3_res={self.sensitivity_h3_res}"
            ")>"
        )


__all__ = ["TaxonSensitivity"]
