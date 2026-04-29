"""ApiKey model — programmatic access credential (FR-074..084).

Phase 15 Batch 3 (T155b): the ``api_keys`` table has existed since the
Phase 11 baseline migration (raw-SQL access path) and is now lifted to
the ORM following the Phase 13 P5 convention used for ``detections``:
the ORM mirrors the canonical DB shape exactly, no schema changes are
emitted.

The schema below mirrors the baseline DDL in
``alembic/versions/0001_baseline_permissions_redesign.py:1097`` and the
Phase 13 inventory:

- ``id`` UUID PK with ``gen_random_uuid()`` server default (supplied by
  :class:`UUIDMixin` via Python-side ``uuid4()``; the table-level server
  default is preserved by the baseline migration but never invoked from
  this ORM).
- ``user_id`` UUID NOT NULL, FK ``users.id`` — owner of the key.
- ``prefix`` VARCHAR(20) NOT NULL UNIQUE — the publicly-visible portion
  of the key used for fast lookup. Stored alongside ``hashed_secret`` so
  the secret part never lands in plain-text on disk.
- ``hashed_secret`` VARCHAR(64) NOT NULL — SHA-256 hex digest of the
  random secret part. Verified via constant-time compare.
- ``granted_permissions`` JSONB NOT NULL — array of scope strings
  (FR-074). CHECK constraint ``ck_api_keys_granted_permissions_array``
  enforces array shape at the DB layer.
- ``project_id`` UUID NULL, FK ``projects.id`` — when set, the key is
  scoped to operations against the named project. NULL means the key
  inherits the user's full project visibility.
- ``allowed_ip_cidrs`` ``VARCHAR[]`` NULL — optional CIDR allowlist.
- ``expires_at`` TIMESTAMPTZ NOT NULL — hard expiry deadline. CHECK
  constraint ``ck_api_keys_expires_at_window`` enforces a 2-year ceiling
  beyond ``created_at`` (FR-076).
- ``revoked_at`` / ``revoked_reason`` — non-NULL marks the key as
  withdrawn while preserving the audit row.
- ``last_used_at`` TIMESTAMPTZ NULL — debounced (1 minute) update by the
  verifier so legitimate hot-loop traffic does not pin the row.
- ``scope_violation_count_10min`` / ``ip_violation_count`` — counters
  used by the rate-limit / audit pipeline (FR-077, FR-091).

Indexes (existing, NOT recreated by Phase 15 — schema is unchanged):

- ``api_keys_pkey`` on ``(id)``
- ``api_keys_prefix_key`` UNIQUE on ``(prefix)`` — drives the verifier
  lookup.
- ``ix_api_keys_user_revoked`` on ``(user_id, revoked_at)``
- ``ix_api_keys_project_revoked`` on ``(project_id, revoked_at)``
- ``ix_api_keys_expires_at_active`` on ``(expires_at)`` WHERE
  ``revoked_at IS NULL``.

The table has no btree index on ``created_at`` even though
:class:`TimestampMixin` declares ``index=True``; this asymmetry is
tolerated for tables outside the Phase 13 P5 normalized parity scope
(same pattern as :class:`Superuser`).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


class ApiKey(UUIDMixin, TimestampMixin, Base):
    """Programmatic access credential (FR-074..084).

    Each row corresponds to a long-lived Bearer credential the caller
    presents on ``/api/v1/*``. The credential itself is never stored —
    only the public ``prefix`` plus a SHA-256 hash of the secret half.
    Verification reconstructs the hash from the inbound raw key and
    compares against ``hashed_secret`` in constant time.
    """

    __tablename__ = "api_keys"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="Owner user (FR-074). FK → users.id, no ON DELETE — keys are "
        "explicitly revoked, not cascade-deleted, so the audit chain "
        "remains intact.",
    )
    prefix: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        unique=True,
        doc=(
            "Public lookup token for the key. Format: "
            "``echoroo_<8-char-prefix>``. UNIQUE — the verifier looks up "
            "rows by prefix in O(1) before constant-time comparing the "
            "secret hash."
        ),
    )
    hashed_secret: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc=(
            "SHA-256 hex digest (64 chars) of the random secret half of "
            "the key. The secret is never persisted in plain text."
        ),
    )
    granted_permissions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        doc=(
            "JSONB array of scope strings (FR-074). The CHECK constraint "
            "``ck_api_keys_granted_permissions_array`` enforces array "
            "shape at the DB layer."
        ),
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id"),
        nullable=True,
        doc=(
            "Optional project scope. When set the key may only act on "
            "the named project; NULL means the key inherits the user's "
            "full visibility."
        ),
    )
    allowed_ip_cidrs: Mapped[list[str] | None] = mapped_column(
        ARRAY(String()),
        nullable=True,
        doc="Optional CIDR allowlist (FR-077).",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc=(
            "Hard expiry deadline (FR-076). CHECK "
            "``ck_api_keys_expires_at_window`` caps the window at 2 years "
            "beyond ``created_at``."
        ),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc=(
            "Revocation timestamp. Non-NULL marks the key as withdrawn; "
            "the row is preserved so audit references remain intact."
        ),
    )
    revoked_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Free-form reason recorded when ``revoked_at`` is set.",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc=(
            "Wall-clock timestamp of the most recent successful "
            "verification. Updated with a 1-minute debounce by the "
            "verifier so a hot-loop client does not pin the row."
        ),
    )
    scope_violation_count_10min: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0,
        doc=(
            "Rolling 10-minute count of scope-violation 403s used by the "
            "rate-limit / audit pipeline (FR-091)."
        ),
    )
    ip_violation_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("0"),
        default=0,
        doc="Cumulative count of CIDR-allowlist violations (FR-077).",
    )

    # Relationships — defined as forward references to avoid import cycles.
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    project: Mapped[Project | None] = relationship(
        "Project", foreign_keys=[project_id]
    )

    __table_args__ = (
        CheckConstraint(
            "expires_at > created_at AND expires_at <= created_at + INTERVAL '2 years'",
            name="ck_api_keys_expires_at_window",
        ),
        CheckConstraint(
            "jsonb_typeof(granted_permissions) = 'array'",
            name="ck_api_keys_granted_permissions_array",
        ),
        Index("ix_api_keys_user_revoked", "user_id", "revoked_at"),
        Index("ix_api_keys_project_revoked", "project_id", "revoked_at"),
        Index(
            "ix_api_keys_expires_at_active",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        """String representation of ApiKey."""
        return (
            f"<ApiKey(id={self.id}, prefix={self.prefix!r}, "
            f"revoked_at={self.revoked_at})>"
        )


__all__ = ["ApiKey"]
