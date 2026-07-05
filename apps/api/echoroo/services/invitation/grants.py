"""Permission-allowlist filter, membership guards, and role ranking.

* :func:`coerce_granted_permissions` — FR-012 / FR-014 / FR-042
  allowlist intersection for Trusted overlays.
* :func:`_reject_if_active_member` — issue-time existing-member guard
  (preview issue #4).
* :func:`_load_existing_grant` — replay lookup for the downstream grant.
* :func:`_role_rank` — FR-011-106 step 3 role ordering.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import (
    TRUSTED_ALLOWED_PERMISSIONS,
    Permission,
)
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectMemberRole,
)
from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.models.user import User

from .errors import InvitationActiveMemberError, InvitationValidationError


def coerce_granted_permissions(
    raw: Iterable[str | Permission],
) -> frozenset[Permission]:
    """Validate + intersect ``granted_permissions`` against the Trusted allowlist.

    Raises :class:`InvitationValidationError` when any entry is not a known
    Permission name OR is outside ``TRUSTED_ALLOWED_PERMISSIONS``. We **do
    not** silently filter at issue-time — the operator must learn that a
    requested capability is unsupported (FR-012 expectation: the UI / API
    surface only Trusted-eligible rows). The runtime safety net in
    :mod:`echoroo.core.permissions` filters anyway, but the error here
    keeps the row aligned with the UI contract.
    """
    out: set[Permission] = set()
    for entry in raw:
        if isinstance(entry, Permission):
            perm = entry
        else:
            try:
                perm = Permission(entry)
            except ValueError as exc:
                raise InvitationValidationError(
                    f"unknown permission name: {entry!r}"
                ) from exc
        if perm not in TRUSTED_ALLOWED_PERMISSIONS:
            raise InvitationValidationError(
                f"permission {perm.value!r} is not in TRUSTED_ALLOWED_PERMISSIONS",
            )
        out.add(perm)
    if not out:
        raise InvitationValidationError("granted_permissions must be non-empty")
    return frozenset(out)


async def _reject_if_active_member(
    session: AsyncSession,
    *,
    project_id: UUID,
    email: str,
) -> None:
    """Raise :class:`InvitationActiveMemberError` when ``email`` is a member.

    Resolves the plain-text ``email`` to a registered :class:`User` (case-
    insensitive, mirroring :meth:`UserRepository.get_by_email`) and checks
    whether that user already holds an *active* (``removed_at IS NULL``)
    :class:`ProjectMember` row on ``project_id``. When such a row exists the
    function raises with the member's current role attached so the handler
    can surface it.

    No-op when the email does not map to any user — an unregistered recipient
    cannot already be a member, so issuance proceeds to the normal
    pending-duplicate guard. Raw emails are never logged here; the email
    arrives already-canonicalised at the boundary and is matched via a
    ``func.lower`` comparison, the same shape the user repository uses.
    """
    user_id = (
        await session.execute(
            select(User.id).where(
                func.lower(User.email) == func.lower(email),
            ),
        )
    ).scalar_one_or_none()
    if user_id is None:
        return

    existing_member = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.removed_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    if existing_member is None:
        return

    raise InvitationActiveMemberError(
        "User is already a member of this project "
        f"(role: {existing_member.role.value})",
        role=existing_member.role,
    )


# spec/011 FR-011-106 step 3 — role-rank helper. ProjectMemberRole is a
# StrEnum so direct enum comparison is unstable; the explicit table
# below documents the ordering once.
_ROLE_RANK: Final[dict[ProjectMemberRole, int]] = {
    ProjectMemberRole.VIEWER: 1,
    ProjectMemberRole.MEMBER: 2,
    ProjectMemberRole.ADMIN: 3,
}


def _role_rank(role: ProjectMemberRole) -> int:
    """Return the comparable integer rank for ``role`` (FR-011-106 step 3)."""
    return _ROLE_RANK.get(role, 0)


async def _load_existing_grant(
    session: AsyncSession,
    invitation: ProjectInvitation,
    current_user_id: UUID,
) -> tuple[ProjectMember | None, ProjectTrustedUser | None]:
    """Fetch the downstream grant row created by a prior accept."""
    member: ProjectMember | None = None
    trusted_user: ProjectTrustedUser | None = None
    if invitation.kind is ProjectInvitationKind.MEMBER:
        member_result = await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == invitation.project_id,
                ProjectMember.user_id == current_user_id,
                ProjectMember.removed_at.is_(None),
            ),
        )
        member = member_result.scalar_one_or_none()
    else:
        trusted_result = await session.execute(
            select(ProjectTrustedUser).where(
                ProjectTrustedUser.invitation_id == invitation.id,
                ProjectTrustedUser.user_id == current_user_id,
            ),
        )
        trusted_user = trusted_result.scalar_one_or_none()
    return member, trusted_user
