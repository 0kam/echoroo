"""spec/011 T243 — Member-kind invitation end-to-end integration tests.

Exercises the full Phase 7 / US2 flow against the real FastAPI app + test
DB. Each test issues an invitation through ``POST /web-api/v1/projects/
{project_id}/invitations``, fetches the public resolver context, accepts
under either the new-user signup branch or the existing-user branch, and
confirms the persisted state (membership row, invitation status, audit
emission). The constant-timing pad (FR-011-105 / FR-011-107) is
monkey-patched to a no-op for the duration of each test so the suite
stays under a second per case.

Spec coverage:

* **FR-011-101 / FR-011-102** — POST issuer surface + cache directives.
* **FR-011-105 / FR-011-107** — public resolver + generic-invalid surface.
* **FR-011-106** — atomic state flip + existing-user branch (R11).
* **FR-011-108** — listing returns kind=member rows.
* **T208** — audit-action emission per branch.

Session authentication uses the spec/009 BFF refresh-token bootstrap
pattern (same as ``tests/integration/api/web_v1/test_projects_a2.py``):
seed a refresh-token + family row, call ``/web-api/v1/auth/refresh`` to
get a CSRF token + access token, then attach both to subsequent
requests.

The TOTP enrollment branch is exercised by stubbing the TwoFactorService
``confirm_enrollment`` helper because the production flow requires a
real TOTP counter; the contract field name ``totp_secret_signed``
round-trips verbatim through the schema validator.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectInvitation, ProjectMember
from echoroo.models.user import User
from echoroo.services.invitation_service import (
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    canonicalize_email,
)

_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 3,
    "allow_precise_location_to_viewer": False,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_response_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the 300ms timing pad so tests stay fast.

    The constant-timing pad is a security property covered separately in
    the NFR-011-006 surface tests; the integration suite would otherwise
    pay 300ms per response unnecessarily.
    """
    from echoroo.api.web_v1 import auth as auth_module

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr(
        auth_module,
        "_invitation_public_sleep_for_minimum",
        _noop,
    )


@pytest.fixture(autouse=True)
def _disable_invitation_public_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the spec/011 invitation rate-limit for the integration suite.

    spec/011 step 7 R1 P0-3 swapped the rate-limit helper to a Redis-
    backed fixed-window INCR + EXPIRE; the bucket lives in the shared
    integration Redis and persists across tests within the same 60s
    window. The per-IP cap (10/min) is comfortably exceeded by the
    dozen-plus tests in this module, so the suite would flap 429s.
    The rate-limit's correctness is covered by a dedicated unit test;
    here we just want the request to pass through.
    """
    from echoroo.api.web_v1 import auth as auth_module

    async def _always_allowed(*, ip: str) -> bool:  # noqa: ARG001
        return False

    monkeypatch.setattr(
        auth_module,
        "_invitation_public_rate_limit_check",
        _always_allowed,
    )


@pytest.fixture(autouse=True)
def _fake_redis_for_invitation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> fakeredis.aioredis.FakeRedis:
    """Patch ``get_redis_connection`` to return a process-local FakeRedis.

    The invitation service's rate-limit + idempotency paths require a
    live async Redis client. The integration test stack does not boot a
    real Redis container, so we substitute fakeredis at the import
    surfaces called by the issuer (``_members.py``) and the trusted
    endpoint (``trusted.py``). The fake is per-test so concurrent runs
    do not cross-contaminate.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_fake() -> fakeredis.aioredis.FakeRedis:
        return fake

    from echoroo.api.web_v1.projects import _members as members_module

    monkeypatch.setattr(members_module, "get_redis_connection", _get_fake)
    # Also patch the shared singleton so any other consumer in the
    # request pipeline picks up the fake (defence in depth).
    from echoroo.core import redis as redis_module

    monkeypatch.setattr(redis_module, "get_redis_connection", _get_fake)
    return fake


