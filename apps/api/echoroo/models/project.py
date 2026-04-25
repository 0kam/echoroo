"""Project and project membership models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)

if TYPE_CHECKING:
    from echoroo.models.user import User


class Project(UUIDMixin, TimestampMixin, Base):
    """Research project with permission redesign visibility and license state."""

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
    visibility: Mapped[ProjectVisibility] = mapped_column(
        Enum(
            ProjectVisibility,
            name="projectvisibility",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProjectVisibility.RESTRICTED,
        nullable=False,
        index=True,
        doc="Project visibility level",
    )
    license: Mapped[ProjectLicense] = mapped_column(
        Enum(
            ProjectLicense,
            name="projectlicense",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc="Project data license",
    )
    restricted_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        doc="Restricted visibility capability toggles",
    )
    restricted_config_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
        doc="Version for restricted_config shape",
    )
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(
            ProjectStatus,
            name="projectstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProjectStatus.ACTIVE,
        nullable=False,
        index=True,
        doc="Project lifecycle status",
    )
    dormant_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the project became dormant",
    )
    archived_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the project was archived",
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
        doc="Project owner user ID",
    )
    review_min_votes: Mapped[int] = mapped_column(
        Integer,
        default=2,
        nullable=False,
        doc="Minimum number of agree+disagree votes required before consensus is evaluated",
    )
    review_consensus_threshold: Mapped[float] = mapped_column(
        Float,
        default=0.667,
        nullable=False,
        doc="Fraction of agree/(agree+disagree) votes required to reach 'agreed' consensus",
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
    license_history: Mapped[list[ProjectLicenseHistory]] = relationship(
        "ProjectLicenseHistory",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "restricted_config IS NOT NULL "
            "AND jsonb_typeof(restricted_config) = 'object' "
            "AND (visibility <> 'restricted' OR ("
            "restricted_config ? 'allow_media_playback' "
            "AND restricted_config ? 'allow_detection_view' "
            "AND restricted_config ? 'mask_species_in_detection' "
            "AND restricted_config ? 'allow_download' "
            "AND restricted_config ? 'allow_export' "
            "AND restricted_config ? 'allow_voting_and_comments' "
            "AND restricted_config ? 'public_location_precision_h3_res' "
            "AND restricted_config ? 'allow_precise_location_to_viewer'"
            "))",
            name="ck_projects_restricted_config_shape",
        ),
        Index("ix_projects_status_dormant_since", "status", text("dormant_since DESC")),
    )

    def __repr__(self) -> str:
        """String representation of Project."""
        return f"<Project(id={self.id}, name={self.name})>"


class ProjectMember(UUIDMixin, TimestampMixin, Base):
    """Project membership with active-history semantics."""

    __tablename__ = "project_members"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Member user ID",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Project ID",
    )
    role: Mapped[ProjectMemberRole] = mapped_column(
        Enum(
            ProjectMemberRole,
            name="projectmemberrole",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProjectMemberRole.MEMBER,
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
        ForeignKey("users.id"),
        nullable=True,
        doc="User who sent the invitation",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Viewer access expiration timestamp",
    )
    removed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when this membership was removed",
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

    __table_args__ = (
        CheckConstraint(
            "role = 'viewer'::projectmemberrole OR expires_at IS NULL",
            name="ck_project_members_viewer_expires",
        ),
        Index(
            "ux_project_members_active",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("removed_at IS NULL"),
        ),
        Index("ix_project_members_project_role", "project_id", "role"),
        Index(
            "ix_project_members_user_project",
            "user_id",
            "project_id",
            postgresql_where=text("removed_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        """String representation of ProjectMember."""
        return f"<ProjectMember(user_id={self.user_id}, project_id={self.project_id}, role={self.role})>"


class ProjectLicenseHistory(UUIDMixin, TimestampMixin, Base):
    """Project license change history."""

    __tablename__ = "project_license_history"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Project ID",
    )
    old_license: Mapped[ProjectLicense | None] = mapped_column(
        Enum(
            ProjectLicense,
            name="projectlicense",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
        doc="Previous project license",
    )
    new_license: Mapped[ProjectLicense] = mapped_column(
        Enum(
            ProjectLicense,
            name="projectlicense",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc="New project license",
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Timestamp when the license changed",
    )
    changed_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who changed the license",
    )

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="license_history",
    )
    changed_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[changed_by_id],
    )

    __table_args__ = (
        Index(
            "ix_project_license_history_project_changed_at",
            "project_id",
            text("changed_at DESC"),
        ),
    )


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
    role: Mapped[ProjectMemberRole] = mapped_column(
        Enum(
            ProjectMemberRole,
            name="projectmemberrole",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ProjectMemberRole.MEMBER,
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
