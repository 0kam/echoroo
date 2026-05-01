"""Superuser model — platform-level operator entitlement (FR-111, FR-072).

Phase 15 Batch 1 (T950): the ``superusers`` table has existed in the
database since the Phase 11 / 12 migrations (raw-SQL access path) and is
now lifted to the ORM following the Phase 13 P5 convention used for
``detections``: the ORM mirrors the canonical DB shape exactly, no
schema changes are emitted.

The schema below mirrors the live ``\\d superusers`` output captured in
Phase 15 inventory and the baseline DDL in
``alembic/versions/0001_baseline_permissions_redesign.py`` (T020a):

- ``id`` UUID PK with ``gen_random_uuid()`` server default (supplied by
  :class:`UUIDMixin` via Python-side ``uuid4()``; the table-level server
  default is preserved by the baseline migration but never invoked from
  this ORM).
- ``user_id`` UUID NOT NULL UNIQUE, FK ``users.id`` (no ON DELETE — a
  superuser row must be revoked explicitly; the spec disallows cascade
  delete because the audit trail must point at the historical user even
  after a hard delete is requested).
- ``added_by_id`` UUID NULL, FK ``users.id`` — NULL for the bootstrap
  superuser (no actor exists when the first superuser is seeded).
- ``added_at`` TIMESTAMPTZ NOT NULL — wall-clock timestamp of the
  promotion. Distinct from ``created_at`` because operators may pre-date
  rows during a recovery import.
- ``revoked_at`` TIMESTAMPTZ NULL — non-NULL marks the entitlement as
  withdrawn while preserving the row for audit (FR-111). Indexed by
  ``ix_superusers_revoked_at`` to support the "active superusers" query
  used by the M-of-N approval engine.
- ``webauthn_credentials`` JSONB NOT NULL DEFAULT ``'[]'::jsonb`` —
  spec FR-111 requires at least two registered authenticators per
  superuser. Application-layer enforcement; the JSONB shape is
  ``[{"credential_id": ..., "public_key": ..., "sign_count": ...}]``.
- ``allowed_ip_cidrs`` ``VARCHAR[]`` NOT NULL DEFAULT ``ARRAY[]::varchar[]``
  — optional CIDR allowlist enforced by the auth middleware (FR-072).
- ``created_at`` / ``updated_at`` TIMESTAMPTZ NOT NULL — supplied by
  :class:`TimestampMixin`. The DB column does NOT have a btree index on
  ``created_at`` even though the mixin declares ``index=True``; this
  asymmetry is tolerated for tables outside the Phase 13 P5 normalized
  parity scope (matches the existing pattern used by
  ``project_taxon_sensitivity_overrides`` and ``project_trusted_users``).

Indexes (existing, NOT recreated by Phase 15 — schema is unchanged):

- ``superusers_pkey`` on ``(id)``
- ``superusers_user_id_key`` UNIQUE on ``(user_id)``
- ``ix_superusers_revoked_at`` on ``(revoked_at)``

DB Trigger (FR-111a): ``superuser_last_protection`` BEFORE DELETE blocks
removal of the last non-revoked superuser unless the session variable
``app.superuser_deletion_override`` is set to ``'true'`` (creator_founder
override path). The trigger is defined in the baseline migration and is
not represented in the ORM.

Referenced by: ``project_taxon_sensitivity_overrides.approved_by_id``,
``superuser_approval_requests.requested_by_id``,
``system_settings.updated_by_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import ARRAY, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.user import User


class Superuser(UUIDMixin, TimestampMixin, Base):
    """Platform-level operator entitlement (FR-111, FR-072).

    A ``Superuser`` row grants its referenced :class:`User` access to the
    M-of-N approval engine, the system_settings mutation surface, and the
    looser-direction taxon override approval workflow. The entitlement is
    intentionally tracked in a separate table (rather than as a flag on
    ``users``) so it can carry its own auth material (WebAuthn
    credentials), its own IP allowlist, and a distinct revocation
    timestamp without bloating the user row.

    The class is FK-target for several other tables; see the module
    docstring for the inbound reference list.
    """

    __tablename__ = "superusers"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
        doc="Underlying user account (FR-111). UNIQUE — at most one superuser row per user.",
    )
    added_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        doc=(
            "User who promoted this account (FR-111). NULL for the "
            "bootstrap superuser; otherwise points at a user whose own "
            "superuser row may have since been revoked."
        ),
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Wall-clock timestamp of the promotion (FR-111).",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc=(
            "Wall-clock timestamp of revocation (FR-111). NULL means the "
            "entitlement is active. Indexed for the active-superusers "
            "lookup used by the M-of-N approval engine."
        ),
    )
    webauthn_credentials: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
        doc=(
            "Registered WebAuthn authenticators (FR-111). Application "
            "layer enforces the spec requirement of >= 2 entries before "
            "the superuser may execute approval actions."
        ),
    )
    allowed_ip_cidrs: Mapped[list[str]] = mapped_column(
        ARRAY(String()),
        nullable=False,
        default=list,
        server_default=text("ARRAY[]::varchar[]"),
        doc=(
            "Optional CIDR allowlist enforced by auth middleware "
            "(FR-072). Empty array means no IP restriction."
        ),
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
    )
    added_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[added_by_id],
    )

    __table_args__ = (Index("ix_superusers_revoked_at", "revoked_at"),)

    def __repr__(self) -> str:
        """String representation of Superuser."""
        return (
            f"<Superuser(id={self.id}, user_id={self.user_id}, "
            f"revoked_at={self.revoked_at})>"
        )


__all__ = ["Superuser"]
