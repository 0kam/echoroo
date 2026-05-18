"""Email verification token model."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base


class EmailVerificationToken(Base):
    """One-time token for proving control of an account email address."""

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        Index(
            "ix_email_verification_tokens_active_token_hash",
            "token_hash",
            unique=True,
            postgresql_where=text(
                "consumed_at IS NULL AND superseded_at IS NULL",
            ),
        ),
        Index(
            "ix_email_verification_tokens_active_user_purpose_email",
            "user_id",
            "purpose",
            "email_normalized",
            unique=True,
            postgresql_where=text(
                "consumed_at IS NULL AND superseded_at IS NULL",
            ),
        ),
        Index(
            "ix_email_verification_tokens_user_purpose_state_expires",
            "user_id",
            "purpose",
            "consumed_at",
            "superseded_at",
            "expires_at",
        ),
        Index("ix_email_verification_tokens_expires_at", "expires_at"),
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
    email_normalized: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