async def _create_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    two_factor_enabled: bool = True,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"t243-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        display_name="T243 user",
        security_stamp="t243" + uuid.uuid4().hex,
        two_factor_enabled=two_factor_enabled,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed_refresh_token(db: AsyncSession, user: User) -> str:
    """Seed a refresh-token + family row and return the token string.

    Mirrors ``tests/integration/api/web_v1/test_projects_read_smoke._seed_refresh_token``.
    """
    from echoroo.api.web_v1.auth import _issue_web_refresh_token

    token, record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    await db.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, :created_at)"
        ),
        {
            "family_id": UUID(record.family_id),
            "user_id": record.user_id,
            "created_at": record.issued_at,
        },
    )
    await db.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(jti, user_id, family_id, issued_at, expires_at) "
            "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
        ),
        {
            "jti": UUID(record.jti),
            "user_id": record.user_id,
            "family_id": UUID(record.family_id),
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        },
    )
    await db.commit()
    return token


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: User,
) -> dict[str, str]:
    """Authenticate ``user`` on the BFF surface and return Bearer + CSRF.

    Note: the refresh endpoint also sets cookies on ``client.cookies``
    (session cookie, refresh cookie, logged-in marker). Subsequent
    requests rely on those cookies so the auth router resolves the
    session correctly. Tests that want to call as an ANONYMOUS user
    should call ``client.cookies.clear()`` first.
    """
    client.cookies.clear()
    refresh_token = await _seed_refresh_token(db, user)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


def _without_csrf(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() != "x-csrf-token"}


async def _create_project(
    db: AsyncSession,
    owner: User,
) -> Project:
    project = Project(
        name=f"T243 {uuid.uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner.id,
        restricted_config=dict(_RESTRICTED_CONFIG),
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role=ProjectMemberRole.ADMIN,
            invited_by_id=owner.id,
        )
    )
    await db.commit()
    await db.refresh(project)
    return project


