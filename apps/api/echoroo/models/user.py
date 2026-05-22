"""User model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Integer, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.project import Project, ProjectMember


class User(UUIDMixin, TimestampMixin, Base):
    """User entity aligned with the permissions-redesign baseline schema."""

    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_deleted_at", "deleted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    two_factor_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    two_factor_secret_encrypted: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    two_factor_secret_dek_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    two_factor_backup_codes_hashed: Mapped[list[str] | None] = mapped_column(
        ARRAY(String()),
        nullable=True,
    )
    security_stamp: Mapped[str] = mapped_column(String(64), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_first_party_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # spec/011 §FR-011-203 / FR-011-204 — forced password change gate.
    # ``must_change_password`` is read by ``ForcedPasswordChangeMiddleware``
    # on every authenticated request; ``temp_password_expires_at`` bounds
    # the validity of the temporary password issued by the admin-reset
    # flow (FR-011-203, 24h TTL). Both columns were added in migration
    # 0021_zero_email_additive (Step 1).
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    temp_password_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # spec/011 §FR-011-305 — 24h cool-off enforced after a successful
    # ``change_email``. The column was added in migration 0021 alongside
    # ``must_change_password`` / ``temp_password_expires_at``; the ORM
    # field is required so the change-email service (FR-011-305) and the
    # email-change banner surface (FR-011-301 / FR-011-302) can read and
    # write the cool-off wall-clock from Python without dropping into raw
    # SQL.
    email_change_cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    registered_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    two_factor_reset_cooldown_until: Mapped[datetime | None] = mapped_column(
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

    owned_projects: Mapped[list[Project]] = relationship(
        "Project",
        foreign_keys="Project.owner_id",
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    project_memberships: Mapped[list[ProjectMember]] = relationship(
        "ProjectMember",
        foreign_keys="ProjectMember.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """String representation of User."""
        return f"<User(id={self.id}, email={self.email})>"
