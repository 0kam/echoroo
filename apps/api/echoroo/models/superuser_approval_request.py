"""Superuser approval request — M-of-N approval workflow (FR-111).

Phase 15 Batch 1 (T950): the ``superuser_approval_requests`` table has
existed since the Phase 11 baseline (with the Phase 12 R3 split that
added ``requesting_user_id`` for project-owner-initiated tickets). This
module lifts it to the ORM following the Phase 13 P5 convention: the
ORM mirrors the canonical DB shape exactly, no schema changes are
emitted.

The schema below mirrors the live ``\\d superuser_approval_requests``
output and the baseline DDL in
``alembic/versions/0001_baseline_permissions_redesign.py`` (T020a).

Actor identity rule (CHECK ``ck_superuser_approval_requests_actor_present``):
exactly one of ``requested_by_id`` / ``requesting_user_id`` MUST be
populated per row (XOR). The split exists because tickets are opened
either by:

* a superuser performing operator triage (``requested_by_id`` set,
  FK → ``superusers.id``), or
* a regular user — typically a project owner / admin — invoking
  ``apply_taxon_override`` for a looser-direction request
  (``requesting_user_id`` set, FK → ``users.id``,
  ``ON DELETE SET NULL`` so a hard-deleted user does not orphan-delete
  the audit row).

``approvals`` is a JSONB array of ``{"superuser_id": ..., "approved_at":
...}`` records that the M-of-N gate aggregates against the configured
quorum.

``status`` is a free-form ``VARCHAR(20)`` (no enum type was minted) and
takes values from the set ``{'pending', 'applied', 'rejected'}`` per
spec data-model.md §3.3 and the application code that has been
operating against this table since Phase 11. Keeping it as a plain
string preserves wire compatibility with the legacy raw-SQL paths.

``executed_at`` records when the action was carried out (NULL while
``status = 'pending'`` or after a rejection).

Indexes (existing, unchanged by Phase 15):
- ``superuser_approval_requests_pkey`` on ``(id)``

The table has no btree index on ``created_at`` even though
:class:`TimestampMixin` declares ``index=True``; this asymmetry is
tolerated for tables outside the Phase 13 P5 normalized parity scope
(same pattern as :class:`Superuser`, ``project_taxon_sensitivity_overrides``,
``project_trusted_users``).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.superuser import Superuser
    from echoroo.models.user import User


class SuperuserApprovalRequest(UUIDMixin, TimestampMixin, Base):
    """M-of-N approval ticket for sensitive platform actions (FR-111).

    Rows track approval lifecycles for actions such as
    ``superuser_add``, ``looser_override_approve``, system_settings
    mutations, and other operations whose execution requires a quorum
    of active superusers. The ORM enforces the actor-XOR invariant via
    a database CHECK constraint so neither raw-SQL nor ORM callers can
    persist a row without a single, unambiguous initiator.
    """

    __tablename__ = "superuser_approval_requests"

    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc=(
            "Action identifier (e.g., 'superuser_add', "
            "'looser_override_approve'). Free-form string; consumers "
            "branch on the value to load the matching detail schema."
        ),
    )
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        doc=(
            "Action-specific payload (target ids, requested values, "
            "etc.). Shape is keyed off ``action`` and validated by the "
            "request handler."
        ),
    )
    requested_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("superusers.id"),
        nullable=True,
        doc=(
            "Superuser who opened the ticket via operator triage. "
            "Mutually exclusive with ``requesting_user_id`` (XOR CHECK)."
        ),
    )
    requesting_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            name="fk_superuser_approval_requests_requesting_user_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        doc=(
            "Regular user (project owner / admin) who opened the ticket "
            "via, e.g., ``apply_taxon_override``. ``ON DELETE SET NULL`` "
            "preserves the audit row when the user is hard-deleted. "
            "Mutually exclusive with ``requested_by_id`` (XOR CHECK)."
        ),
    )
    approvals: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        doc=(
            "Append-only list of approval records, each shaped "
            "``{\"superuser_id\": uuid, \"approved_at\": isoformat}``. "
            "The M-of-N gate compares ``len(approvals)`` against the "
            "configured quorum."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        doc=(
            "Lifecycle status. One of {'pending', 'applied', 'rejected'} "
            "(spec data-model.md §3.3). Stored as VARCHAR(20) — no enum "
            "type is minted — for compatibility with the legacy raw-SQL "
            "paths."
        ),
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc=(
            "Wall-clock timestamp at which the action was carried out. "
            "NULL while ``status='pending'`` or after a rejection."
        ),
    )

    # Relationships
    requested_by: Mapped[Superuser | None] = relationship(
        "Superuser",
        foreign_keys=[requested_by_id],
    )
    requesting_user: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[requesting_user_id],
    )

    __table_args__ = (
        # Actor-XOR invariant — exactly one of the two FKs must be set
        # per row. Mirrors the baseline Alembic migration so the ORM
        # cannot bypass the constraint.
        CheckConstraint(
            "(requested_by_id IS NOT NULL) <> (requesting_user_id IS NOT NULL)",
            name="ck_superuser_approval_requests_actor_present",
        ),
    )

    def __repr__(self) -> str:
        """String representation of SuperuserApprovalRequest."""
        return (
            f"<SuperuserApprovalRequest(id={self.id}, action={self.action!r}, "
            f"status={self.status!r})>"
        )


__all__ = ["SuperuserApprovalRequest"]