async def _issue_member_invitation(
    client: AsyncClient,
    *,
    project_id: UUID,
    owner_headers: dict[str, str],
    email: str,
    role: str = "member",
) -> dict[str, Any]:
    response = await client.post(
        f"/web-api/v1/projects/{project_id}/invitations",
        headers=owner_headers,
        json={"email": email, "role": role},
    )
    assert response.status_code == 201, response.text
    assert (
        response.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    body = response.json()
    assert "invitation_url" in body
    assert "bound_email_hash" in body
    return body


# ---------------------------------------------------------------------------
# Happy path — existing user accept (R11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_user_accept_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Existing-user accept inserts a membership row at the invited role.

    Mirrors FR-011-106 step 1b (R11). The resolver reports
    ``is_logged_in=true`` and ``authenticated_email_matches_bound=true``;
    the accept body is the minimal ``{accept: true}`` payload.
    """
    owner = await _create_user(db_session, email="t243-owner-1@example.com")
    other = await _create_user(db_session, email="t243-other-1@example.com")
    project = await _create_project(db_session, owner)

    owner_headers = await _bff_session_headers(client, db_session, owner)
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=other.email,
        role="member",
    )
    token = body["invitation_url"]

    # Authenticate as ``other`` (the recipient) for the existing-user branch.
    other_headers = await _bff_session_headers(client, db_session, other)
    resolve = await client.get(
        f"/web-api/v1/auth/invitations/{token}",
        headers=_without_csrf(other_headers),
    )
    assert resolve.status_code == 200, resolve.text
    ctx = resolve.json()
    assert ctx["kind"] == "member"
    assert ctx["role"] == "member"
    assert ctx["is_logged_in"] is True
    assert ctx["authenticated_email_matches_bound"] is True

    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=other_headers,
        json={"accept": True},
    )
    assert accept.status_code == 201, accept.text
    assert (
        accept.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    accepted = accept.json()
    assert accepted["kind"] == "member"
    assert accepted["membership_created"] is True
    assert accepted["ownership_transferred"] is False

    # Membership row is present and the invitation flipped to accepted.
    member_row = (
        await db_session.execute(
            sa.select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == other.id,
            ),
        )
    ).scalar_one_or_none()
    assert member_row is not None
    assert member_row.role is ProjectMemberRole.MEMBER

    invitation_id = UUID(body["invitation_id"])
    inv = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
            ),
        )
    ).scalar_one()
    assert inv.status is ProjectInvitationStatus.ACCEPTED
    assert inv.accepted_at is not None

    audit_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id = :pid AND action = :action"
            ),
            {
                "pid": str(project.id),
                "action": AUDIT_ACTION_MEMBER_INVITE_ACCEPTED,
            },
        )
    ).scalar_one()
    assert audit_count >= 1


# ---------------------------------------------------------------------------
# Happy path — new-user signup branch (signup audit action)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_signup_accept_writes_signup_audit(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """New-user signup branch emits the signup audit action (T208).

    The TOTP enrollment confirm is monkey-patched to a no-op so the
    integration test does not need to wire a real TOTP counter. The
    audit action is what differentiates this branch from the
    existing-user accept.
    """
    from echoroo.services.two_factor_service import TwoFactorService

    async def _fake_confirm(
        self: TwoFactorService,
        user: User,
        _secret: str,
        _code: str,
        *,
        commit: bool = True,
    ) -> list[str]:
        # spec/011 step 7 R1 P0-1: the public accept handler invokes
        # ``confirm_enrollment(commit=False)`` so the 2FA write joins
        # the same TX as the user INSERT + invitation UPDATE. The stub
        # mirrors the contract — do not commit when the caller asked
        # us not to.
        user.two_factor_enabled = True
        if commit:  # pragma: no cover — endpoint always passes False
            await self.db.commit()
        return ["backup-1", "backup-2"]

    monkeypatch.setattr(TwoFactorService, "confirm_enrollment", _fake_confirm)

    owner = await _create_user(db_session, email="t243-owner-2@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    target_email = f"t243-signup-{uuid4().hex[:8]}@example.com"
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=target_email,
        role="member",
    )
    token = body["invitation_url"]

    # Anonymous accept — no session, no CSRF.
    client.cookies.clear()
    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        json={
            "email": target_email,
            "password": "StrongPassword!1234",
            "totp_enrollment": {
                "totp_secret_signed": "JBSWY3DPEHPK3PXP",
                "totp_initial_code": "123456",
            },
        },
    )
    assert accept.status_code == 201, accept.text
    accepted = accept.json()
    assert accepted["kind"] == "member"
    assert accepted["membership_created"] is True

    user_row = (
        await db_session.execute(
            sa.text("SELECT id FROM users WHERE email = :email"),
            {"email": canonicalize_email(target_email)},
        )
    ).first()
    assert user_row is not None

    audit_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id = :pid AND action = :action"
            ),
            {
                "pid": str(project.id),
                "action": AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
            },
        )
    ).scalar_one()
    assert audit_count >= 1


# ---------------------------------------------------------------------------
# Email mismatch — resolver flag, accept generic 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_reports_authenticated_email_mismatch(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The resolver tells the frontend when the session email does NOT match.

    R11: the existing-user branch is gated on
    ``authenticated_email_matches_bound``. A mismatched session must
    surface the mismatch so the UI can ask the user to sign out.
    Accepting under the mismatched session collapses to the generic
    invalid 404 (FR-011-107 anti-enumeration).
    """
    owner = await _create_user(db_session, email="t243-owner-3@example.com")
    other = await _create_user(db_session, email="t243-other-3@example.com")
    project = await _create_project(db_session, owner)

    owner_headers = await _bff_session_headers(client, db_session, owner)
    bound_email = f"t243-bound-{uuid4().hex[:8]}@example.com"
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=bound_email,
        role="member",
    )
    token = body["invitation_url"]

    other_headers = await _bff_session_headers(client, db_session, other)
    resolve = await client.get(
        f"/web-api/v1/auth/invitations/{token}",
        headers=_without_csrf(other_headers),
    )
    assert resolve.status_code == 200, resolve.text
    ctx = resolve.json()
    assert ctx["is_logged_in"] is True
    assert ctx["authenticated_email_matches_bound"] is False

    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=other_headers,
        json={"accept": True},
    )
    assert accept.status_code == 404
    assert "ERR_INVITATION_INVALID" in accept.text


