"""User banner dismissal ORM model — spec/011 zero-email deployment.

Backs the ``user_banner_dismissals`` table introduced by migration
``0021_zero_email_additive`` (see ``data-model.md §user_banner_dismissals``
and ``spec.md §FR-011-301``). The table is polymorphic over the two audit
tables (``project_audit_log`` and ``platform_audit_log``) — Postgres does
not natively support polymorphic foreign keys, so ``audit_log_id`` is
deliberately NOT bound by an FK constraint; the integrity invariant is
enforced at write time by :mod:`echoroo.services.user_banner`.

The composite primary key ``(user_id, audit_table, audit_log_id)`` also
serves as the index for "list dismissals for this user" via leading-column
prefix scans, so no secondary index is declared.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base


class UserBannerDismissal(Base):
    """Per-user dismissal of an in-app banner event.

    Banner content is a row in either ``project_audit_log`` or
    ``platform_audit_log``; this row records that ``user_id`` has
    dismissed that specific audit row so it no longer surfaces from
    ``GET /web-api/v1/me/banners`` (FR-011-302). The dismissal does
    NOT affect ``GET /web-api/v1/me/activity`` (FR-011-307) — the
    activity view is the permanent record.
    """

    __tablename__ = "user_banner_dismissals"
    __table_args__ = (
        CheckConstraint(
            "audit_table IN ('project_audit_log', 'platform_audit_log')",
            name="ck_user_banner_dismissals_audit_table",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_banner_dismissals_user_id"),
        primary_key=True,
        nullable=False,
    )
    audit_table: Mapped[str] = mapped_column(
        # ``Text`` (not ``String``) to mirror migration ``0021`` which
        # emits ``sa.Text()`` plus the data-model.md declaration of
        # the column as ``TEXT``. Polymorphic FK targets are
        # constrained by the CHECK constraint, not by a length cap.
        Text,
        primary_key=True,
        nullable=False,
    )
    audit_log_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        nullable=False,
    )
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        """String representation of UserBannerDismissal."""
        return (
            f"<UserBannerDismissal(user_id={self.user_id}, "
            f"audit_table={self.audit_table}, audit_log_id={self.audit_log_id})>"
        )
