"""User and authentication models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.project import Project, ProjectMember


class User(UUIDMixin, TimestampMixin, Base):
    """User entity for authentication and profile management.

    This model represents a user account with authentication credentials
    and profile information. Initially implemented for User Story 6 (Initial Setup),
    extended in User Story 1 for full authentication functionality.

    Attributes:
        id: Unique identifier (UUID, from UUIDMixin)
        email: User's email address (unique, used for login)
        hashed_password: Argon2id hashed password
        display_name: Optional display name
        organization: Optional organization/affiliation
        is_active: Whether the account is active
        is_superuser: System administrator flag
        is_verified: Email verification status
        created_at: Account creation timestamp (from TimestampMixin)
        updated_at: Last update timestamp (from TimestampMixin)
        last_login_at: Last successful login timestamp
        email_verification_token: Token for email verification
        email_verification_expires_at: Expiration time for email verification token
        password_reset_token: Token for password reset
        password_reset_expires_at: Expiration time for password reset token
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        doc="User's email address",
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Argon2id hashed password",
    )
    display_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="User's display name",
    )
    organization: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        doc="User's organization or affiliation",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        doc="Account active status",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="System administrator flag",
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Email verification status",
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Last successful login timestamp",
    )
    email_verification_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Email verification token",
    )
    email_verification_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Email verification token expiration",
    )
    password_reset_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Password reset token",
    )
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Password reset token expiration",
    )

    # Relationships
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
    api_tokens: Mapped[list[APIToken]] = relationship(
        "APIToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """String representation of User."""
        return f"<User(id={self.id}, email={self.email})>"


class LoginAttempt(UUIDMixin, Base):
    """Login attempt tracking for security and rate limiting.

    Records all login attempts (successful and failed) for security monitoring,
    rate limiting, and account locking after too many failed attempts.

    Attributes:
        id: Unique identifier (UUID, from UUIDMixin)
        email: Email address used in login attempt
        ip_address: IP address of the client
        success: Whether the login was successful
        attempted_at: Timestamp of the attempt
        user_agent: User agent string from request headers
        user_id: Foreign key to users table (null for failed attempts)
    """

    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Email address used in login attempt",
    )
    ip_address: Mapped[str] = mapped_column(
        String(45),
        nullable=False,
        index=True,
        doc="IP address of the client (supports IPv6)",
    )
    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        index=True,
        doc="Whether the login was successful",
    )
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="Timestamp of the login attempt",
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="User agent string from request headers",
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        doc="Foreign key to users table (null for failed attempts)",
    )

    # Composite indexes for rate limiting queries
    __table_args__ = (
        Index("ix_login_attempts_email_attempted_at", "email", "attempted_at"),
        Index("ix_login_attempts_ip_address_attempted_at", "ip_address", "attempted_at"),
    )

    def __repr__(self) -> str:
        """String representation of LoginAttempt."""
        return f"<LoginAttempt(email={self.email}, success={self.success})>"


class APIToken(UUIDMixin, Base):
    """API token for programmatic access.

    API tokens provide an alternative to JWT for programmatic access to the API.
    Tokens are prefixed with 'ecr_' and stored as SHA256 hashes.

    Attributes:
        id: Unique identifier (UUID, from UUIDMixin)
        user_id: Foreign key to users table
        token_hash: SHA256 hash of the token
        name: Human-readable name for the token
        last_used_at: Timestamp of the last usage
        expires_at: Optional expiration timestamp
        is_active: Whether the token is active
        created_at: Token creation timestamp
    """

    __tablename__ = "api_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Foreign key to users table",
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        doc="SHA256 hash of the token",
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Human-readable name for the token",
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of the last usage",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Optional expiration timestamp",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        index=True,
        doc="Whether the token is active",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Token creation timestamp",
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        back_populates="api_tokens",
    )

    def __repr__(self) -> str:
        """String representation of APIToken."""
        return f"<APIToken(id={self.id}, name={self.name})>"
