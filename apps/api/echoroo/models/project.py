"""Project and project membership models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import ProjectRole, ProjectVisibility

if TYPE_CHECKING:
    from echoroo.models.user import User


class Project(UUIDMixin, TimestampMixin, Base):
    """Project entity for research project management.

    This model represents a research project with members, settings, and data.
    Projects can be private (default) or public, and have an owner who created them.

    Attributes:
        id: Unique identifier (UUID, from UUIDMixin)
        name: Project name (required, max 200 chars)
        description: Optional project description
        target_taxa: Optional comma-separated target taxonomic groups (max 500 chars)
        visibility: Project visibility ('private' or 'public')
        owner_id: Foreign key to user who owns the project
        created_at: Project creation timestamp (from TimestampMixin)
        updated_at: Last update timestamp (from TimestampMixin)
        owner: Relationship to User model (project owner)
        members: Relationship to ProjectMember model (project members)
    """

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Project name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Project description",
    )
    target_taxa: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Target taxonomic groups (comma-separated)",
    )
    visibility: Mapped[ProjectVisibility] = mapped_column(
        default=ProjectVisibility.PRIVATE,
        nullable=False,
        index=True,
        doc="Project visibility level",
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Project owner user ID",
    )

    # Relationships
    owner: Mapped[User] = relationship(
        "User",
        foreign_keys=[owner_id],
        back_populates="owned_projects",
        lazy="joined",
    )
    members: Mapped[list[ProjectMember]] = relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        """String representation of Project."""
        return f"<Project(id={self.id}, name={self.name})>"


class ProjectMember(UUIDMixin, Base):
    """Project membership junction table with roles.

    This model represents a user's membership in a project with a specific role.
    Each user can have only one membership per project (enforced by unique constraint).

    Attributes:
        id: Unique identifier (UUID, from UUIDMixin)
        user_id: Foreign key to user
        project_id: Foreign key to project
        role: Member's role in the project ('admin', 'member', or 'viewer')
        joined_at: Timestamp when user joined the project
        invited_by_id: Optional foreign key to user who sent the invitation
        user: Relationship to User model
        project: Relationship to Project model
        invited_by: Relationship to User model (inviter)
    """

    __tablename__ = "project_members"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Member user ID",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Project ID",
    )
    role: Mapped[ProjectRole] = mapped_column(
        default=ProjectRole.MEMBER,
        nullable=False,
        doc="Member role in project",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp when user joined",
    )
    invited_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who sent the invitation",
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[user_id],
        back_populates="project_memberships",
        lazy="joined",
    )
    project: Mapped[Project] = relationship(
        "Project",
        back_populates="members",
    )
    invited_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[invited_by_id],
    )

    # Unique constraint: one membership per user per project
    # Composite index for efficient JOIN queries
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_user_project"),
        Index("ix_project_members_project_id_user_id", "project_id", "user_id"),
    )

    def __repr__(self) -> str:
        """String representation of ProjectMember."""
        return f"<ProjectMember(user_id={self.user_id}, project_id={self.project_id}, role={self.role})>"


class ProjectInvitation(UUIDMixin, Base):
    """Pending project invitations.

    This model represents invitations sent to users (by email) to join a project.
    Used for invitation-only registration mode or to invite existing users.

    Attributes:
        id: Unique identifier (UUID, from UUIDMixin)
        project_id: Foreign key to project
        email: Email address of invitee
        role: Role to assign on acceptance
        token_hash: SHA256 hash of invitation token
        invited_by_id: Foreign key to user who sent invitation
        expires_at: Token expiration timestamp (default: 7 days)
        accepted_at: Optional timestamp when invitation was accepted
        created_at: Invitation creation timestamp
        project: Relationship to Project model
        invited_by: Relationship to User model (inviter)
    """

    __tablename__ = "project_invitations"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Target project ID",
    )
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        doc="Invitee email address",
    )
    role: Mapped[ProjectRole] = mapped_column(
        default=ProjectRole.MEMBER,
        nullable=False,
        doc="Role to assign on acceptance",
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="SHA256 hash of invitation token",
    )
    invited_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who sent the invitation",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Token expiration timestamp",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when invitation was accepted",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Invitation creation timestamp",
    )

    # Relationships
    project: Mapped[Project] = relationship("Project")
    invited_by: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        """String representation of ProjectInvitation."""
        return f"<ProjectInvitation(email={self.email}, project_id={self.project_id})>"
