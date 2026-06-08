"""ToriTore participation-gate helpers (preview).

Shared between the annotation-set eligibility endpoint and the annotation
create flow. The gate exempts project Owners and Admins (they run the
study); everyone else must clear the set's ``min_total_score`` with their
latest ToriTore total score.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectMemberRole
from echoroo.models.project import Project, ProjectMember
from echoroo.services import toritore as toritore_service


async def is_project_owner_or_admin(
    db: AsyncSession, *, project_id: UUID, user_id: UUID
) -> bool:
    """Return True iff ``user_id`` owns or is an Admin of ``project_id``.

    Owner is derived from ``projects.owner_id``; Admin from the user's
    ``ProjectMember.role``. Used to exempt study runners from the ToriTore
    participation gate.
    """
    owner_id = (
        await db.execute(
            select(Project.owner_id).where(Project.id == project_id)
        )
    ).scalar_one_or_none()
    if owner_id is not None and owner_id == user_id:
        return True

    role = (
        await db.execute(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    return role == ProjectMemberRole.ADMIN


async def enforce_participation_gate(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    min_total_score: float | None,
) -> None:
    """Raise 403 ``toritore_score_insufficient`` when the gate blocks the user.

    No-op when there is no requirement (``min_total_score is None``) or when
    the user is exempt (project Owner/Admin). Otherwise the user's latest
    ToriTore ``total_score`` must exist and be ``>= min_total_score``.
    """
    if min_total_score is None:
        return
    if await is_project_owner_or_admin(
        db, project_id=project_id, user_id=user_id
    ):
        return

    current = await toritore_service.get_latest_total_score(db, user_id)
    if current is None or current < min_total_score:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "toritore_score_insufficient",
                "required": min_total_score,
                "current": current,
            },
        )


__all__ = ["enforce_participation_gate", "is_project_owner_or_admin"]
