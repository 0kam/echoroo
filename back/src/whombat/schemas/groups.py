"""Schemas related to user groups and memberships."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from whombat.models.group import GroupRole
from whombat.schemas.base import BaseSchema
from whombat.schemas.users import SimpleUser

__all__ = [
    "Group",
    "GroupCreate",
    "GroupDetail",
    "GroupMembership",
    "GroupMembershipCreate",
    "GroupMembershipUpdate",
    "GroupRole",
    "GroupUpdate",
]


class Group(BaseSchema):
    """Group representation returned to clients."""

    id: int
    name: str
    description: Optional[str] = None
    created_by_id: UUID | None = Field(default=None, repr=False)


class GroupDetail(Group):
    """Group enriched with membership information."""

    memberships: list[GroupMembership] = Field(default_factory=list)


class GroupCreate(BaseModel):
    """Payload required to create a new group."""

    name: str
    description: Optional[str] = None


class GroupUpdate(BaseModel):
    """Fields that can be updated for a group."""

    name: Optional[str] = None
    description: Optional[str] = None


class GroupMembership(BaseSchema):
    """Group membership details, including the user information."""

    group_id: int
    user_id: UUID
    role: GroupRole
    user: SimpleUser | None = None


class GroupMembershipCreate(BaseModel):
    """Payload to add a user to a group."""

    user_id: UUID
    role: GroupRole = GroupRole.MEMBER


class GroupMembershipUpdate(BaseModel):
    """Payload to update an existing membership."""

    role: GroupRole
