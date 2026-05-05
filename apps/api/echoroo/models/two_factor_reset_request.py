"""Two-factor reset workflow ORM models (Phase 17 backlog A-11).

The workflow has three companion tables:

* :class:`TwoFactorResetRequest` — canonical state-machine row. One row
  per support ticket. See ``alembic/versions/0014_*`` for the in-flight
  unique partial index that prevents two pending requests for the same
  user.
* :class:`TwoFactorResetMagicLink` — short-lived magic-link token
  emailed to the user as part of the 4-factor identity verification.
  ``token_hash`` is SHA-256 hex of the raw token; the raw value is
  never persisted.
* :class:`TwoFactorConfirmationToken` — nonce row backing the HMAC
  confirmation token issued after a successful magic-link redeem. The
  ``used_at`` column is consumed under
  ``UPDATE ... WHERE used_at IS NULL RETURNING`` to enforce one-time
  use across concurrent admin redeems.

The status string set is intentionally a free-form ``VARCHAR`` (with a
DB-level CHECK constraint) rather than a PostgreSQL enum — extending an
enum requires a migration with ``ALTER TYPE`` and that is heavier than
this state machine warrants.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base

# Status literals — keep in lockstep with the CHECK constraint defined
# in ``alembic/versions/0014_two_factor_reset_requests.py``.
STATUS_PENDING_DELAY = "pending_delay"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_DISPATCHING = "dispatching"
STATUS_APPLIED = "applied"
STATUS_EXPIRED = "expired"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"

#: Statuses that count as "in-flight" — these are excluded by the
#: partial unique index ``ux_two_factor_reset_requests_active_user`` so
#: a single user can only have one row in this set at any given time.
ACTIVE_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_PENDING_DELAY,
        STATUS_PENDING_APPROVAL,
        STATUS_APPROVED,
        STATUS_DISPATCHING,
    }
)

#: Statuses the dispatch poller is allowed to consume.
DISPATCHABLE_STATUSES: frozenset[str] = frozenset(
    {STATUS_PENDING_DELAY, STATUS_APPROVED}
)


class TwoFactorResetRequest(Base):
    """Phase 17 A-11 canonical state-machine row."""

    __tablename__ = "two_factor_reset_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_delay','pending_approval','approved',"
            "'dispatching','applied','expired','cancelled','failed')",
            name="ck_two_factor_reset_requests_status",
        ),
        Index(
            "ix_two_factor_reset_requests_dispatch_at",
            "status",
            "dispatch_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by_superuser_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("superusers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    support_ticket_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    skip_delay: Mapped[bool] = mapped_column(
        Boolean(),
        nullable=False,
        server_default=text("false"),
    )
    dispatch_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    confirmation_token_nonce: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    approval_request_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("superuser_approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    #: Round-2 Fix-2: timestamp set when the dispatch poller transitions
    #: the row to ``dispatching``. The reclaim sweep uses this to revert
    #: stale rows back to ``pending_delay`` so a crashed worker cannot
    #: leave the partial unique index permanently blocking new requests.
    dispatching_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class TwoFactorResetMagicLink(Base):
    """Magic-link token emailed to the user as part of identity verification."""

    __tablename__ = "two_factor_reset_magic_links"
    __table_args__ = (
        Index(
            "ix_two_factor_reset_magic_links_user_expires",
            "user_id",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    requested_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    requested_user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class TwoFactorConfirmationToken(Base):
    """Nonce row backing the short-lived HMAC confirmation token."""

    __tablename__ = "two_factor_confirmation_tokens"
    __table_args__ = (
        Index(
            "ix_two_factor_confirmation_tokens_user_purpose_expires",
            "user_id",
            "purpose",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    nonce: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


__all__ = [
    "ACTIVE_STATUSES",
    "DISPATCHABLE_STATUSES",
    "STATUS_APPLIED",
    "STATUS_APPROVED",
    "STATUS_CANCELLED",
    "STATUS_DISPATCHING",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_PENDING_APPROVAL",
    "STATUS_PENDING_DELAY",
    "TwoFactorConfirmationToken",
    "TwoFactorResetMagicLink",
    "TwoFactorResetRequest",
]
