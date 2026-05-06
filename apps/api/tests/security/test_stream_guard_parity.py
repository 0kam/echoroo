"""Phase 17 backlog A-5 Round 2 R1-I1: ``gate_action`` / ``recheck_action_permission`` parity.

The Hybrid Contract requires that the HTTP-time gate
(:func:`echoroo.core.permissions.gate_action`) and the mid-stream
guard (:func:`echoroo.core.stream_guard.recheck_action_permission`)
agree on every allow/deny decision. Codex Round 1 NO-GO flagged that
the two paths previously duplicated their authorization algorithm and
could drift when a future Phase added another condition.

The fix (R1-I1) extracts the shared decision logic into the public
helper :func:`echoroo.core.permissions.decide_action_permission`. Both
``gate_action`` and ``recheck_action_permission`` delegate to it. This
test file is the load-bearing regression guard: for every principal
type the canonical permission matrix recognises, we assert that

  * ``gate_action`` raises :class:`HTTPException(403)` iff
  * ``recheck_action_permission`` raises
    :class:`PermissionRevokedMidStream`

— and that on success both helpers complete without raising. The
parametrize matrix covers Owner / Member / Viewer / Authenticated
non-member / Guest / Trusted overlay / API key (full + scoped) /
Superuser to detect drift if any new branch is added to the gate but
forgotten in the mid-stream path (or vice-versa).
"""
from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core import stream_guard
from echoroo.core.actions import DETECTION_EXPORT_CSV_ACTION
from echoroo.core.permissions import gate_action
from echoroo.models.api_key import ApiKey
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Seed helpers (mirrors test_stream_guard.py to keep this file self-contained)
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"sg_parity {email}",
        security_stamp="s" * 64,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_project(db: AsyncSession, *, owner: User) -> Project:
    project = Project(
        name="Parity Project",
        description="A-5 R1-I1 parity",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner.id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": True,
            "allow_export": True,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _add_member(
    db: AsyncSession, *, project: Project, user: User, role: ProjectMemberRole
) -> ProjectMember:
    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=role,
        invited_by_id=project.owner_id,
    )
    db.add(member)
    await db.flush()
    return member