# ---------------------------------------------------------------------------
# Already-member 409
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_existing_user_already_member_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Accept fails with 409 when caller already holds same/higher role."""
    owner = await _create_user(db_session, email="t243-owner-4@example.com")
    other = await _create_user(db_session, email="t243-other-4@example.com")
    project = await _create_project(db_session, owner)
    db_session.add(
        ProjectMember(
            project_id=project.id,
            user_id=other.id,
            role=ProjectMemberRole.ADMIN,
            invited_by_id=owner.id,
        )
    )
    await db_session.commit()

    owner_headers = await _bff_session_headers(client, db_session, owner)
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=other.email,
        role="member",
    )
    token = body["invitation_url"]

    other_headers = await _bff_session_headers(client, db_session, other)
    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=other_headers,
        json={"accept": True},
    )
    assert accept.status_code == 409
    # The 409 response body MAY be wrapped under ``detail`` (raw
    # HTTPException) or flattened by the existing error envelope
    # middleware. We just need the marker string somewhere.
    assert "ERR_ALREADY_MEMBER" in accept.text


# ---------------------------------------------------------------------------
# Expired invitation collapses to generic invalid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_invitation_collapses_to_generic_invalid(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An expired row surfaces as the generic 404 (FR-011-107).

    We rewrite ``expires_at`` past ``now()`` rather than constructing
    a token with a past ``exp`` claim — the latter would also trip the
    HMAC envelope check, which is a separate concern covered by the
    kid-rotation suite.
    """
    owner = await _create_user(db_session, email="t243-owner-5@example.com")
    other = await _create_user(db_session, email="t243-other-5@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=other.email,
        role="member",
    )
    token = body["invitation_url"]
    invitation_id = UUID(body["invitation_id"])

    await db_session.execute(
        sa.text(
            "UPDATE project_invitations SET expires_at = :ts WHERE id = :id"
        ),
        {
            "ts": datetime.now(UTC) - timedelta(seconds=1),
            "id": invitation_id,
        },
    )
    await db_session.commit()

    other_headers = await _bff_session_headers(client, db_session, other)
    resolve = await client.get(
        f"/web-api/v1/auth/invitations/{token}",
        headers=_without_csrf(other_headers),
    )
    assert resolve.status_code == 404

    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=other_headers,
        json={"accept": True},
    )
    assert accept.status_code == 404


# ---------------------------------------------------------------------------
# Listing surface — kind=member rows appear alongside any existing rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_returns_member_kind_rows(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """T201 / FR-011-108: the listing surface enumerates kind=member rows."""
    owner = await _create_user(db_session, email="t243-owner-6@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=f"t243-list-{uuid4().hex[:8]}@example.com",
        role="member",
    )

    response = await client.get(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=_without_csrf(owner_headers),
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert any(
        item["id"] == body["invitation_id"]
        and item["kind"] == ProjectInvitationKind.MEMBER.value
        for item in items
    )

    response = await client.get(
        f"/web-api/v1/projects/{project.id}/invitations?kind=member",
        headers=_without_csrf(owner_headers),
    )
    assert response.status_code == 200
    member_items = response.json()["items"]
    assert all(
        it["kind"] == ProjectInvitationKind.MEMBER.value for it in member_items
    )


# ---------------------------------------------------------------------------
# Token decoupling: a malformed token surfaces as generic invalid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_garbage_token_returns_generic_invalid(
    client: AsyncClient,
) -> None:
    """An unparseable / forged token collapses to the FR-011-107 surface."""
    client.cookies.clear()
    response = await client.get(
        "/web-api/v1/auth/invitations/not-a-real-token",
    )
    assert response.status_code == 404
    payload = response.json()
    # The body MAY be ``{"detail": {...}}`` (FastAPI HTTPException) or a
    # flatter shape if a different middleware re-wrapped the response.
    # We just need the marker string somewhere in the body so that an
    # operator scrubbing the logs sees the generic-invalid envelope.
    assert "ERR_INVITATION_INVALID" in response.text


