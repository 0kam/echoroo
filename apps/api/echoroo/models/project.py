"""Project and project membership models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
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
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)

if TYPE_CHECKING:
    from echoroo.models.license import License
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
    target_taxa: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Operator-typed comma-separated focus taxa (e.g. 'Birds, Anurans').",
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
    license_id: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("licenses.id", ondelete="RESTRICT"),
        nullable=True,
        doc="Project data license ID",
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
    license_record: Mapped[License | None] = relationship(
        "License",
        lazy="selectin",
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

    @property
    def license(self) -> str | None:
        """Read-only access to the attached license short name."""
        if self.license_record is not None:
            return self.license_record.short_name
        return None


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
    old_license: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        doc="Previous project license",
    )
    new_license: Mapped[str] = mapped_column(
        String(50),
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


class ProjectInvitation(UUIDMixin, TimestampMixin, Base):
    """Pending project invitation row (Member or Trusted, FR-047 / FR-048).

    A single ``project_invitations`` table backs both Member invitations and
    Trusted overlay invitations. The ``kind`` discriminator selects which
    subset of columns is populated and the database enforces the constraint
    via ``ck_project_invitations_kind_fields``:

    * ``kind = 'member'``  → ``role`` set, ``granted_permissions`` and
      ``trusted_duration_seconds`` NULL.
    * ``kind = 'trusted'`` → ``role`` NULL, ``granted_permissions`` is a
      non-empty JSONB array (Permission enum names), and
      ``trusted_duration_seconds`` ∈ [1, 31_536_000] (1 second–1 year).

    Email is stored as ``email_hash`` (HMAC-SHA-256, 64 hex chars) so an
    attacker cannot enumerate addresses (FR-055). The plain ``email``
    column exists only as an operator-readable convenience for emails the
    system itself sent — it is nullable and may be cleared at any time;
    runtime lookups go through ``email_hash``.

    Status × timestamp consistency is guarded by
    ``ck_project_invitations_status_timestamps`` so an ``accepted`` row
    always carries ``accepted_at IS NOT NULL`` (and similarly for
    ``declined`` / ``revoked``).
    """

    __tablename__ = "project_invitations"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        # No implicit single-column index: the baseline migration only
        # declares ``ux_project_invitations_pending`` (partial unique on
        # ``project_id, email_hash WHERE status='pending'``) and
        # ``ix_project_invitations_status_expires``. Both cover the runtime
        # access patterns; an extra ``project_id`` btree would be unused.
        doc="Target project ID",
    )
    kind: Mapped[ProjectInvitationKind] = mapped_column(
        Enum(
            ProjectInvitationKind,
            name="invitationkind",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc="Invitation kind: member or trusted (FR-047)",
    )
    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc=(
            "Plaintext invitee email — kept for operator readability of the "
            "outgoing message; runtime lookups use email_hash (FR-055)."
        ),
    )
    email_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc=(
            "HMAC-SHA-256 hex digest of the NFKC-normalised lowercased email "
            "(FR-055 enumeration mitigation)."
        ),
    )
    # Phase 17 backlog A-2 (FR-091b) — KMS-backed sibling hash that
    # supports CMK rotation without re-writing historical rows.
    #
    # Round 2 R1-C1: ``email_hash_v2`` is *strictly* a v2-mode column.
    # It is NULL whenever the row was inserted while
    # :func:`echoroo.core.kms.get_pii_hash_version` returned ``1``
    # (i.e. pre-rotation single-key deployment OR a row inserted before
    # Alembic 0016). The daily ``pii_hash_backfill_invitations`` task
    # selects on ``email_hash_v2 IS NULL AND email IS NOT NULL`` and
    # fills both this column and ``pii_hash_version`` once an operator
    # flips the v2 alias on. Writers must therefore NEVER stuff the
    # v1 hash into this column as a placeholder — doing so hides the
    # row from the backfill sweep and the rotation never completes.
    email_hash_v2: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc=(
            "KMS-keyed v2 hash (FR-091b). NULL until rotation begins or "
            "the daily backfill worker fills it. Lookups try this column "
            "first, then fall back to the legacy ``email_hash``."
        ),
    )
    pii_hash_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc=(
            "PII hash CMK generation. NULL = single-key / pre-rotation "
            "row. 2 = row was hashed while rotation was active and the "
            "v2 column was populated synchronously (FR-091b)."
        ),
    )
    role: Mapped[ProjectMemberRole | None] = mapped_column(
        Enum(
            ProjectMemberRole,
            name="projectmemberrole",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
        doc="Role to assign on accept (Member invitations only).",
    )
    granted_permissions: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc=(
            "Trusted invitations only: JSONB array of Permission enum names "
            "to grant on accept (FR-042 — must be a TRUSTED_ALLOWED_PERMISSIONS "
            "subset)."
        ),
    )
    trusted_duration_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc=(
            "Trusted invitations only: validity window in seconds, "
            "1 ≤ x ≤ 31_536_000 (1 year, FR-043). expires_at on the resulting "
            "ProjectTrustedUser row is computed as granted_at + this value."
        ),
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        doc=(
            "SHA-256 hex digest of the 256-bit raw invitation token. The raw "
            "token is sent in email and never persisted (FR-051)."
        ),
    )
    invited_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who issued the invitation.",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="HMAC + DB-level expiry of the invitation token (FR-052: 7 days).",
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Set atomically with status='accepted' (FR-053).",
    )
    declined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Set atomically with status='declined' (recipient self-decline, T512).",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Set atomically with status='revoked' (Owner/Admin revoke).",
    )
    status: Mapped[ProjectInvitationStatus] = mapped_column(
        Enum(
            ProjectInvitationStatus,
            name="invitationstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ProjectInvitationStatus.PENDING,
        server_default=text("'pending'::invitationstatus"),
        doc="Invitation lifecycle state (FR-053).",
    )
    # spec/011 FR-011-122 — SU bootstrap ownership transfer flag.
    #
    # Added by Alembic migration 0021_zero_email_additive. When True the
    # invitation MUST be a Member-kind row (R5 — enforced both by the DB
    # CHECK ``ck_project_invitations_ownership_transfer_kind_member`` AND
    # by the application-level guard in
    # ``services.invitation_service.create_invitation`` /
    # ``accept_invitation``). The role=ADMIN requirement of FR-011-121 is
    # enforced upstream at the SU bootstrap create-project endpoint
    # (Step 9 T501), not by R5 itself — the CHECK only constrains kind,
    # which matches both the migration and the service guard. On accept,
    # the same transaction transfers project ownership from the SU
    # placeholder to the accepting user (Step 9 wires the
    # SAVEPOINT-nested transfer; this column lands in Step 1 + Step 6 so
    # service-layer code can populate it).
    ownership_transfer_on_accept: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        doc=(
            "spec/011 FR-011-122..125: when True, accepting this invitation "
            "transfers project ownership to the accepter. Only valid for "
            "kind='member' (R5, CHECK + service guard). The role=ADMIN "
            "requirement of FR-011-121 is enforced upstream at the SU "
            "bootstrap create-project endpoint, not by this CHECK."
        ),
    )

    # Relationships
    project: Mapped[Project] = relationship("Project")
    invited_by: Mapped[User] = relationship("User")

    __table_args__ = (
        # FR-048 — kind × field consistency. Mirrors the DB CHECK in the
        # baseline migration (0001_baseline_permissions_redesign).
        CheckConstraint(
            "kind IS NOT NULL AND status IS NOT NULL AND ("
            "(kind = 'member' AND role IS NOT NULL "
            " AND granted_permissions IS NULL "
            " AND trusted_duration_seconds IS NULL)"
            " OR "
            "(kind = 'trusted' AND role IS NULL "
            " AND jsonb_typeof(granted_permissions) = 'array' "
            " AND trusted_duration_seconds IS NOT NULL "
            " AND trusted_duration_seconds BETWEEN 1 AND 31536000))",
            name="ck_project_invitations_kind_fields",
        ),
        CheckConstraint(
            "(status = 'accepted' AND accepted_at IS NOT NULL "
            "  AND declined_at IS NULL AND revoked_at IS NULL) "
            "OR (status = 'declined' AND declined_at IS NOT NULL "
            "  AND accepted_at IS NULL AND revoked_at IS NULL) "
            "OR (status = 'revoked' AND revoked_at IS NOT NULL) "
            "OR (status = 'pending' AND accepted_at IS NULL "
            "  AND declined_at IS NULL AND revoked_at IS NULL) "
            "OR (status = 'expired' AND accepted_at IS NULL "
            "  AND declined_at IS NULL)",
            name="ck_project_invitations_status_timestamps",
        ),
        # spec/011 R5 — mirrors the DB CHECK in migration
        # ``0021_zero_email_additive``:
        # ``ownership_transfer_on_accept = false OR kind = 'member'``.
        # Without this mirror the next Alembic autogenerate would emit
        # a spurious "remove constraint" diff against the migration.
        CheckConstraint(
            "ownership_transfer_on_accept = false OR kind = 'member'",
            name="ck_project_invitations_ownership_transfer_kind_member",
        ),
        # FR-049 — at most one pending invitation per (project, email_hash);
        # kind is intentionally NOT in the key so a pending Member and pending
        # Trusted for the same email cannot coexist.
        Index(
            "ux_project_invitations_pending",
            "project_id",
            "email_hash",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_project_invitations_status_expires",
            "status",
            "expires_at",
        ),
    )

    def __repr__(self) -> str:
        """String representation of ProjectInvitation."""
        return (
            "<ProjectInvitation("
            f"id={self.id}, project_id={self.project_id}, "
            f"kind={self.kind}, status={self.status}"
            ")>"
        )
