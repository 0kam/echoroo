"""Trusted User overlay row (006-permissions-redesign, FR-041 / FR-044).

A :class:`ProjectTrustedUser` is the *capability overlay* on top of an
already-Authenticated principal. Owners/Admins issue them via
:class:`ProjectInvitation` (``kind='trusted'``); on accept the invitation
service creates one row here per (project, user) pair with:

* ``granted_permissions``  – JSONB array of Permission enum names. Must be a
  subset of ``TRUSTED_ALLOWED_PERMISSIONS`` (FR-012). The permission engine
  re-intersects with the allowlist at every request as a runtime safety net
  (FR-014, see :func:`echoroo.core.permissions.active_trusted_capabilities`).
* ``expires_at``            – computed as ``granted_at + duration``, capped at
  ``granted_at + 1 year`` by the ``ck_trusted_users_duration_within_one_year``
  DB constraint (FR-043).
* ``status``                – ``active`` is the only value that grants
  capability. ``expired`` is set by the auto-expire worker (T516); ``revoked``
  by Owner/Admin via :func:`echoroo.services.trusted_service.revoke_trusted_user`.

The capability is **never** baked into the JWT — :func:`is_allowed` reads
this row on every request (FR-044). The `(project_id, user_id)` partial
unique index (``status='active'``) ensures the engine sees at most one
active overlay per pair.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import ProjectTrustedStatus

if TYPE_CHECKING:
    from echoroo.models.project import Project, ProjectInvitation
    from echoroo.models.user import User


class ProjectTrustedUser(UUIDMixin, TimestampMixin, Base):
    """Capability overlay row granted to an Authenticated principal.

    See module docstring for the full FR mapping. The ``__table_args__``
    mirror the baseline Alembic migration:

    * ``ck_trusted_users_permissions_non_empty_array``  – ``granted_permissions``
      must be a non-empty JSONB array (FR-042).
    * ``ck_trusted_users_duration_within_one_year``    – ``expires_at`` is in
      ``(granted_at, granted_at + 1 year]`` (FR-043).
    * ``ux_project_trusted_users_active``              – partial unique index
      on ``(project_id, user_id)`` filtered by ``status = 'active'`` so the
      gate never has to reconcile two overlays for the same pair.
    """

    __tablename__ = "project_trusted_users"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Target project (FR-041).",
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="Authenticated principal receiving the overlay (FR-041).",
    )
    invitation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("project_invitations.id"),
        nullable=False,
        doc="Source invitation row whose accept created this overlay (FR-041).",
    )
    granted_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who issued the originating invitation (FR-041).",
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Wall-clock timestamp at which the overlay started (FR-043).",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc=(
            "Wall-clock timestamp at which the overlay automatically lapses. "
            "Bound by ck_trusted_users_duration_within_one_year (FR-043)."
        ),
    )
    status: Mapped[ProjectTrustedStatus] = mapped_column(
        Enum(
            ProjectTrustedStatus,
            name="trusteduserstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ProjectTrustedStatus.ACTIVE,
        server_default=text("'active'::trusteduserstatus"),
        doc="Lifecycle of the overlay (FR-044).",
    )
    granted_permissions: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        doc=(
            "JSONB array of Permission enum names. The permission engine "
            "intersects with TRUSTED_ALLOWED_PERMISSIONS at every request "
            "(FR-014 runtime safety net)."
        ),
    )
    email_at_invitation: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc=(
            "Plaintext invitee email captured at accept time, kept for audit "
            "readability (FR-041). Nullable because operators may purge it."
        ),
    )
    email_at_invitation_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc=(
            "HMAC-SHA-256 hex digest of the email at accept time. Used by "
            "FR-054 audit replay even after email is cleared."
        ),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Set atomically with status='revoked'.",
    )

    # Relationships
    project: Mapped[Project] = relationship("Project")
    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    invitation: Mapped[ProjectInvitation] = relationship(
        "ProjectInvitation",
        foreign_keys=[invitation_id],
    )
    granted_by: Mapped[User] = relationship("User", foreign_keys=[granted_by_id])

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(granted_permissions) = 'array' "
            "AND jsonb_array_length(granted_permissions) > 0",
            name="ck_trusted_users_permissions_non_empty_array",
        ),
        CheckConstraint(
            "expires_at > granted_at "
            "AND expires_at <= granted_at + INTERVAL '1 year'",
            name="ck_trusted_users_duration_within_one_year",
        ),
        Index(
            "ix_project_trusted_users_project_user_status",
            "project_id",
            "user_id",
            "status",
        ),
        Index(
            "ix_project_trusted_users_status_expires",
            "status",
            "expires_at",
        ),
        # FR-041 / FR-044 — at most one *active* overlay per (project, user)
        # pair. Mirrors the partial unique index in the baseline Alembic
        # migration; without it concurrent accept_invitation/update_trusted_user
        # calls could create two ACTIVE rows that the permission engine would
        # union, escalating capability beyond the issuing Owner's intent.
        Index(
            "ux_project_trusted_users_active",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    def __repr__(self) -> str:
        """String representation of ProjectTrustedUser."""
        return (
            "<ProjectTrustedUser("
            f"id={self.id}, project_id={self.project_id}, "
            f"user_id={self.user_id}, status={self.status}"
            ")>"
        )


__all__ = ["ProjectTrustedUser"]