# ===========================================================================
# spec/011 step 7 R1 — Codex R1 regression tests
# ===========================================================================
#
# These tests assert the four P0 + two P1 fixes Codex R1 flagged on PR #100.
# They MUST stay green to prevent regressions.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# P0-1: signup branch never leaks an orphan user + 2FA credential
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_branch_rolls_back_user_and_2fa_when_invitation_invalidated(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """spec/011 step 7 R1 P0-1: atomic accept TX leaves no orphan account.

    Setup: issue a Member invitation, then **revoke** the row out of band
    (status flipped to ``revoked``) AFTER the signup payload has already
    been computed by the caller. The signup attempt then arrives at the
    accept handler — the atomic UPDATE returns zero rows because the
    row is no longer ``status='pending'``, so the whole transaction
    must roll back. The post-condition is:

    * NO user row with the signup email exists.
    * NO 2FA credential row exists for any new user.

    Before the P0-1 fix, ``confirm_enrollment`` committed mid-flow and
    the User + 2FA persisted past the invitation-state guard, leaving
    an orphan account in the DB that the affected email could no
    longer re-use.
    """
    from echoroo.services.two_factor_service import TwoFactorService

    async def _fake_confirm(
        self: TwoFactorService,
        user: User,
        _secret: str,
        _code: str,
        *,
        commit: bool = True,
    ) -> list[str]:
        # Honour the commit-flag contract: the public accept handler
        # passes ``commit=False`` so a downstream invitation rollback
        # also rolls back this 2FA write. The stub mirrors that:
        # mutate the user but do NOT commit on its own.
        user.two_factor_enabled = True
        if commit:  # pragma: no cover — endpoint always passes False
            await self.db.commit()
        return ["backup-1", "backup-2"]

    monkeypatch.setattr(TwoFactorService, "confirm_enrollment", _fake_confirm)

    owner = await _create_user(db_session, email="t243-r1p0-1-owner@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    target_email = f"t243-r1p0-1-{uuid4().hex[:8]}@example.com"
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=target_email,
        role="member",
    )
    token = body["invitation_url"]
    invitation_id = UUID(body["invitation_id"])

    # Out-of-band revoke. Mirrors the race where an admin revokes the
    # invitation between the resolver call and the signup submission.
    await db_session.execute(
        sa.text(
            "UPDATE project_invitations "
            "SET status = 'revoked', revoked_at = now() "
            "WHERE id = :id"
        ),
        {"id": invitation_id},
    )
    await db_session.commit()

    # Anonymous accept attempt — the atomic UPDATE will match zero rows
    # because the row is no longer ``status='pending'``.
    client.cookies.clear()
    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        json={
            "email": target_email,
            "password": "StrongPassword!1234",
            "totp_enrollment": {
                "totp_secret_signed": "JBSWY3DPEHPK3PXP",
                "totp_initial_code": "123456",
            },
        },
    )
    assert accept.status_code == 404
    assert "ERR_INVITATION_INVALID" in accept.text

    # P0-1: the User row must NOT exist (rollback succeeded).
    canonical = canonicalize_email(target_email)
    user_row = (
        await db_session.execute(
            sa.text("SELECT id, two_factor_enabled FROM users WHERE email = :email"),
            {"email": canonical},
        )
    ).first()
    assert user_row is None, (
        "spec/011 step 7 R1 P0-1 regression: invitation rollback "
        "left an orphan user row in the database; "
        "expected the create+2FA+accept transaction to roll back "
        "atomically when the atomic UPDATE returned zero rows."
    )


