"""Trusted device model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base


class TrustedDevice(Base):
    """Remembered 2FA device for routine future logins."""

    __tablename__ = "trusted_devices"
    __table_args__ = (
        Index(
            "ix_trusted_devices_active_device_secret_hash",
            "device_secret_hash",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "ix_trusted_devices_user_revoked_expires",
            "user_id",
            "revoked_at",
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
    device_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    security_stamp: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
