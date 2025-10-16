"""Group models.

These models provide a minimal grouping system with membership roles that can
be used to organise users and delegate administrative privileges.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
import sqlalchemy.orm as orm

from whombat.models.base import Base

__all__ = ["Group", "GroupMembership", "GroupRole"]


class GroupRole(str, Enum):
    """Supported membership roles within a group."""

    MEMBER = "member"
    MANAGER = "manager"


class Group(Base):
    """Represents a collaborative group of users."""

    __tablename__ = "group"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """Primary key."""

    name: orm.Mapped[str] = orm.mapped_column(unique=True)
    """Display name of the group."""

    description: orm.Mapped[Optional[str]] = orm.mapped_column(default=None)
    """Optional textual description."""

    created_by_id: orm.Mapped[UUID | None] = orm.mapped_column(
        sa.ForeignKey("user.id", ondelete="SET NULL"),
        default=None,
    )
    """The user that created the group, if known."""

    created_by: orm.Mapped[Optional["User"]] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        repr=False,
        init=False,
    )
    """Relationship to the user that created the group."""

    memberships: orm.Mapped[list["GroupMembership"]] = orm.relationship(
        "GroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Membership relationships."""

    members: orm.Mapped[list["User"]] = orm.relationship(
        "User",
        secondary="group_membership",
        viewonly=True,
        default_factory=list,
        repr=False,
        init=False,
    )
    """Convenience relationship to quickly load group members."""


class GroupMembership(Base):
    """Association table between users and groups with a role attribute."""

    __tablename__ = "group_membership"

    group_id: orm.Mapped[int] = orm.mapped_column(
        sa.ForeignKey("group.id", ondelete="CASCADE"),
        primary_key=True,
    )
    """Identifier of the related group."""

    user_id: orm.Mapped[UUID] = orm.mapped_column(
        sa.ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    """Identifier of the related user."""

    role: orm.Mapped[GroupRole] = orm.mapped_column(
        sa.Enum(GroupRole, name="group_role"),
        default=GroupRole.MEMBER,
        server_default=GroupRole.MEMBER.value,
    )
    """The role of the user within the group."""

    group: orm.Mapped[Group] = orm.relationship(
        "Group",
        back_populates="memberships",
        repr=False,
        init=False,
    )
    """Relationship to the group."""

    user: orm.Mapped["User"] = orm.relationship(
        "User",
        back_populates="group_memberships",
        repr=False,
        init=False,
    )
    """Relationship to the user."""
