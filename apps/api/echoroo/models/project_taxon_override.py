"""Per-project taxon sensitivity override (006-permissions-redesign, FR-033/034).

A :class:`ProjectTaxonSensitivityOverride` lets a project owner adjust the
auto-obscure masking resolution for a single taxon within their project,
*on top of* the global :class:`TaxonSensitivity` row (FR-032).

* ``direction = 'stricter'`` — increases masking (lower H3 res). Applies
  immediately because reducing public exposure cannot harm sensitive
  species.
* ``direction = 'looser'`` — decreases masking (higher H3 res). Requires
  superuser approval (FR-034) because relaxing protection on a flagged
  species is a sensitive operation. Until approved, the row exists with
  ``approval_status = 'pending_superuser_approval'`` and is **not** consumed
  by ``compute_effective_resolution`` (spec L313-365).

The CHECK constraint ``ck_taxon_overrides_direction_vs_approval`` enforces
the legal direction × approval combinations, and the partial unique index
``ux_taxon_overrides_applied_unique`` guarantees the masking pipeline never
sees two competing applied overrides for the same ``(project_id, taxon_id)``
pair.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import (
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
)

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


class ProjectTaxonSensitivityOverride(UUIDMixin, TimestampMixin, Base):
    """Per-project override of a taxon's masking resolution.

    See module docstring for the full FR mapping. ``__table_args__`` mirror
    the baseline Alembic migration:

    * ``ck_taxon_overrides_h3_discrete``           — ``sensitivity_h3_res``
      must be one of {2, 5, 7, 9, 15} (FR-027).
    * ``ck_taxon_overrides_direction_vs_approval`` — encodes the FR-034
      rule that ``stricter`` is auto-applied while ``looser`` must move
      through the superuser approval workflow.
    * ``ux_taxon_overrides_applied_unique``        — partial unique on
      ``(project_id, taxon_id)`` filtered by ``approval_status = 'applied'``
      so that ``compute_effective_resolution`` never has to reconcile two
      applied overrides for the same pair.
    * ``ix_taxon_overrides_taxon_approval``        — supports the bulk
      preload performed by the masking utility when projecting a list of
      detections for a public viewer.
    """

    __tablename__ = "project_taxon_sensitivity_overrides"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Target project (FR-033).",
    )
    taxon_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="GBIF species key. Matches detections.taxon_id / tags.taxon_id.",
    )
    sensitivity_h3_res: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc=(
            "Project-specific H3 resolution for masking. Must be one of "
            "{2, 5, 7, 9, 15} (FR-027). Compared against the global "
            "TaxonSensitivity.sensitivity_h3_res to classify direction."
        ),
    )
    direction: Mapped[TaxonOverrideDirection] = mapped_column(
        Enum(
            TaxonOverrideDirection,
            name="taxonoverridedirection",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc=(
            "Direction of the override relative to the global recommendation "
            "(FR-033). 'stricter' applies immediately; 'looser' requires "
            "superuser approval (FR-034)."
        ),
    )
    approval_status: Mapped[TaxonOverrideApprovalStatus] = mapped_column(
        Enum(
            TaxonOverrideApprovalStatus,
            name="taxonoverrideapprovalstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=TaxonOverrideApprovalStatus.APPLIED,
        server_default=text("'applied'::taxonoverrideapprovalstatus"),
        doc=(
            "Approval lifecycle (FR-034). Constrained to legal direction "
            "combinations by ck_taxon_overrides_direction_vs_approval."
        ),
    )
    requested_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User (typically project owner / admin) who requested the override.",
    )
    approved_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        doc=(
            "Superuser who approved the override (FR-034). Required when "
            "direction='looser' AND approval_status='applied'; NULL otherwise. "
            "The FK to ``superusers.id`` is enforced at the database level "
            "by the baseline Alembic migration; the ORM column is kept "
            "FK-less because the ``Superuser`` ORM class lives outside the "
            "permission models scope (added by a later phase)."
        ),
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Wall-clock timestamp of the approval (FR-034).",
    )
    rejected_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Free-form reason recorded by the superuser when rejecting (FR-034).",
    )

    # Relationships
    project: Mapped[Project] = relationship("Project")
    requested_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[requested_by_id],
    )

    __table_args__ = (
        CheckConstraint(
            "sensitivity_h3_res IN (2, 5, 7, 9, 15)",
            name="ck_taxon_overrides_h3_discrete",
        ),
        # FR-034: stricter ⇒ applied; looser may move through the approval
        # state machine. Pairs with the application-level guard that requires
        # an approver row before flipping looser to applied.
        CheckConstraint(
            "(direction = 'stricter' AND approval_status = 'applied')"
            " OR (direction = 'looser'"
            " AND approval_status IN ('pending_superuser_approval', 'applied', 'rejected'))",
            name="ck_taxon_overrides_direction_vs_approval",
        ),
        # FR-033 — exactly one *applied* override per (project, taxon) pair.
        # Mirrors the partial unique index in the baseline Alembic migration;
        # without it concurrent approve_override calls could leave the
        # masking pipeline reading two competing rows.
        Index(
            "ux_taxon_overrides_applied_unique",
            "project_id",
            "taxon_id",
            unique=True,
            postgresql_where=text("approval_status = 'applied'"),
        ),
        # Bulk preload by the masking utility — given a set of detections,
        # find all applied overrides matching their taxon_ids in one query.
        Index(
            "ix_taxon_overrides_taxon_approval",
            "taxon_id",
            "approval_status",
        ),
    )

    def __repr__(self) -> str:
        """String representation of ProjectTaxonSensitivityOverride."""
        return (
            "<ProjectTaxonSensitivityOverride("
            f"id={self.id}, project_id={self.project_id}, "
            f"taxon_id={self.taxon_id}, direction={self.direction}, "
            f"approval_status={self.approval_status}"
            ")>"
        )


__all__ = ["ProjectTaxonSensitivityOverride"]
