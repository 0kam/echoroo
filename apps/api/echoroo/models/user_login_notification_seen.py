"""Tracks (IP, UA) tuples we have already notified a user about (FR-104).

Storage layout aligned with the 0004 Alembic migration. The two hashes
are produced by :func:`echoroo.core.kms.compute_pii_hash` so even a
full DB compromise cannot reveal the raw IPs / user agents — the HMAC
key never leaves KMS.

Lifecycle:

* On a successful login the
  :class:`echoroo.services.login_notification_service.LoginNotificationService`
  computes ``ip_hash`` + ``ua_hash`` and looks up an existing row.
* If the row exists and ``last_seen_at`` is younger than
  :data:`echoroo.services.login_notification_service.LOGIN_RECORD_RETENTION`,
  the login is treated as "seen" and no notification is enqueued.
* Otherwise the service ``UPSERT``s the row with the current timestamp
  and enqueues an :class:`OutboxEvent` (``event_type='login_notification'``)
  for the dispatcher.
* The Phase-3 background reaper (``cleanup_expired_login_notifications``,
  TODO) drops rows older than 30 days so the table does not grow
  unbounded.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base


class UserLoginNotificationSeen(Base):
    """One row per (user, IP-hash, UA-hash) tuple seen in the last 30 days."""

    __tablename__ = "user_login_notifications_seen"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "ip_hash",
            "ua_hash",
            name="uq_user_login_notifications_seen_tuple",
        ),
        Index(
            "ix_user_login_notifications_seen_user_id",
            "user_id",
        ),
        Index(
            "ix_user_login_notifications_seen_last_seen_at",
            "last_seen_at",
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
    # 64-character lowercase hex output of HMAC-SHA256 (compute_pii_hash).
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ua_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