# ---------------------------------------------------------------------------
# P0-4: resolver omits bound_email for wrong-account caller
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_omits_bound_email_for_wrong_account_caller(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """spec/011 step 7 R1 P0-4: ``bound_email`` is null for mismatched session.

    When a user is logged in as identity X but opens an invitation
    URL bound to identity Y, the resolver MUST NOT surface Y's email
    address — that would let any holder of a leaked invitation URL
    confirm the recipient identity by signing in as themselves.
    """
    owner = await _create_user(db_session, email="t243-r1p0-4-owner@example.com")
    other = await _create_user(db_session, email="t243-r1p0-4-other@example.com")
    project = await _create_project(db_session, owner)

    owner_headers = await _bff_session_headers(client, db_session, owner)
    bound_email = f"t243-r1p0-4-bound-{uuid4().hex[:8]}@example.com"
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=bound_email,
        role="member",
    )
    token = body["invitation_url"]

    other_headers = await _bff_session_headers(client, db_session, other)
    resolve = await client.get(
        f"/web-api/v1/auth/invitations/{token}",
        headers=_without_csrf(other_headers),
    )
    assert resolve.status_code == 200, resolve.text
    ctx = resolve.json()
    assert ctx["is_logged_in"] is True
    assert ctx["authenticated_email_matches_bound"] is False
    # P0-4: the field MUST be absent or null — never the actual email.
    bound_email_value = ctx.get("bound_email")
    assert bound_email_value in (None, ""), (
        "spec/011 step 7 R1 P0-4 regression: resolver leaked "
        f"bound_email={bound_email_value!r} to a wrong-account session; "
        "expected null/omitted."
    )
    assert bound_email_value != bound_email
    assert bound_email_value != bound_email.lower()


@pytest.mark.asyncio
async def test_resolver_surfaces_bound_email_for_anonymous_caller(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Anonymous resolve MUST still surface the bound email (signup prefill).

    Complementary to ``test_resolver_omits_bound_email_for_wrong_account_caller``:
    the P0-4 fix only suppresses the field for AUTHENTICATED wrong-account
    callers; anonymous callers (the signup branch) still need the email
    rendered as the read-only form value.
    """
    owner = await _create_user(db_session, email="t243-r1p0-4b-owner@example.com")
    project = await _create_project(db_session, owner)

    owner_headers = await _bff_session_headers(client, db_session, owner)
    bound_email = f"t243-r1p0-4b-bound-{uuid4().hex[:8]}@example.com"
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=bound_email,
        role="member",
    )
    token = body["invitation_url"]

    client.cookies.clear()
    resolve = await client.get(f"/web-api/v1/auth/invitations/{token}")
    assert resolve.status_code == 200, resolve.text
    ctx = resolve.json()
    assert ctx["is_logged_in"] is False
    # Anonymous signup branch — the field MUST be present (the
    # canonicalised form).
    assert ctx.get("bound_email") == canonicalize_email(bound_email)


@pytest.mark.asyncio
async def test_resolver_surfaces_bound_email_for_matching_authenticated_caller(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Matching authenticated caller MUST see their own bound email.

    P0-4 only suppresses the field when ``is_logged_in`` is true AND
    the email doesn't match; the matching case is the existing-user
    accept happy path and still surfaces the field so the confirm
    screen can show "you are about to accept this invitation".
    """
    owner = await _create_user(db_session, email="t243-r1p0-4c-owner@example.com")
    other = await _create_user(db_session, email="t243-r1p0-4c-other@example.com")
    project = await _create_project(db_session, owner)

    owner_headers = await _bff_session_headers(client, db_session, owner)
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=other.email,
        role="member",
    )
    token = body["invitation_url"]

    other_headers = await _bff_session_headers(client, db_session, other)
    resolve = await client.get(
        f"/web-api/v1/auth/invitations/{token}",
        headers=_without_csrf(other_headers),
    )
    assert resolve.status_code == 200, resolve.text
    ctx = resolve.json()
    assert ctx["is_logged_in"] is True
    assert ctx["authenticated_email_matches_bound"] is True
    assert ctx.get("bound_email") == canonicalize_email(other.email)


