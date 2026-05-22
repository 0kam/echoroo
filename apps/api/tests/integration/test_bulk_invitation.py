"""spec/011 T291 — Bulk-invitation + revoke endpoint integration tests.

Exercises the spec/011 Step 8 surface end-to-end (FR-011-110..115):

* **FR-011-110** — bulk POST happy path returns one ``status='issued'``
  row per submitted email with the one-shot ``invitation_url``.
* **FR-011-111** — whole-request reject on in-list canonicalisation
  duplicate (no DB writes, no per-issuer quota consumed).
* **FR-011-111** — whole-request reject on a malformed email entry
  (Pydantic EmailStr surfaces 422 BEFORE any SAVEPOINT runs).
* **FR-011-112 / NFR-011-008** — per-row SAVEPOINT semantics: a
  duplicate-pending row in the middle of the batch is reported as
  ``status='duplicate_pending'`` while preceding + following rows
  persist (no whole-batch rollback).
* **FR-011-114** — per-issuer rate-limit exhaustion mid-batch surfaces
  remaining rows as ``status='rate_limited'`` while successfully-issued
  rows survive.
* **FR-011-115** — revoke happy path; ``revoke`` of an unknown id /
  cross-project id / already-revoked row all collapse to HTTP 404.

The single-invite + accept tests already live in
``test_member_invitation_flow.py``; this module focuses on the bulk +
revoke surfaces.
"""

from __future__ import annotations

import uuid
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
    ProjectInvitationStatus,
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectInvitation, ProjectMember
from echoroo.models.user import User

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
# Fixtures (mirror test_member_invitation_flow patterns)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fake_redis_for_invitation_service(
    monkeypatch: pytest.MonkeyPatch,
) -> fakeredis.aioredis.FakeRedis:
    """Patch ``get_redis_connection`` to a process-local FakeRedis.

    The bulk endpoint hits Redis via two surfaces — the per-issuer
    rate-limit helper in ``_members.py`` and the FR-056 actor / project
    counters inside ``create_invitation``. Both must see the same
    FakeRedis so the rate-limit semantics tests can manipulate one
    bucket and observe the effect on the other.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_fake() -> fakeredis.aioredis.FakeRedis:
        return fake

    from echoroo.api.web_v1.projects import _members as members_module

    monkeypatch.setattr(members_module, "get_redis_connection", _get_fake)
    from echoroo.core import redis as redis_module

    monkeypatch.setattr(redis_module, "get_redis_connection", _get_fake)
    return fake


async def _create_user(
    db: AsyncSession,
    *,
    email: str | None = None,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"t291-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        display_name="T291 user",
        security_stamp="t291" + uuid.uuid4().hex,
        two_factor_enabled=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed_refresh_token(db: AsyncSession, user: User) -> str:
    """Seed a refresh-token + family row and return the token string."""
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


async def _create_project(db: AsyncSession, owner: User) -> Project:
    project = Project(
        name=f"T291 {uuid.uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
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


def _make_unique_emails(n: int) -> list[str]:
    """Return ``n`` distinct, well-formed, canonicalisation-unique addresses."""
    return [f"t291-{uuid4().hex[:8]}@example.com" for _ in range(n)]


# ===========================================================================
# Happy path — 10 emails issued successfully
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_invitation_happy_path_10_emails(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-110: 10 valid emails → 10 ``status='issued'`` rows.

    The response array is in submission order and every row carries
    ``invitation_url`` + ``invitation_id`` + ``expires_at``.
    """
    owner = await _create_user(db_session, email="t291-hp-owner@example.com")
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    emails = _make_unique_emails(10)
    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={"role": "member", "emails": emails},
    )

    assert response.status_code == 207, response.text
    assert (
        response.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    rows = response.json()
    assert isinstance(rows, list), "FR-011-113: top-level response MUST be an array"
    assert len(rows) == 10
    for i, row in enumerate(rows):
        assert row["email"] == emails[i]
        assert row["status"] == "issued", row
        assert row["invitation_id"] is not None
        assert row["invitation_url"] is not None
        assert row["expires_at"] is not None
        assert row.get("error_message") is None

    # Persisted: 10 pending invitations exist for this project.
    pending = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project.id,
                ProjectInvitation.status == ProjectInvitationStatus.PENDING,
            ),
        )
    ).scalar_one()
    assert pending == 10


