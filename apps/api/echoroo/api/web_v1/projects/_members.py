"""Project membership endpoints (T037 / T043 / T044).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``GET    /{project_id}/members``              — list members.
* ``PATCH  /{project_id}/members/{user_id}``    — update member role.
* ``DELETE /{project_id}/members/{user_id}``    — remove member.

The invitation surface (issue / bulk / revoke / list / accept / decline)
lives in the sibling :mod:`echoroo.api.web_v1.projects._invitations`
module. Adding a user to a project is invitation-only — direct member-add
was removed 2026-06-03 (preview feedback #7).

The router still has **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select

from echoroo.api.web_v1.projects._audit import write_project_bff_audit_soft
from echoroo.api.web_v1.projects._core import ProjectServiceDep
from echoroo.core.actions import (
    PROJECT_MEMBER_LIST_ACTION,
    PROJECT_MEMBER_REMOVE_ACTION,
    PROJECT_MEMBER_UPDATE_ROLE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.project import ProjectMember
from echoroo.schemas.project import (
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _enum_value(value: object) -> object:
    """Return a JSON-safe enum value while preserving None and plain objects."""
    if isinstance(value, Enum):
        return cast(object, value.value)
    return value


def _member_audit_snapshot(
    member: ProjectMember | ProjectMemberResponse,
    *,
    project_id: UUID,
) -> dict[str, Any]:
    role = getattr(member, "role", None)
    user_id = getattr(member, "user_id", None)
    if user_id is None:
        user_id = member.user.id
    return {
        "id": str(member.id),
        "project_id": str(project_id),
        "user_id": str(user_id),
        "role": _enum_value(role),
        "joined_at": _json_datetime(member.joined_at),
        "expires_at": _json_datetime(member.expires_at),
        "removed_at": _json_datetime(member.removed_at),
    }


async def _load_member_for_audit(
    db: DbSession,
    *,
    project_id: UUID,
    user_id: UUID,
) -> ProjectMember | None:
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# T037 / T043 / T044 — /{project_id}/members
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    summary="List project members (Web UI)",
    description=(
        "Cookie-session Web UI surface mirroring the programmatic member "
        "list route. Owner / Admin only via the canonical MANAGE_MEMBERS gate."
    ),
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> list[ProjectMemberResponse]:
    """List members through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.list_members(current_user.id, project_id)


# NOTE (2026-06-03, preview feedback #7): the direct member-add route
# (``POST /{project_id}/members``) has been removed. Adding a user to a
# project is invitation-only — issue a Member-kind invitation via
# ``POST /{project_id}/invitations`` (see
# :mod:`echoroo.api.web_v1.projects._invitations`) and let the recipient
# accept it. The members LIST / role-change / remove endpoints below
# remain intact.


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
    summary="Update member role (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "role update route. Owner / Admin only via MANAGE_MEMBERS."
    ),
)
async def update_project_member_role(
    project_id: UUID,
    user_id: UUID,
    payload: ProjectMemberUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Update a member role through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_UPDATE_ROLE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    before_member = await _load_member_for_audit(
        db,
        project_id=project_id,
        user_id=user_id,
    )
    before = (
        _member_audit_snapshot(before_member, project_id=project_id)
        if before_member is not None
        else None
    )
    member = await service.update_member_role(
        current_user.id,
        project_id,
        user_id,
        payload,
    )
    await db.commit()
    await write_project_bff_audit_soft(
        actor_user_id=current_user.id,
        project_id=project_id,
        action=PROJECT_MEMBER_UPDATE_ROLE_ACTION.name,
        request=request,
        detail={
            "project_id": str(project_id),
            "user_id": str(user_id),
            "old_role": before["role"] if before is not None else None,
            "new_role": member.role.value,
        },
        before=before,
        after=_member_audit_snapshot(member, project_id=project_id),
    )
    return member


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove project member (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "remove route. Owner / Admin only via MANAGE_MEMBERS."
    ),
)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Remove a member through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_REMOVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    before_member = await _load_member_for_audit(
        db,
        project_id=project_id,
        user_id=user_id,
    )
    before = (
        _member_audit_snapshot(before_member, project_id=project_id)
        if before_member is not None
        else None
    )
    await service.remove_member(current_user.id, project_id, user_id)
    await db.commit()
    await write_project_bff_audit_soft(
        actor_user_id=current_user.id,
        project_id=project_id,
        action=PROJECT_MEMBER_REMOVE_ACTION.name,
        request=request,
        detail={
            "project_id": str(project_id),
            "user_id": str(user_id),
            "old_role": before["role"] if before is not None else None,
        },
        before=before,
        after=None,
    )


__all__ = ["router"]
