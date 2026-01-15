"""Project model.

Represents research or monitoring initiatives that own datasets.
"""

from __future__ import annotations

import datetime
import secrets
import string
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
import sqlalchemy.orm as orm

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.site import Site
    from echoroo.models.annotation_project import AnnotationProject
    from echoroo.models.user import User

__all__ = ["Project", "ProjectMember", "ProjectMemberRole"]


def _generate_project_id() -> str:
    """Generate a stable, human-friendly project identifier."""
    alphabet = string.ascii_lowercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"prj-{suffix}"


class ProjectMemberRole(str, Enum):
    """Supported membership roles within a project."""

    MANAGER = "manager"
    MEMBER = "member"


class Project(Base):
    """Project lookup table."""

    __tablename__ = "project"

    project_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        default_factory=_generate_project_id,
        primary_key=True,
        kw_only=True,
    )
    """Natural identifier for the project (e.g. sparrow2025)."""

    project_name: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        nullable=False,
    )
    """Human-readable name of the project."""

    url: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Optional project homepage."""

    description: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text(),
        nullable=True,
        default=None,
    )
    """Short description of the project."""

    target_taxa: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Comma-separated list of target taxa."""

    admin_name: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Primary administrator name."""

    admin_email: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Primary administrator email."""

    is_active: orm.Mapped[bool] = orm.mapped_column(
        sa.Boolean(),
        nullable=False,
        default=True,
        server_default=sa.true(),
    )
    """Whether the project is currently active."""

    datasets: orm.Mapped[list["Dataset"]] = orm.relationship(
        "Dataset",
        back_populates="project",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Datasets registered under this project."""

    sites: orm.Mapped[list["Site"]] = orm.relationship(
        "Site",
        back_populates="project",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Sites managed under this project."""

    annotation_projects: orm.Mapped[list["AnnotationProject"]] = (
        orm.relationship(
            "AnnotationProject",
            back_populates="project",
            default_factory=list,
            repr=False,
            init=False,
        )
    )
    """Annotation projects associated with this project."""

    memberships: orm.Mapped[list["ProjectMember"]] = orm.relationship(
        "ProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Membership assignments for the project."""

    members: orm.Mapped[list["User"]] = orm.relationship(
        "User",
        secondary="project_member",
        viewonly=True,
        default_factory=list,
        repr=False,
        init=False,
    )
    """Users belonging to this project."""


class ProjectMember(Base):
    """Association table between projects and users."""

    __tablename__ = "project_member"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """Surrogate primary key to ease auditing."""

    project_id: orm.Mapped[str] = orm.mapped_column(
        sa.ForeignKey("project.project_id", ondelete="CASCADE"),
        nullable=False,
    )
    """Identifier of the project."""

    user_id: orm.Mapped[UUID] = orm.mapped_column(
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
    )
    """Identifier of the user."""

    role: orm.Mapped[ProjectMemberRole] = orm.mapped_column(
        sa.Enum(
            ProjectMemberRole,
            name="project_member_role",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ProjectMemberRole.MEMBER,
        server_default=ProjectMemberRole.MEMBER.value,
    )
    """Role granted to the member."""

    created_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        default=datetime.datetime.utcnow,
        init=False,
    )
    """Timestamp when the membership was created."""

    project: orm.Mapped[Project] = orm.relationship(
        "Project",
        back_populates="memberships",
        repr=False,
        init=False,
    )
    """Relationship back to the project."""

    user: orm.Mapped["User"] = orm.relationship(
        "User",
        back_populates="project_memberships",
        repr=False,
        init=False,
    )
    """Relationship back to the user."""