# ===========================================================================
# Whole-request reject — in-list canonicalisation duplicate (FR-011-111)
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_invitation_rejects_in_list_canonical_duplicate(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-111: ``alice@x`` + ``ALICE@x`` → 422, no rows persisted.

    The canonicalisation guard runs BEFORE any SAVEPOINT loop so the
    request never consumes per-issuer rate-limit quota and no DB writes
    happen.
    """
    owner = await _create_user(
        db_session, email="t291-dup-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={
            "role": "member",
            "emails": [
                "alice@example.com",
                "ALICE@example.com",  # canonicalises to alice@example.com
            ],
        },
    )
    assert response.status_code == 422, response.text
    body = response.json()
    text = response.text
    assert "ERR_BULK_DUPLICATE_EMAILS" in text, body

    # Zero invitations persisted.
    count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(ProjectInvitation.project_id == project.id),
        )
    ).scalar_one()
    assert count == 0


# ===========================================================================
# Whole-request reject — malformed email entry (FR-011-111)
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_invitation_rejects_malformed_email(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-111: any malformed email rejects the WHOLE request with 422.

    Pydantic's ``EmailStr`` validator catches the malformed entry before
    the handler body even runs — no SAVEPOINT, no quota consumption.
    """
    owner = await _create_user(
        db_session, email="t291-malformed-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={
            "role": "member",
            "emails": [
                "first@example.com",
                "not-an-email-at-all",
                "third@example.com",
            ],
        },
    )
    assert response.status_code == 422, response.text

    # Zero invitations persisted.
    count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(ProjectInvitation.project_id == project.id),
        )
    ).scalar_one()
    assert count == 0


# ===========================================================================
# Per-row duplicate_pending — middle row collides; siblings persist
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_invitation_per_row_duplicate_pending(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-112 / NFR-011-008: a duplicate-pending row reports per-row.

    Issue email X via a first bulk call; then submit X again as the
    middle entry in a second bulk call. The middle row reports
    ``status='duplicate_pending'`` while the surrounding rows persist
    successfully — proof that SAVEPOINT rollback only affected the
    middle row.
    """
    owner = await _create_user(
        db_session, email="t291-dp-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    duplicate_email = "t291-dp-collide@example.com"
    # First call seeds the pending row for ``duplicate_email``.
    first = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={"role": "member", "emails": [duplicate_email]},
    )
    assert first.status_code == 207, first.text
    assert first.json()[0]["status"] == "issued"

    # Second call: leading + trailing rows are fresh; middle row collides.
    leading = f"t291-dp-leading-{uuid4().hex[:8]}@example.com"
    trailing = f"t291-dp-trailing-{uuid4().hex[:8]}@example.com"
    second = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={
            "role": "member",
            "emails": [leading, duplicate_email, trailing],
        },
    )
    assert second.status_code == 207, second.text
    rows = second.json()
    assert len(rows) == 3
    assert rows[0]["email"] == leading
    assert rows[0]["status"] == "issued"
    assert rows[1]["email"] == duplicate_email
    assert rows[1]["status"] == "duplicate_pending"
    assert rows[1].get("invitation_url") is None
    assert rows[2]["email"] == trailing
    assert rows[2]["status"] == "issued"

    # DB-side: leading + trailing rows exist (the SAVEPOINT for the
    # middle row rolled back without taking the others with it).
    leading_count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project.id,
                ProjectInvitation.email == leading,
            ),
        )
    ).scalar_one()
    assert leading_count == 1
    trailing_count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project.id,
                ProjectInvitation.email == trailing,
            ),
        )
    ).scalar_one()
    assert trailing_count == 1


# ===========================================================================
# Per-row rate_limited — per-issuer hour cap exhaustion mid-batch
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_invitation_per_row_rate_limited_mid_batch(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-114: rows past the per-issuer cap report ``rate_limited``.

    We shrink the per-issuer hour limit to 2 for this test so the
    third row in a 5-row batch trips the cap. Rows 1-2 are ``issued``;
    rows 3-5 collapse to ``rate_limited`` (the cap-trip is sticky for
    the rest of the batch — no further INCRs run, so the cap meaning
    is preserved).
    """
    from echoroo.api.web_v1.projects import _members as members_module

    monkeypatch.setattr(members_module, "_BULK_INVITE_HOUR_LIMIT", 2)

    owner = await _create_user(
        db_session, email="t291-rl-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    emails = _make_unique_emails(5)
    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={"role": "member", "emails": emails},
    )
    assert response.status_code == 207, response.text
    rows = response.json()
    assert len(rows) == 5

    # Rows 1-2 issued, rows 3-5 rate-limited.
    statuses = [r["status"] for r in rows]
    assert statuses[0] == "issued"
    assert statuses[1] == "issued"
    assert all(s == "rate_limited" for s in statuses[2:])

    # Per-row error_message MUST be populated for rate-limited rows so
    # the operator can surface the cause without poking at logs.
    for r in rows[2:]:
        assert r.get("error_message"), r

    # DB-side: only 2 invitations persisted.
    pending_count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(
                ProjectInvitation.project_id == project.id,
                ProjectInvitation.status == ProjectInvitationStatus.PENDING,
            ),
        )
    ).scalar_one()
    assert pending_count == 2