async def _seed_api_key(
    db: AsyncSession,
    *,
    user: User,
    project: Project | None,
    permissions: list[str] | None = None,
) -> ApiKey:
    raw_secret = secrets.token_urlsafe(32)
    prefix_random = secrets.token_urlsafe(6)[:8]
    prefix = f"echoroo_{prefix_random}"
    hashed = hashlib.sha256(raw_secret.encode()).hexdigest()
    key = ApiKey(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id if project is not None else None,
        prefix=prefix,
        hashed_secret=hashed,
        granted_permissions=permissions or ["view_project_metadata", "export", "view_media"],
        expires_at=datetime.now(UTC) + timedelta(days=365),
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return key


def _make_request() -> Any:
    return SimpleNamespace(
        state=SimpleNamespace(),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


# ---------------------------------------------------------------------------
# Per-call helpers: run both gates and return their allow/deny verdicts
# ---------------------------------------------------------------------------


async def _gate_allows(
    db: AsyncSession, *, current_user: Any, project_id: uuid.UUID
) -> bool:
    """Run ``gate_action`` — True if it returns, False on HTTPException(403)."""
    try:
        await gate_action(
            action=DETECTION_EXPORT_CSV_ACTION,
            project_id=project_id,
            current_user=current_user,
            request=_make_request(),
            db=db,
        )
    except HTTPException as exc:
        if exc.status_code == 403:
            return False
        raise
    return True


async def _recheck_allows(
    db: AsyncSession, *, current_user: Any, project_id: uuid.UUID
) -> bool:
    """Run ``recheck_action_permission`` — True on success, False on revoke."""
    try:
        await stream_guard.recheck_action_permission(
            db=db,
            action=DETECTION_EXPORT_CSV_ACTION,
            project_id=project_id,
            current_user=current_user,
            request=_make_request(),
        )
    except stream_guard.PermissionRevokedMidStream:
        return False
    return True


# ---------------------------------------------------------------------------
# Parity assertions per principal type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_owner(db_session: AsyncSession) -> None:
    """Project owner: both gates allow EXPORT."""
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    await db_session.commit()

    gate = await _gate_allows(db_session, current_user=owner, project_id=project.id)
    recheck = await _recheck_allows(db_session, current_user=owner, project_id=project.id)
    assert gate is True and recheck is True, (
        f"owner parity drift: gate={gate} recheck={recheck}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,expected_allowed",
    [
        (ProjectMemberRole.ADMIN, True),
        (ProjectMemberRole.MEMBER, True),
        (ProjectMemberRole.VIEWER, False),  # viewer cannot export by default
    ],
)
async def test_parity_member_roles(
    db_session: AsyncSession,
    role: ProjectMemberRole,
    expected_allowed: bool,
) -> None:
    """Admin / Member / Viewer roles must match between gate and recheck."""
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    member_user = await _make_user(
        db_session, email=f"sg_parity_member_{uuid.uuid4().hex[:6]}@e.com"
    )
    await _add_member(db_session, project=project, user=member_user, role=role)
    await db_session.commit()

    gate = await _gate_allows(db_session, current_user=member_user, project_id=project.id)
    recheck = await _recheck_allows(
        db_session, current_user=member_user, project_id=project.id
    )
    assert gate == recheck, f"role={role.value} drift: gate={gate} recheck={recheck}"
    # Sanity-check the matrix expectation for the parametrized role so a
    # silent regression in the canonical matrix would still be caught.
    assert gate == expected_allowed, (
        f"role={role.value} expected allow={expected_allowed} but got {gate}"
    )


@pytest.mark.asyncio
async def test_parity_authenticated_non_member(db_session: AsyncSession) -> None:
    """Authenticated non-member: both gates produce the SAME verdict.

    The project has ``allow_export=True`` in its ``restricted_config``,
    so the canonical matrix may permit EXPORT for an authenticated
    non-member depending on visibility. The load-bearing parity
    assertion is that ``gate_action`` and ``recheck_action_permission``
    BOTH agree (the absolute allow/deny depends on matrix policy and
    must not be hard-coded here).
    """
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    stranger = await _make_user(
        db_session, email=f"sg_parity_stranger_{uuid.uuid4().hex[:6]}@e.com"
    )
    await db_session.commit()

    gate = await _gate_allows(db_session, current_user=stranger, project_id=project.id)
    recheck = await _recheck_allows(
        db_session, current_user=stranger, project_id=project.id
    )
    assert gate == recheck, (
        f"authenticated non-member drift: gate={gate} recheck={recheck}"
    )


@pytest.mark.asyncio
async def test_parity_guest(db_session: AsyncSession) -> None:
    """Guest (current_user=None) + Restricted project: both gates deny EXPORT."""
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    await db_session.commit()

    gate = await _gate_allows(db_session, current_user=None, project_id=project.id)
    recheck = await _recheck_allows(db_session, current_user=None, project_id=project.id)
    assert gate is False and recheck is False, (
        f"guest drift: gate={gate} recheck={recheck}"
    )


@pytest.mark.asyncio
async def test_parity_api_key_full_scope(db_session: AsyncSession) -> None:
    """Owner + API key with EXPORT scope: both gates allow."""
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    key = await _seed_api_key(
        db_session,
        user=owner,
        project=project,
        permissions=["view_project_metadata", "export", "view_media"],
    )
    await db_session.commit()

    # Match the auth middleware's principal stamping.
    owner._api_key_id = key.id  # type: ignore[attr-defined]
    owner._api_key_project_id = project.id  # type: ignore[attr-defined]
    owner._api_key_scopes = tuple(key.granted_permissions)  # type: ignore[attr-defined]

    gate = await _gate_allows(db_session, current_user=owner, project_id=project.id)
    recheck = await _recheck_allows(db_session, current_user=owner, project_id=project.id)
    assert gate is True and recheck is True, (
        f"api-key full-scope drift: gate={gate} recheck={recheck}"
    )


@pytest.mark.asyncio
async def test_parity_api_key_scoped_without_export(db_session: AsyncSession) -> None:
    """Owner + API key WITHOUT EXPORT scope: both gates deny EXPORT.

    The user is the owner so without the API-key intersection EXPORT
    would pass; the parity check is whether the intersection logic
    matches between the two gates.
    """
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    key = await _seed_api_key(
        db_session,
        user=owner,
        project=project,
        permissions=["view_project_metadata"],  # NO export
    )
    await db_session.commit()

    owner._api_key_id = key.id  # type: ignore[attr-defined]
    owner._api_key_project_id = project.id  # type: ignore[attr-defined]
    owner._api_key_scopes = tuple(key.granted_permissions)  # type: ignore[attr-defined]

    gate = await _gate_allows(db_session, current_user=owner, project_id=project.id)
    recheck = await _recheck_allows(db_session, current_user=owner, project_id=project.id)
    assert gate is False and recheck is False, (
        f"api-key scoped-without-export drift: gate={gate} recheck={recheck}"
    )


@pytest.mark.asyncio
async def test_parity_api_key_project_binding_mismatch(db_session: AsyncSession) -> None:
    """API key bound to project A used against project B: both gates deny.

    This test exercises the binding check that runs BEFORE any DB
    access. Both gates must surface the same deny.
    """
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project_a = await _make_project(db_session, owner=owner)
    project_b = await _make_project(db_session, owner=owner)
    key = await _seed_api_key(
        db_session,
        user=owner,
        project=project_a,  # bound to A
    )
    await db_session.commit()

    owner._api_key_id = key.id  # type: ignore[attr-defined]
    owner._api_key_project_id = project_a.id  # type: ignore[attr-defined]
    owner._api_key_scopes = tuple(key.granted_permissions)  # type: ignore[attr-defined]

    gate = await _gate_allows(db_session, current_user=owner, project_id=project_b.id)
    recheck = await _recheck_allows(db_session, current_user=owner, project_id=project_b.id)
    assert gate is False and recheck is False, (
        f"api-key binding-mismatch drift: gate={gate} recheck={recheck}"
    )


@pytest.mark.asyncio
async def test_parity_trusted_overlay(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Authenticated non-member with active Trusted EXPORT overlay: both allow.

    The overlay is normally seeded via the trusted_service workflow
    (multi-step admin approval). For a parity check we monkeypatch
    :func:`get_active_trusted_capabilities` so both code paths read
    the same capability set — the load-bearing assertion is that
    ``gate_action`` and ``recheck_action_permission`` BOTH consult the
    overlay (or BOTH skip it). Drift here would manifest as gate
    allowing while recheck denies (or vice versa).
    """
    from echoroo.core.permissions import Permission
    from echoroo.services import trusted_service

    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    stranger = await _make_user(
        db_session, email=f"sg_parity_stranger_{uuid.uuid4().hex[:6]}@e.com"
    )
    await db_session.commit()

    async def _fake_overlay(
        _db: Any, *, user_id: Any, project_id: Any  # noqa: ARG001
    ) -> frozenset[Permission]:
        return frozenset({Permission.EXPORT})

    monkeypatch.setattr(
        trusted_service,
        "get_active_trusted_capabilities",
        _fake_overlay,
    )

    gate = await _gate_allows(db_session, current_user=stranger, project_id=project.id)
    recheck = await _recheck_allows(
        db_session, current_user=stranger, project_id=project.id
    )
    assert gate == recheck, f"trusted overlay drift: gate={gate} recheck={recheck}"
    # Both should ALLOW because the overlay grants EXPORT and the
    # action under test is DETECTION_EXPORT_CSV (which requires EXPORT).
    assert gate is True, (
        "trusted EXPORT overlay should unlock DETECTION_EXPORT_CSV for "
        "an authenticated non-member"
    )


@pytest.mark.asyncio
async def test_parity_superuser(db_session: AsyncSession) -> None:
    """Superuser: matrix matches between gate and recheck.

    Whether superuser actually allows DETECTION_EXPORT_CSV on a
    Restricted project depends on the canonical matrix; the load-
    bearing parity check is that BOTH gates return the same verdict.
    """
    # ``_is_superuser`` reads ``is_superuser`` straight off the principal
    # object — the auth middleware stamps it from the live ``superusers``
    # table at request time, so we mirror that behaviour by stamping the
    # attribute directly on the User row.
    su = await _make_user(
        db_session, email=f"sg_parity_su_{uuid.uuid4().hex[:6]}@e.com"
    )
    su.is_superuser = True  # type: ignore[attr-defined]
    owner = await _make_user(db_session, email=f"sg_parity_owner_{uuid.uuid4().hex[:6]}@e.com")
    project = await _make_project(db_session, owner=owner)
    await db_session.commit()

    gate = await _gate_allows(db_session, current_user=su, project_id=project.id)
    recheck = await _recheck_allows(db_session, current_user=su, project_id=project.id)
    assert gate == recheck, f"superuser parity drift: gate={gate} recheck={recheck}"
