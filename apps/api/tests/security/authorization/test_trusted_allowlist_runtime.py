"""FR-014 Trusted allowlist runtime safety net (T532).

The Trusted overlay's ``granted_permissions`` JSONB column accepts any
string, so a malicious operator (or a bug in a future migration) could
INSERT a row that names a permission outside
:data:`TRUSTED_ALLOWED_PERMISSIONS` (e.g. ``view_audit_log``).
:func:`echoroo.services.trusted_service.get_active_trusted_capabilities`
and the static helper
:func:`echoroo.core.permissions.active_trusted_capabilities` MUST
intersect with the allowlist on every read so the gate never grants the
out-of-band permission.

This module pins:

1. **Happy path** — an overlay whose ``granted_permissions`` is a strict
   subset of the allowlist returns the same set when read back.
2. **Manual-INSERT escalation attempt** — a row containing
   ``view_audit_log`` (NOT in the allowlist) is read by
   ``get_active_trusted_capabilities`` and the ineligible permission is
   filtered out.
3. **Mixed in/out of allowlist** — an overlay that mixes legal and
   illegal permissions returns only the legal subset.
4. **API-route allowlist gate** —
   :func:`echoroo.services.invitation_service.coerce_granted_permissions`
   refuses to issue a Trusted invitation that names ``view_audit_log``,
   surfacing :class:`InvitationValidationError` so the endpoint can map
   to ``ERR_INVALID_TRUSTED_PERMISSION`` (422).

The third bullet is the load-bearing assertion: even if a row escapes
the issue-time gate, the **runtime** read filter is the last line of
defence (FR-014 ``runtime safety net``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import (
    TRUSTED_ALLOWED_PERMISSIONS,
    Permission,
    active_trusted_capabilities,
)
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectTrustedStatus,
)
from echoroo.models.project import ProjectInvitation
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.services.invitation_service import (
    InvitationValidationError,
    coerce_granted_permissions,
)
from echoroo.services.trusted_service import get_active_trusted_capabilities

# ---------------------------------------------------------------------------
# Sanity check — VIEW_AUDIT_LOG is intentionally OUTSIDE the allowlist.
# ---------------------------------------------------------------------------


def test_view_audit_log_is_not_in_trusted_allowlist() -> None:
    """Spec-level guarantee: ``VIEW_AUDIT_LOG`` is Admin-only (FR-012)."""
    assert Permission.VIEW_AUDIT_LOG not in TRUSTED_ALLOWED_PERMISSIONS


# ---------------------------------------------------------------------------
# Fixture: insert a stand-in user + parent invitation row so the FKs hold.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def t532_owner_id(db_session: AsyncSession) -> Any:
    from echoroo.models.user import User

    user = User(
        email=f"t532-owner-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T532 Owner",
        security_stamp="t532" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


async def _purge(db: AsyncSession) -> None:
    await db.execute(sa.text("DELETE FROM project_trusted_users"))
    await db.execute(sa.text("DELETE FROM project_invitations"))
    await db.commit()


async def _seed_project(db: AsyncSession, owner_id: Any) -> Any:
    """Insert a minimal Project row (parent FK for invitation/overlay)."""
    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project

    project = Project(
        name=f"T532 {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner_id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project.id


async def _seed_target_user(db: AsyncSession) -> Any:
    """Insert the user receiving the Trusted overlay (FK target)."""
    from echoroo.models.user import User

    user = User(
        email=f"t532-target-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T532 Target",
        security_stamp="t532" + "t" * 60,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


async def _seed_overlay(
    db: AsyncSession,
    *,
    granted_permissions: list[str],
    project_id: Any,
    user_id: Any,
    invited_by_id: Any,
) -> ProjectTrustedUser:
    """Insert a parent invitation + a ProjectTrustedUser row with the given perms.

    We insert the row directly so the test can exercise the runtime
    safety net regardless of whether the issue-time validator would
    have accepted the array.
    """
    expires_at = datetime.now(UTC) + timedelta(days=30)
    invitation = ProjectInvitation(
        project_id=project_id,
        kind=ProjectInvitationKind.TRUSTED,
        email="t532-target@example.com",
        email_hash="0" * 64,
        granted_permissions=granted_permissions,
        trusted_duration_seconds=30 * 24 * 3600,
        token_hash=("a" * 32 + uuid4().hex)[:64],
        invited_by_id=invited_by_id,
        expires_at=expires_at,
        status=ProjectInvitationStatus.ACCEPTED,
        accepted_at=datetime.now(UTC),
    )
    db.add(invitation)
    await db.flush()

    overlay = ProjectTrustedUser(
        project_id=project_id,
        user_id=user_id,
        invitation_id=invitation.id,
        granted_by_id=invited_by_id,
        granted_at=datetime.now(UTC),
        expires_at=expires_at,
        status=ProjectTrustedStatus.ACTIVE,
        granted_permissions=granted_permissions,
        email_at_invitation="t532-target@example.com",
        email_at_invitation_hash="0" * 64,
    )
    db.add(overlay)
    await db.commit()
    await db.refresh(overlay)
    return overlay


# ---------------------------------------------------------------------------
# 1. Happy path — overlay perms within allowlist round-trip cleanly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_overlay_within_allowlist_returns_full_set(
    db_session: AsyncSession,
    t532_owner_id: Any,
) -> None:
    """A row whose perms are all inside the allowlist comes back intact."""
    await _purge(db_session)
    project_id = await _seed_project(db_session, t532_owner_id)
    user_id = await _seed_target_user(db_session)
    granted = ["view_media", "vote", "comment"]
    await _seed_overlay(
        db_session,
        granted_permissions=granted,
        project_id=project_id,
        user_id=user_id,
        invited_by_id=t532_owner_id,
    )

    perms = await get_active_trusted_capabilities(
        db_session,
        user_id=user_id,
        project_id=project_id,
    )
    assert perms == frozenset(
        {Permission.VIEW_MEDIA, Permission.VOTE, Permission.COMMENT}
    )


# ---------------------------------------------------------------------------
# 2. Manual INSERT that names VIEW_AUDIT_LOG — runtime filter drops it.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_insert_view_audit_log_is_filtered_at_read(
    db_session: AsyncSession,
    t532_owner_id: Any,
) -> None:
    """A row with ``view_audit_log`` MUST resolve to an empty/limited set."""
    await _purge(db_session)
    project_id = await _seed_project(db_session, t532_owner_id)
    user_id = await _seed_target_user(db_session)
    # ONLY view_audit_log → resolved set must be empty.
    await _seed_overlay(
        db_session,
        granted_permissions=["view_audit_log"],
        project_id=project_id,
        user_id=user_id,
        invited_by_id=t532_owner_id,
    )

    perms = await get_active_trusted_capabilities(
        db_session,
        user_id=user_id,
        project_id=project_id,
    )
    assert Permission.VIEW_AUDIT_LOG not in perms
    assert perms == frozenset(), (
        f"Out-of-allowlist permission must be filtered, got {perms!r}"
    )


# ---------------------------------------------------------------------------
# 3. Mixed allowlist members + non-member → only allowed members survive.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mixed_allowlist_in_and_out_keeps_only_allowed(
    db_session: AsyncSession,
    t532_owner_id: Any,
) -> None:
    """Smuggling ``view_audit_log`` next to legitimate perms must not work."""
    await _purge(db_session)
    project_id = await _seed_project(db_session, t532_owner_id)
    user_id = await _seed_target_user(db_session)
    await _seed_overlay(
        db_session,
        granted_permissions=[
            "view_media",        # in allowlist
            "view_audit_log",    # NOT in allowlist
            "vote",              # in allowlist
            "delete_project",    # NOT in allowlist (Owner-only)
        ],
        project_id=project_id,
        user_id=user_id,
        invited_by_id=t532_owner_id,
    )

    perms = await get_active_trusted_capabilities(
        db_session,
        user_id=user_id,
        project_id=project_id,
    )
    assert perms == frozenset({Permission.VIEW_MEDIA, Permission.VOTE})
    assert Permission.VIEW_AUDIT_LOG not in perms
    assert Permission.DELETE_PROJECT not in perms


# ---------------------------------------------------------------------------
# 4. The static helper used by the gate engine performs the same filter.
# ---------------------------------------------------------------------------


def test_active_trusted_capabilities_static_helper_filters_out_of_allowlist() -> None:
    """The pure-Python helper backs the request-scope ``is_allowed`` path."""

    class _Row:
        def __init__(self, perms: list[str]) -> None:
            self.status = ProjectTrustedStatus.ACTIVE
            self.expires_at = datetime.now(UTC) + timedelta(days=1)
            self.granted_permissions = perms

    perms = active_trusted_capabilities(
        [_Row(["view_media", "view_audit_log", "delete_project"])],
        now_utc=datetime.now(UTC),
    )
    assert perms == frozenset({Permission.VIEW_MEDIA})


# ---------------------------------------------------------------------------
# 5. Issue-time gate — coerce_granted_permissions raises 422 for VIEW_AUDIT_LOG.
# ---------------------------------------------------------------------------


def test_coerce_granted_permissions_rejects_view_audit_log() -> None:
    """The invite POST path filter rejects VIEW_AUDIT_LOG up-front (FR-012)."""
    with pytest.raises(InvitationValidationError) as ei:
        coerce_granted_permissions(["view_media", "view_audit_log"])
    assert "view_audit_log" in str(ei.value).lower()


def test_coerce_granted_permissions_accepts_full_allowlist() -> None:
    """Every TRUSTED_ALLOWED_PERMISSIONS entry must be acceptable at issue time."""
    accepted = coerce_granted_permissions(
        [p.value for p in TRUSTED_ALLOWED_PERMISSIONS]
    )
    assert accepted == TRUSTED_ALLOWED_PERMISSIONS


# ---------------------------------------------------------------------------
# 6. Unknown permission strings (typos / future names) raise too.
# ---------------------------------------------------------------------------


def test_coerce_granted_permissions_rejects_unknown_permission_name() -> None:
    with pytest.raises(InvitationValidationError):
        coerce_granted_permissions(["completely_made_up_permission"])


__all__ = [
    "test_active_trusted_capabilities_static_helper_filters_out_of_allowlist",
    "test_coerce_granted_permissions_accepts_full_allowlist",
    "test_coerce_granted_permissions_rejects_unknown_permission_name",
    "test_coerce_granted_permissions_rejects_view_audit_log",
    "test_manual_insert_view_audit_log_is_filtered_at_read",
    "test_mixed_allowlist_in_and_out_keeps_only_allowed",
    "test_overlay_within_allowlist_returns_full_set",
    "test_view_audit_log_is_not_in_trusted_allowlist",
]