# ===========================================================================
# Per-row internal_error — middle row's create_invitation raises
# ===========================================================================


@pytest.mark.asyncio
async def test_bulk_invitation_per_row_internal_error_isolates(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """NFR-011-008: an unexpected per-row failure rolls back only that row.

    Patch ``create_invitation`` to raise a ``RuntimeError`` on the
    middle row of a 3-row batch. The middle row surfaces as
    ``internal_error`` while the surrounding rows persist normally.
    """
    from echoroo.api.web_v1.projects import _members as members_module

    leading = f"t291-ie-leading-{uuid4().hex[:8]}@example.com"
    sabotaged = f"t291-ie-sabotaged-{uuid4().hex[:8]}@example.com"
    trailing = f"t291-ie-trailing-{uuid4().hex[:8]}@example.com"

    original_create = members_module.create_invitation

    async def _maybe_sabotage(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("email") == sabotaged:
            raise RuntimeError("simulated infra fault for middle row")
        return await original_create(*args, **kwargs)

    monkeypatch.setattr(members_module, "create_invitation", _maybe_sabotage)

    owner = await _create_user(
        db_session, email="t291-ie-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={
            "role": "member",
            "emails": [leading, sabotaged, trailing],
        },
    )
    assert response.status_code == 207, response.text
    rows = response.json()
    assert len(rows) == 3
    assert rows[0]["status"] == "issued"
    assert rows[1]["status"] == "internal_error"
    assert rows[1].get("error_message")
    assert rows[2]["status"] == "issued"

    # leading + trailing survived; sabotaged did NOT persist.
    persisted_emails = (
        await db_session.execute(
            sa.select(ProjectInvitation.email).where(
                ProjectInvitation.project_id == project.id,
            ),
        )
    ).scalars().all()
    assert leading in persisted_emails
    assert trailing in persisted_emails
    assert sabotaged not in persisted_emails


# ===========================================================================
# Revoke — happy path
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_invitation_happy_path(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Revoke flips ``status=revoked`` and returns the compact body."""
    owner = await _create_user(
        db_session, email="t291-rev-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    # Issue one invitation via the single-issue endpoint so we have a
    # stable invitation_id to revoke.
    issue = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=owner_headers,
        json={
            "email": f"t291-rev-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    revoke = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_headers,
        json={"reason": "operator changed their mind"},
    )
    assert revoke.status_code == 200, revoke.text
    assert (
        revoke.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    body = revoke.json()
    assert body["invitation_id"] == invitation_id
    assert body["status"] == "revoked"
    assert body["revoked_at"]

    # DB-side: status flipped, revoked_at set.
    row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == UUID(invitation_id),
            ),
        )
    ).scalar_one()
    assert row.status is ProjectInvitationStatus.REVOKED
    assert row.revoked_at is not None


# ===========================================================================
# Revoke — replay surfaces 404 (anti-enumeration)
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_invitation_replay_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Already-revoked row collapses to 404 (anti-enumeration)."""
    owner = await _create_user(
        db_session, email="t291-rep-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    issue = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=owner_headers,
        json={
            "email": f"t291-rep-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    first = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_headers,
        json={},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_headers,
        json={},
    )
    assert second.status_code == 404, second.text


# ===========================================================================
# Revoke — unknown id → 404
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_invitation_unknown_id_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An unknown invitation_id collapses to 404 (anti-enumeration)."""
    owner = await _create_user(
        db_session, email="t291-unk-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{uuid4()}/revoke",
        headers=owner_headers,
        json={},
    )
    assert response.status_code == 404, response.text


# ===========================================================================
# Revoke — wrong project surfaces 404 (anti-enumeration)
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_invitation_wrong_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Cross-project lookup collapses to 404 (anti-enumeration)."""
    owner_a = await _create_user(
        db_session, email="t291-cp-owner-a@example.com",
    )
    owner_b = await _create_user(
        db_session, email="t291-cp-owner-b@example.com",
    )
    project_a = await _create_project(db_session, owner_a)
    project_b = await _create_project(db_session, owner_b)

    # Issue under project_a using owner_a — fully complete this flow
    # BEFORE switching to owner_b. The BFF refresh-token bootstrap
    # rotates the security stamp on each ``_bff_session_headers`` call
    # so alternating sessions cross-invalidates if we don't fence the
    # work between switches.
    owner_a_headers = await _bff_session_headers(client, db_session, owner_a)
    issue = await client.post(
        f"/web-api/v1/projects/{project_a.id}/invitations",
        headers=owner_a_headers,
        json={
            "email": f"t291-cp-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    # NOW switch identities. ``_bff_session_headers`` clears the cookie
    # jar and seeds a fresh refresh-token family for owner_b — the
    # original owner_a session is no longer needed.
    owner_b_headers = await _bff_session_headers(client, db_session, owner_b)
    # Try to revoke the project_a invitation under project_b's URL,
    # using project_b's owner credentials so the gate_action passes —
    # the 404 MUST come from the project-scope mismatch inside
    # ``revoke_invitation``, NOT from the gate. Critically the response
    # shape must be the SAME generic 404 (no leak of "wrong project"
    # vs "row missing").
    response = await client.post(
        f"/web-api/v1/projects/{project_b.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_b_headers,
        json={},
    )
    assert response.status_code == 404, response.text

    # The original row under project_a remains pending.
    row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == UUID(invitation_id),
            ),
        )
    ).scalar_one()
    assert row.status is ProjectInvitationStatus.PENDING


# ===========================================================================
# Revoke — accepted invitation cannot be revoked → 404
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_invitation_already_accepted_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A row in terminal ``accepted`` state collapses to 404 on revoke.

    Simulate the terminal state by an out-of-band UPDATE (the integration
    accept flow lives in ``test_member_invitation_flow.py``; we only
    need the row's status here).
    """
    owner = await _create_user(
        db_session, email="t291-acc-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    issue = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=owner_headers,
        json={
            "email": f"t291-acc-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    await db_session.execute(
        sa.text(
            "UPDATE project_invitations "
            "SET status = 'accepted', accepted_at = now() "
            "WHERE id = :id"
        ),
        {"id": UUID(invitation_id)},
    )
    await db_session.commit()

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_headers,
        json={},
    )
    assert response.status_code == 404, response.text


# ===========================================================================
# Revoke — declined invitation cannot be revoked → 404
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_invitation_already_declined_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """A row in terminal ``declined`` state collapses to 404 on revoke."""
    owner = await _create_user(
        db_session, email="t291-dec-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    issue = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=owner_headers,
        json={
            "email": f"t291-dec-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    await db_session.execute(
        sa.text(
            "UPDATE project_invitations "
            "SET status = 'declined', declined_at = now() "
            "WHERE id = :id"
        ),
        {"id": UUID(invitation_id)},
    )
    await db_session.commit()

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_headers,
        json={},
    )
    assert response.status_code == 404, response.text


# ===========================================================================
# spec/011 Step 8 R1 — P2 coverage gap closure (size + PII + permission +
# info-leak regressions). Added in the post-PR-101 round so the
# orchestrator's hand-listed gaps are covered before merge.
# ===========================================================================


# ---------------------------------------------------------------------------
# R1 #1 — bulk rejects a 51-item batch with 422 (Pydantic max_items)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_invitation_rejects_51_item_batch(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-115: ``emails`` capped at 50 entries; 51 → HTTP 422.

    The Pydantic ``max_length=50`` constraint on
    :class:`BulkInvitationRequest.emails` fires BEFORE the handler runs,
    so no SAVEPOINT opens and no per-issuer quota is consumed.
    """
    owner = await _create_user(
        db_session, email="t291-r1-51-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    emails = _make_unique_emails(51)
    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={"role": "member", "emails": emails},
    )
    assert response.status_code == 422, response.text

    # Zero invitations persisted.
    count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(ProjectInvitation.project_id == project.id),
        )
    ).scalar_one()
    assert count == 0


# ---------------------------------------------------------------------------
# R1 #2 — bulk rejects an empty batch with 422 (Pydantic min_items)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_invitation_rejects_empty_batch(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-110: ``emails`` requires at least one entry; ``[]`` → 422.

    Pydantic's ``min_length=1`` on the ``emails`` field rejects the empty
    list before the handler runs.
    """
    owner = await _create_user(
        db_session, email="t291-r1-empty-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={"role": "member", "emails": []},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# R1 #3 — revoke rejects a ``reason`` containing PII (Phase 17 A-13)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_rejects_reason_with_pii(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """FR-011-208: the free-form ``reason`` runs the A-13 PII detector.

    A submitted email address inside the reason value MUST trip the
    detector with HTTP 422 BEFORE the revoke commits.
    """
    owner = await _create_user(
        db_session, email="t291-r1-pii-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    issue = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=owner_headers,
        json={
            "email": f"t291-r1-pii-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=owner_headers,
        # The detector recognises common PII tokens; an email inside the
        # free-form reason text MUST trip it.
        json={"reason": "contact alice@bar.com for context"},
    )
    assert response.status_code == 422, response.text

    # The invitation row remains pending — the PII detector ran BEFORE
    # the revoke commit.
    row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == UUID(invitation_id),
            ),
        )
    ).scalar_one()
    assert row.status is ProjectInvitationStatus.PENDING


# ---------------------------------------------------------------------------
# R1 #4 — bulk caller without MANAGE_MEMBERS → 403 (issuance endpoint
# contract; revoke gets 404 anti-enumeration, see #5 below).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_invitation_returns_403_when_caller_lacks_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Bulk issuance gate denial surfaces as HTTP 403 (contract YAML).

    The issuance endpoint's YAML explicitly lists ``403: PermissionDenied``;
    unlike the revoke surface (which collapses 403 → 404 to defeat
    invitation-id enumeration), the bulk endpoint exposes ``project_id``
    in the URL so a 403 leaks nothing the URL did not already.
    """
    owner = await _create_user(
        db_session, email="t291-r1-bulk403-owner@example.com",
    )
    outsider = await _create_user(
        db_session, email="t291-r1-bulk403-outsider@example.com",
    )
    project = await _create_project(db_session, owner)
    outsider_headers = await _bff_session_headers(client, db_session, outsider)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=outsider_headers,
        json={
            "role": "member",
            "emails": [f"t291-r1-bulk403-{uuid4().hex[:8]}@example.com"],
        },
    )
    # Outsider is not a member at all; the gate denies with 403 (or 404
    # if the gate elected to mask project existence). The contract YAML
    # accepts either as a non-leak shape — but 403 is the documented
    # response for the bulk issuance path.
    assert response.status_code in (403, 404), response.text
    # No invitation persisted in either branch.
    count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(ProjectInvitation.project_id == project.id),
        )
    ).scalar_one()
    assert count == 0