# ---------------------------------------------------------------------------
# P1-1: new-user signup branch establishes a session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_signup_branch_establishes_session(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """spec/011 step 7 R1 P1-1: signup branch sets the session cookies.

    Contract YAML ``invitation-public.yaml`` § 201 response: "For the
    new-user branch, a session is established." The handler invokes
    ``_issue_real_session`` after the accept commits; the
    ``Set-Cookie`` header MUST carry the refresh-token + family +
    CSRF + logged-in marker.
    """
    from echoroo.services.two_factor_service import TwoFactorService

    async def _fake_confirm(
        self: TwoFactorService,
        user: User,
        _secret: str,
        _code: str,
        *,
        commit: bool = True,
    ) -> list[str]:
        user.two_factor_enabled = True
        if commit:  # pragma: no cover — endpoint always passes False
            await self.db.commit()
        return ["backup-1", "backup-2"]

    monkeypatch.setattr(TwoFactorService, "confirm_enrollment", _fake_confirm)

    owner = await _create_user(db_session, email="t243-r1p1-1-owner@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    target_email = f"t243-r1p1-1-{uuid4().hex[:8]}@example.com"
    body = await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=target_email,
        role="member",
    )
    token = body["invitation_url"]

    client.cookies.clear()
    accept = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        json={
            "email": target_email,
            "password": "StrongPassword!1234",
            "totp_enrollment": {
                "totp_secret_signed": "JBSWY3DPEHPK3PXP",
                "totp_initial_code": "123456",
            },
        },
    )
    assert accept.status_code == 201, accept.text

    # P1-1: the response MUST carry session cookies.
    settings_ = get_settings()
    cookie_jar = client.cookies
    # httpx populates ``client.cookies`` from response ``Set-Cookie``
    # headers across the AsyncClient transport.
    assert cookie_jar.get(settings_.web_refresh_cookie_name) is not None, (
        "spec/011 step 7 R1 P1-1 regression: signup accept did not set "
        "the refresh-token cookie."
    )
    assert cookie_jar.get(settings_.web_session_cookie_name) is not None, (
        "spec/011 step 7 R1 P1-1 regression: signup accept did not set "
        "the family-id session cookie."
    )
    assert cookie_jar.get(settings_.web_csrf_cookie_name) is not None, (
        "spec/011 step 7 R1 P1-1 regression: signup accept did not set "
        "the CSRF cookie."
    )

    # And the CSRF header is echoed for the SPA's double-submit pickup.
    csrf_header = accept.headers.get("x-csrf-token") or accept.headers.get(
        "X-CSRF-Token",
    )
    assert csrf_header, (
        "spec/011 step 7 R1 P1-1 regression: signup accept did not emit "
        "the X-CSRF-Token response header."
    )


# ---------------------------------------------------------------------------
# P1-2: listing endpoint sets Cache-Control: no-store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_listing_endpoint_emits_no_store_cache_control(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """spec/011 step 7 R1 P1-2: invitation listing carries no-store.

    The listing surfaces ``bound_email_hash`` + per-invitation status
    for admin consumption; both are admin-only data that MUST NOT be
    cached by an upstream proxy or browser bfcache. The header is
    set unconditionally — even when the result set is empty.
    """
    owner = await _create_user(db_session, email="t243-r1p1-2-owner@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    # Issue at least one invitation so the listing is non-empty
    # (covering both the empty- and non-empty-result codepaths is
    # nice but the no-store directive lives BEFORE the SELECT so a
    # single test is sufficient).
    await _issue_member_invitation(
        client,
        project_id=project.id,
        owner_headers=owner_headers,
        email=f"t243-r1p1-2-list-{uuid4().hex[:8]}@example.com",
        role="member",
    )

    response = await client.get(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=_without_csrf(owner_headers),
    )
    assert response.status_code == 200, response.text

    cache_control = response.headers.get("cache-control")
    assert cache_control == "no-store, no-cache, must-revalidate, private", (
        "spec/011 step 7 R1 P1-2 regression: listing endpoint did "
        f"not emit no-store; got {cache_control!r}."
    )