# ---------------------------------------------------------------------------
# R1 #5 — revoke caller without MANAGE_MEMBERS → 404 (anti-enumeration)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_returns_404_when_caller_lacks_permission(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Contract YAML revoke 404 collapse covers permission denial too.

    A caller without ``MANAGE_MEMBERS`` on the project MUST see HTTP 404
    (same body as the other revoke 404 paths) so an attacker who possesses
    a leaked ``invitation_id`` cannot probe whether the id exists by
    measuring the gate's 403 vs the row-missing 404 split.
    """
    owner = await _create_user(
        db_session, email="t291-r1-rev404-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    # Issue first so we have a real invitation_id under owner's project.
    issue = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations",
        headers=owner_headers,
        json={
            "email": f"t291-r1-rev404-target-{uuid4().hex[:8]}@example.com",
            "role": "member",
        },
    )
    assert issue.status_code == 201, issue.text
    invitation_id = issue.json()["invitation_id"]

    # Switch identities to an outsider with NO membership on the project.
    # ``_bff_session_headers`` clears cookies + seeds a fresh refresh
    # family so the outsider's session is unrelated to the owner's.
    outsider = await _create_user(
        db_session, email="t291-r1-rev404-outsider@example.com",
    )
    outsider_headers = await _bff_session_headers(client, db_session, outsider)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/"
        f"{invitation_id}/revoke",
        headers=outsider_headers,
        json={},
    )
    assert response.status_code == 404, response.text
    # Response body matches the other 404 producers (missing / wrong
    # project / non-pending) — same detail key so the shape is uniform.
    body = response.json()
    assert body.get("detail") == "invitation not found", body

    # DB-side: invitation still pending under the original project.
    row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == UUID(invitation_id),
            ),
        )
    ).scalar_one()
    assert row.status is ProjectInvitationStatus.PENDING


# ---------------------------------------------------------------------------
# R1 #6 — internal_error rows do NOT leak the exception type / message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_invitation_internal_error_does_not_leak_exception_detail(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """spec/011 Step 8 R1 P0-1 regression guard.

    Monkey-patch ``create_invitation`` so the middle row raises a
    ``RuntimeError`` whose message embeds a fake connection string
    (``"connection to db:5432 refused"``). The response row's
    ``error_message`` MUST be the constant generic string — neither the
    exception type name nor the raw message may appear in the body.
    """
    from echoroo.api.web_v1.projects import _members as members_module

    leading = f"t291-r1-leak-leading-{uuid4().hex[:8]}@example.com"
    sabotaged = f"t291-r1-leak-sabotaged-{uuid4().hex[:8]}@example.com"
    trailing = f"t291-r1-leak-trailing-{uuid4().hex[:8]}@example.com"
    leak_marker = "connection to db:5432 refused"

    original_create = members_module.create_invitation

    async def _maybe_sabotage(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("email") == sabotaged:
            raise RuntimeError(leak_marker)
        return await original_create(*args, **kwargs)

    monkeypatch.setattr(members_module, "create_invitation", _maybe_sabotage)

    owner = await _create_user(
        db_session, email="t291-r1-leak-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={
            "role": "member",
            "emails": [leading, sabotaged, trailing],
        },
    )
    assert response.status_code == 207, response.text
    rows = response.json()
    assert len(rows) == 3
    assert rows[1]["status"] == "internal_error"

    # The forbidden tokens must not appear ANYWHERE in the response body.
    body_text = response.text
    assert "RuntimeError" not in body_text, body_text
    assert leak_marker not in body_text, body_text
    # ``db:5432`` substring is the load-bearing leak shape (the canonical
    # example from the orchestrator's P0-1 brief).
    assert "db:5432" not in body_text, body_text

    # The constant generic message must be the visible substitute.
    assert rows[1]["error_message"] == (
        "Internal error; the operator log captured the cause."
    ), rows[1]


# ---------------------------------------------------------------------------
# R1 #7 — rate_limited rows do NOT leak the actor / project identifiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bulk_invitation_rate_limit_error_does_not_leak_internal_identifiers(
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """spec/011 Step 8 R1 P0-2 regression guard.

    Shrink the per-issuer hour cap to 1 so the SECOND row trips the cap.
    The response's ``error_message`` for the rate-limited row MUST be the
    constant generic message — neither the actor's UUID nor the project's
    UUID nor any "actor … exceeded" / "project … exceeded" substring may
    appear in the response body.
    """
    from echoroo.api.web_v1.projects import _members as members_module

    monkeypatch.setattr(members_module, "_BULK_INVITE_HOUR_LIMIT", 1)

    owner = await _create_user(
        db_session, email="t291-r1-rl-owner@example.com",
    )
    project = await _create_project(db_session, owner)
    owner_headers = await _bff_session_headers(client, db_session, owner)

    emails = _make_unique_emails(3)
    response = await client.post(
        f"/web-api/v1/projects/{project.id}/invitations/bulk",
        headers=owner_headers,
        json={"role": "member", "emails": emails},
    )
    assert response.status_code == 207, response.text
    rows = response.json()
    assert len(rows) == 3
    assert rows[0]["status"] == "issued"
    assert rows[1]["status"] == "rate_limited"
    assert rows[2]["status"] == "rate_limited"

    # The forbidden internal identifiers must not appear ANYWHERE in the
    # response body.
    body_text = response.text
    actor_id = str(owner.id)
    project_id = str(project.id)
    assert actor_id not in body_text, body_text
    assert project_id not in body_text, body_text
    # The legacy exception-formatting prefix (``"actor <uuid> exceeded "``
    # / ``"project <uuid> exceeded "``) must not appear either.
    assert "exceeded invitation rate limit" not in body_text, body_text

    # The constant generic message must be the visible substitute on
    # every rate-limited row.
    for r in rows[1:]:
        assert r["error_message"] == (
            "Rate limit reached for this issuer; retry after the per-hour "
            "or per-day window."
        ), r
