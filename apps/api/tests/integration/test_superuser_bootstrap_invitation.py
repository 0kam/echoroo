"""spec/011 T541 — System superuser project bootstrap integration tests.

Covers FR-011-120..125 end-to-end against the real FastAPI app + test
DB. Exercises:

* **FR-011-120 / FR-011-125** — non-superuser callers silently drop
  ``intended_owner_email`` and the response shape stays identical to
  a vanilla create.
* **FR-011-121** — superuser callers atomically create the project +
  issue a Member-kind ADMIN-role invitation with
  ``ownership_transfer_on_accept=true``; the response carries the
  signed envelope under ``invitation_url`` and the matching
  ``invitation_id``.
* **FR-011-123** — accepting the bootstrap invitation flips
  ``Project.owner_id`` to the intended owner, demotes the SU to a
  member row at role=ADMIN, and post-commits the
  ``project.ownership.bootstrap_transfer`` composite audit row with
  ``pre_transfer_action_summary``.
* **FR-011-124** — declining / revoking / expiring the bootstrap
  invitation leaves the project SU-owned (transfer never fires).

The R5 defence-in-depth path (Member-kind required when
``ownership_transfer_on_accept=True``) is covered by
``apps/api/tests/security/test_invitation_kind_guard.py`` (T542); we
keep a small ``test_r5_defence_in_depth`` here as a traceability
breadcrumb so a maintainer searching for spec/011 Step 9 test files
lands on both.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
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
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectInvitation, ProjectMember
from echoroo.models.superuser import Superuser
from echoroo.models.user import User
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    AUDIT_ACTION_MEMBER_INVITE_ACCEPTED_SIGNUP,
    AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
    InvitationStateError,
    accept_invitation,
    canonicalize_email,
    create_invitation,
)

# ---------------------------------------------------------------------------
# Fixtures (mirror tests/integration/test_member_invitation_flow.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_response_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable every constant-timing pad so tests stay fast.

    spec/011 Step 9 R1 P0-3 added a 150ms floor on
    ``POST /web-api/v1/projects`` so the SU bootstrap branch is
    timing-indistinguishable from the non-SU drop branch. Tests
    monkey-patch that helper alongside the Step 7 invitation public
    pad so the integration suite runs at full speed.
    """
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.api.web_v1.projects import _core as projects_core_module

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr(
        auth_module,
        "_invitation_public_sleep_for_minimum",
        _noop,
    )
    monkeypatch.setattr(
        projects_core_module,
        "_project_create_sleep_for_minimum",
        _noop,
    )


@pytest.fixture(autouse=True)
def _disable_invitation_public_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disable the spec/011 invitation rate-limit for the integration suite."""
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

    Mirrors the same patch the member-invitation flow suite installs.
    The bootstrap branch in ``_core.py`` consumes the same singleton
    via :func:`echoroo.core.redis.get_redis_connection` so we patch
    the module binding inside ``_core.py`` AND the shared singleton.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _get_fake() -> fakeredis.aioredis.FakeRedis:
        return fake

    from echoroo.api.web_v1.projects import _core as core_module

    monkeypatch.setattr(core_module, "get_redis_connection", _get_fake)
    from echoroo.core import redis as redis_module

    monkeypatch.setattr(redis_module, "get_redis_connection", _get_fake)
    return fake


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str | None = None,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email or f"t541-{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("correct horse battery staple"),
        display_name="T541 user",
        security_stamp="t541" + uuid.uuid4().hex,
        two_factor_enabled=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _promote_to_superuser(db: AsyncSession, user: User) -> None:
    """Insert a Superuser row so ``current_user.is_superuser`` resolves True."""
    db.add(
        Superuser(
            user_id=user.id,
            added_by_id=None,
            added_at=datetime.now(UTC),
        )
    )
    await db.commit()


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
    """Authenticate ``user`` on the BFF surface and return Bearer + CSRF."""
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


def _vanilla_create_payload(suffix: str | None = None) -> dict[str, Any]:
    return {
        "name": f"T541 project {suffix or uuid.uuid4().hex[:6]}",
        "visibility": ProjectVisibility.PUBLIC.value,
        "license": ProjectLicense.CC_BY.value,
    }


# ---------------------------------------------------------------------------
# 1. SU + intended_owner_email — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_superuser_with_intended_owner_email_issues_invitation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """SU bootstrap: project owned by SU + ADMIN Member-kind invitation issued."""
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    headers = await _bff_session_headers(client, db_session, superuser)

    intended_email = f"t541-intended-{uuid4().hex[:8]}@example.com"
    payload = _vanilla_create_payload("su-happy")
    payload["intended_owner_email"] = intended_email

    response = await client.post(
        "/web-api/v1/projects/",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    assert (
        response.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    body = response.json()

    assert body["invitation_url"], "invitation_url must be populated for SU bootstrap"
    assert body["invitation_id"], "invitation_id must be populated for SU bootstrap"

    project_id = UUID(body["id"])
    invitation_id = UUID(body["invitation_id"])

    # Owner is the superuser (placeholder owner before accept).
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id

    # Invitation row carries the spec/011 R5 combination.
    invitation_row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
            ),
        )
    ).scalar_one()
    assert invitation_row.kind is ProjectInvitationKind.MEMBER
    assert invitation_row.role is ProjectMemberRole.ADMIN
    assert invitation_row.ownership_transfer_on_accept is True
    assert invitation_row.email is not None
    assert canonicalize_email(invitation_row.email) == canonicalize_email(
        intended_email,
    )


# ---------------------------------------------------------------------------
# 2. Non-SU + intended_owner_email — silently dropped (FR-011-125)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_superuser_intended_owner_email_silently_dropped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Non-SU submission: response carries null invitation fields, no row issued."""
    plain_user = await _create_user(db_session)
    headers = await _bff_session_headers(client, db_session, plain_user)

    payload = _vanilla_create_payload("non-su")
    payload["intended_owner_email"] = f"t541-decoy-{uuid4().hex[:8]}@example.com"

    response = await client.post(
        "/web-api/v1/projects/",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    # FR-011-125 anti-enumeration: cache-control is uniform.
    assert (
        response.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    body = response.json()
    # The fields are present (same shape) but null.
    assert body["invitation_url"] is None
    assert body["invitation_id"] is None
    # The caller owns the project — the field was silently dropped.
    project_id = UUID(body["id"])
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == plain_user.id
    # No invitation was issued.
    invitation_count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(ProjectInvitation.project_id == project_id),
        )
    ).scalar_one()
    assert invitation_count == 0


# ---------------------------------------------------------------------------
# 2b. spec/011 Step 9 R1 P0-2 — malformed ``intended_owner_email`` from a
#     non-superuser is silently dropped (NO 422 email-format error).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_superuser_malformed_intended_owner_email_silently_dropped(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Non-SU + malformed value: vanilla 201, no field-existence leak.

    spec/011 Step 9 R1 P0-2: when ``intended_owner_email`` was an
    ``EmailStr`` at the schema layer, Pydantic ran email-format validation
    BEFORE the handler's SU drop branch could fire — a non-SU submitting
    ``intended_owner_email="not-an-email"`` got a 422 ``value is not a
    valid email address`` response, which leaked that the server
    recognises the field (a single failed format probe lets an attacker
    enumerate the SU bootstrap feature). The fix weakens the schema type
    to ``str | None`` and moves the format validation INSIDE the handler
    AFTER the SU check, so non-SU callers' submissions are silently
    dropped without ANY validation feedback regardless of format.
    """
    plain_user = await _create_user(db_session)
    headers = await _bff_session_headers(client, db_session, plain_user)

    payload = _vanilla_create_payload("non-su-malformed")
    payload["intended_owner_email"] = "not-an-email"

    response = await client.post(
        "/web-api/v1/projects/",
        headers=headers,
        json=payload,
    )
    # MUST be 201, NOT 422 — the malformed value is silently dropped.
    assert response.status_code == 201, response.text
    assert (
        response.headers.get("cache-control")
        == "no-store, no-cache, must-revalidate, private"
    )
    body = response.json()
    # Same shape as the no-bootstrap branch: both fields are null.
    assert body["invitation_url"] is None
    assert body["invitation_id"] is None
    # Caller still owns the freshly-created project.
    project_id = UUID(body["id"])
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == plain_user.id
    # No invitation row.
    invitation_count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(ProjectInvitation)
            .where(ProjectInvitation.project_id == project_id),
        )
    ).scalar_one()
    assert invitation_count == 0


# ---------------------------------------------------------------------------
# 3. SU bootstrap accept by intended owner (existing user) — ownership
#    transferred + SU demoted to ADMIN ProjectMember + composite audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_accept_by_existing_user_transfers_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Accept by an existing user fires the SAVEPOINT branch end-to-end."""
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-existing-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("xfer-existing")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    token = create_body["invitation_url"]
    project_id = UUID(create_body["id"])

    # Accept as the intended owner (existing-user branch).
    intended_headers = await _bff_session_headers(
        client, db_session, intended_user,
    )
    accept_response = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=intended_headers,
        json={"accept": True},
    )
    assert accept_response.status_code == 201, accept_response.text
    accept_body = accept_response.json()
    assert accept_body["ownership_transferred"] is True

    # Project owner flipped.
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == intended_user.id

    # Prior owner (SU) is now a ProjectMember at role=ADMIN.
    su_member_row = (
        await db_session.execute(
            sa.select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == superuser.id,
                ProjectMember.removed_at.is_(None),
            ),
        )
    ).scalar_one()
    assert su_member_row.role is ProjectMemberRole.ADMIN

    # Composite audit row exists with pre_transfer_action_summary payload.
    composite_rows = (
        await db_session.execute(
            sa.text(
                "SELECT detail FROM project_audit_log "
                "WHERE project_id = :pid AND action = :action"
            ),
            {
                "pid": str(project_id),
                "action": AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            },
        )
    ).all()
    assert len(composite_rows) == 1
    detail = composite_rows[0][0]
    if isinstance(detail, str):  # SQLite returns str; PG returns dict
        detail = json.loads(detail)
    assert detail["prior_owner"] == str(superuser.id)
    assert detail["new_owner"] == str(intended_user.id)
    assert "pre_transfer_action_summary" in detail
    assert "summary" in detail["pre_transfer_action_summary"]


# ---------------------------------------------------------------------------
# 4. Decline by intended owner — no transfer (FR-011-124)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_does_not_transfer(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Decline leaves the project SU-owned (FR-011-124).

    spec/011 Step 9 R1 P1-3 — the decline transition is exercised via
    the real :func:`invitation_service.decline_invitation_by_recipient`
    service entry point, not raw SQL. Calling the service guarantees
    the same recipient-decline state machine the public endpoint goes
    through actually rejects the SAVEPOINT branch from ever firing.
    """
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-decline-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("decline")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    project_id = UUID(create_body["id"])
    invitation_id = UUID(create_body["invitation_id"])
    token = create_body["invitation_url"]

    # Drive the actual recipient-decline service (real state machine —
    # mirrors what ``DELETE /web-api/v1/projects/{pid}/invitations/{tok}``
    # would invoke for an authenticated recipient). The service rejects
    # the bootstrap SAVEPOINT branch by transitioning ``status`` to
    # DECLINED before ``accept_invitation_via_public_token`` is reachable.
    decline_outcome = await invitation_service.decline_invitation_by_recipient(
        db_session,
        signed_token=token,
        current_user_id=intended_user.id,
        current_user_email=intended_user.email,
        hmac_secret=get_settings().web_session_secret,
        project_id_scope=project_id,
    )
    await db_session.commit()
    assert not decline_outcome.is_replay
    assert (
        decline_outcome.invitation.status is ProjectInvitationStatus.DECLINED
    )
    assert decline_outcome.invitation.id == invitation_id

    # Project owner stays the SU.
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id
    # The intended owner is NOT a member (decline NEVER transfers — the
    # SAVEPOINT branch only runs on accept).
    intended_member = (
        await db_session.execute(
            sa.select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == intended_user.id,
                ProjectMember.removed_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    assert intended_member is None
    # No composite audit was written.
    composite_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id=:pid AND action=:action"
            ),
            {
                "pid": str(project_id),
                "action": AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            },
        )
    ).scalar_one()
    assert composite_count == 0


# ---------------------------------------------------------------------------
# 5. Revoke by SU before accept — no transfer (FR-011-124)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_does_not_transfer(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Revoke leaves the project SU-owned (FR-011-124)."""
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-revoke-{uuid4().hex[:8]}@example.com"

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("revoke")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    project_id = UUID(create_body["id"])
    invitation_id = UUID(create_body["invitation_id"])

    # Direct revoke via raw SQL — the bootstrap invitation is normal
    # otherwise; the public revoke handler is exercised in the bulk
    # invitation tests. We assert here that ``status=revoked`` alone
    # does not trip the SAVEPOINT branch.
    await db_session.execute(
        sa.text(
            "UPDATE project_invitations "
            "SET status='revoked', revoked_at=now() "
            "WHERE id=:id"
        ),
        {"id": invitation_id},
    )
    await db_session.commit()

    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id
    composite_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id=:pid AND action=:action"
            ),
            {
                "pid": str(project_id),
                "action": AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            },
        )
    ).scalar_one()
    assert composite_count == 0


# ---------------------------------------------------------------------------
# 6. Expiry sweep — no transfer (FR-011-124)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_invitation_does_not_transfer(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """An expired bootstrap invitation cannot be accepted (FR-011-124)."""
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-expire-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("expire")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    project_id = UUID(create_body["id"])
    invitation_id = UUID(create_body["invitation_id"])
    token = create_body["invitation_url"]

    # Force the row to expire by setting expires_at in the past.
    await db_session.execute(
        sa.text(
            "UPDATE project_invitations "
            "SET expires_at = now() - INTERVAL '1 second' "
            "WHERE id=:id"
        ),
        {"id": invitation_id},
    )
    await db_session.commit()

    intended_headers = await _bff_session_headers(
        client, db_session, intended_user,
    )
    accept_response = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=intended_headers,
        json={"accept": True},
    )
    # Public-token surface collapses every failure cause to the generic
    # 404 (FR-011-107).
    assert accept_response.status_code == 404

    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id
    composite_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id=:pid AND action=:action"
            ),
            {
                "pid": str(project_id),
                "action": AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            },
        )
    ).scalar_one()
    assert composite_count == 0


# ---------------------------------------------------------------------------
# 7. SAVEPOINT failure rollback (negative test)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_savepoint_failure_rolls_back_parent_transaction(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure inside the SAVEPOINT rolls back the whole parent TX.

    We monkeypatch :func:`build_pre_transfer_action_summary` (called by
    the SAVEPOINT branch) to raise. The accept handler MUST rollback
    the parent transaction so:

    * The invitation row stays ``pending`` (NOT ``accepted``).
    * No ``ProjectMember`` row exists for the intended owner.
    * No composite audit row is written.

    This is the FR-011-123 step-5 invariant: "On SAVEPOINT failure:
    rollback the SAVEPOINT and the parent transaction".
    """
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-savepoint-fail-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("savepoint-fail")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    token = create_body["invitation_url"]
    invitation_id = UUID(create_body["invitation_id"])
    project_id = UUID(create_body["id"])

    # Patch the helper that runs inside the SAVEPOINT so it raises. The
    # accept handler's outer except block MUST rollback the entire TX.
    async def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("synthetic savepoint failure")

    monkeypatch.setattr(
        invitation_service,
        "build_pre_transfer_action_summary",
        _explode,
    )

    intended_headers = await _bff_session_headers(
        client, db_session, intended_user,
    )
    # The synthetic RuntimeError propagates through the ASGI transport;
    # the substantive guarantees are the DB-state assertions below
    # (invitation row remains pending, no membership row, owner unchanged,
    # no composite audit). The pytest.raises here just absorbs the
    # surfaced exception so the rest of the test can run.
    with pytest.raises(RuntimeError, match="synthetic savepoint failure"):
        await client.post(
            f"/web-api/v1/auth/invitations/{token}/accept",
            headers=intended_headers,
            json={"accept": True},
        )

    # Force the session to drop any in-flight state so the SELECTs below
    # see the post-rollback DB contents.
    await db_session.rollback()

    invitation_row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
            ),
        )
    ).scalar_one()
    assert invitation_row.status is ProjectInvitationStatus.PENDING

    member_row = (
        await db_session.execute(
            sa.select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == intended_user.id,
                ProjectMember.removed_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    assert member_row is None

    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id

    composite_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id=:pid AND action=:action"
            ),
            {
                "pid": str(project_id),
                "action": AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            },
        )
    ).scalar_one()
    assert composite_count == 0


# ---------------------------------------------------------------------------
# 8. R5 traceability — Trusted + transfer rejected at service layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_r5_defence_in_depth(
    db_session: AsyncSession,
) -> None:
    """``ownership_transfer_on_accept=True`` + ``kind=trusted`` raises.

    Traceability breadcrumb — the full DB-CHECK + service-layer + accept
    coverage lives in ``apps/api/tests/security/test_invitation_kind_guard.py``
    (T058 / T542). This single-call test pins the connection between
    the SU-bootstrap test module and the R5 defence so a grep for
    spec/011 Step 9 lands on both files.
    """

    class _FakeRedis:
        async def incr(self, name: str) -> int:  # noqa: ARG002
            return 1

        async def expire(self, name: str, time: int) -> bool:  # noqa: ARG002
            return True

        async def get(self, name: str) -> Any:  # noqa: ARG002
            return None

        async def set(  # noqa: D401, ARG002
            self,
            name: str,
            value: Any,
            *,
            ex: int | None = None,
            nx: bool = False,
        ) -> bool | None:
            return True

    issuer = await _create_user(db_session)
    # Use a Public project — visibility does not matter for R5; the
    # service guard fires before any DB round trip.
    project_id = uuid4()
    db_session.add(
        Project(
            id=project_id,
            name=f"r5-{uuid4().hex[:6]}",
            visibility=ProjectVisibility.PUBLIC,
            license_id="cc-by",
            owner_id=issuer.id,
        )
    )
    await db_session.commit()

    with pytest.raises(InvitationStateError) as exc_info:
        await create_invitation(
            db_session,
            project_id=project_id,
            kind=ProjectInvitationKind.TRUSTED,
            email=f"r5-su-bootstrap-{uuid4().hex[:6]}@example.com",
            invited_by_id=issuer.id,
            hmac_secret="r5-test-hmac-32chars-padding-xxxxxxx",
            redis=_FakeRedis(),  # type: ignore[arg-type]
            granted_permissions=["view_media"],
            trusted_duration_seconds=86400,
            ownership_transfer_on_accept=True,
        )
    assert "ownership_transfer_on_accept_invalid_for_kind" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 9. spec/011 Step 9 R1 P0-1 — legacy authenticated-only accept path
#    refuses ``ownership_transfer_on_accept=True`` rows.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_accept_path_refuses_bootstrap_invitation(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The legacy ``accept_invitation`` rejects SU-bootstrap invitations.

    The Step 9 SAVEPOINT-nested ownership transfer is wired into
    ``accept_invitation_via_public_token`` only. Without an explicit
    refusal on the legacy path the same invitation token can be POSTed
    to ``/web-api/v1/projects/{project_id}/invitations/{token}/accept``
    (the legacy endpoint that maps to :func:`accept_invitation`); the
    row would flip to ``accepted`` and the SAVEPOINT branch would NOT
    run, leaving the project SU-owned and the intended owner as a
    plain ADMIN member — a silent ownership-transfer leak.

    spec/011 Step 9 R1 P0-1: the legacy service raises
    :class:`InvitationStateError` (``ownership_transfer_must_use_public_path``)
    so the endpoint maps to 410. We assert at the service layer
    because the legacy path's endpoint is parameterised through
    ``project_id`` + a 4-part signed token; the service-layer guard
    is the authoritative defence.
    """
    # Issue a Step 9 SU bootstrap invitation through the real endpoint.
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-legacy-reject-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("legacy-reject")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    token = create_body["invitation_url"]
    project_id = UUID(create_body["id"])
    invitation_id = UUID(create_body["invitation_id"])

    # Drive the legacy ``accept_invitation`` service directly. The guard
    # we just added MUST surface as :class:`InvitationStateError` carrying
    # ``ownership_transfer_must_use_public_path`` so the endpoint maps to
    # 410. Use a lightweight fake Redis so the idempotency short-circuit
    # is exercised without needing a live broker.

    class _FakeRedis:
        async def incr(self, name: str) -> int:  # noqa: ARG002
            return 1

        async def expire(self, name: str, time: int) -> bool:  # noqa: ARG002
            return True

        async def get(self, name: str) -> Any:  # noqa: ARG002
            return None

        async def set(  # noqa: D401, ARG002
            self,
            name: str,
            value: Any,
            *,
            ex: int | None = None,
            nx: bool = False,
        ) -> bool | None:
            return True

    with pytest.raises(InvitationStateError) as exc_info:
        await accept_invitation(
            db_session,
            signed_token=token,
            current_user_id=intended_user.id,
            current_user_email=intended_user.email,
            hmac_secret=get_settings().web_session_secret,
            redis=_FakeRedis(),  # type: ignore[arg-type]
            project_id_scope=project_id,
        )
    assert "ownership_transfer_must_use_public_path" in str(exc_info.value)

    # Belt-and-braces: the invitation row is still PENDING (the guard
    # raised before the atomic UPDATE could fire) and the project owner
    # is still the SU placeholder.
    await db_session.rollback()
    invitation_row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
            ),
        )
    ).scalar_one()
    assert invitation_row.status is ProjectInvitationStatus.PENDING

    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id


# ---------------------------------------------------------------------------
# 10. spec/011 Step 9 R1 P1-1 — ``Project.updated_at`` is preserved across
#     the bootstrap ownership flip (no ``onupdate`` bump).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ownership_transfer_preserves_project_updated_at(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """The SAVEPOINT-nested owner UPDATE does NOT bump ``updated_at``.

    spec/011 Step 9 R1 P1-1: the bootstrap transfer is a system-internal
    lifecycle event (placeholder SU yields to the intended owner) and
    MUST NOT pollute the project's mtime-driven sort orders / cache
    keys. The :class:`TimestampMixin` declares ``onupdate=lambda: now()``
    which SQLAlchemy auto-applies to every Core ``update()`` whose
    ``.values()`` clause does NOT mention the column. The service-layer
    fix pins ``updated_at`` to its current value via the literal
    ``Project.__table__.c.updated_at`` (a no-op self-assignment) so
    ``onupdate`` is suppressed. The composite audit row records the
    transfer's ``at`` timestamp separately for observability.
    """
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-updated-at-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("updated-at")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    token = create_body["invitation_url"]
    project_id = UUID(create_body["id"])

    # Snapshot ``updated_at`` BEFORE the accept fires the SAVEPOINT
    # branch. Read via raw SQL so the value is a Python-side capture
    # that survives the ORM identity-map cache below (a subsequent
    # ``select(Project)`` would hand back the same cached row and
    # the in-Python ``updated_at`` would not refresh from DB).
    updated_at_before_row = (
        await db_session.execute(
            sa.text("SELECT updated_at FROM projects WHERE id = :pid"),
            {"pid": str(project_id)},
        )
    ).first()
    assert updated_at_before_row is not None
    updated_at_before = updated_at_before_row[0]

    # Accept as the intended owner — the SAVEPOINT branch flips
    # ``Project.owner_id``. The fix MUST hold ``updated_at`` constant.
    intended_headers = await _bff_session_headers(
        client, db_session, intended_user,
    )
    accept_response = await client.post(
        f"/web-api/v1/auth/invitations/{token}/accept",
        headers=intended_headers,
        json={"accept": True},
    )
    assert accept_response.status_code == 201, accept_response.text

    # The accept endpoint runs on its own DB session (the FastAPI
    # request dependency yields a fresh ``AsyncSession``); the
    # ``db_session`` fixture's connection still holds an open
    # transaction view of the row from before the accept. Issue a
    # rollback to drop the snapshot view, then read via raw SQL so
    # the result reflects the accept's committed state and bypasses
    # the ORM identity map entirely.
    await db_session.rollback()
    after_row_raw = (
        await db_session.execute(
            sa.text(
                "SELECT owner_id, updated_at FROM projects WHERE id = :pid"
            ),
            {"pid": str(project_id)},
        )
    ).first()
    assert after_row_raw is not None
    owner_id_after, updated_at_after = after_row_raw
    assert UUID(str(owner_id_after)) == intended_user.id, (
        "ownership transfer should have flipped owner_id "
        f"(got {owner_id_after!r}, expected {intended_user.id!r})"
    )
    assert updated_at_after == updated_at_before, (
        "Project.updated_at must NOT be bumped by the bootstrap transfer "
        f"(before={updated_at_before!r}, after={updated_at_after!r})"
    )


# ---------------------------------------------------------------------------
# 11. spec/011 Step 9 R1 P1-2 — SAVEPOINT rollback AFTER the owner UPDATE
#     succeeded. Patches the post-upsert hook so the failure surfaces
#     after the critical DB writes — asserts the entire parent TX
#     rolls back (owner_id reverts to SU, invitation row reverts to
#     PENDING, no ProjectMember row for the prior owner).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_savepoint_rollback_after_owner_update_succeeded(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure AFTER the owner UPDATE + ProjectMember upsert rolls back.

    spec/011 Step 9 R1 P1-2: complements
    :func:`test_savepoint_failure_rolls_back_parent_transaction` (which
    patches the FIRST SAVEPOINT step — ``build_pre_transfer_action_summary``).
    This variant patches the LAST SAVEPOINT step
    (:func:`_ownership_transfer_savepoint_finalize_hook`, which fires
    after Steps 3 + 4 have already committed dirty state into the
    SAVEPOINT) so the rollback-after-success invariant is exercised
    end-to-end: even when the owner UPDATE has effectively run inside
    the nested TX, exception propagation MUST undo it.
    """
    superuser = await _create_user(db_session)
    await _promote_to_superuser(db_session, superuser)
    intended_email = f"t541-rollback-post-update-{uuid4().hex[:8]}@example.com"
    intended_user = await _create_user(db_session, email=intended_email)

    su_headers = await _bff_session_headers(client, db_session, superuser)
    payload = _vanilla_create_payload("rollback-post-update")
    payload["intended_owner_email"] = intended_email
    create_response = await client.post(
        "/web-api/v1/projects/",
        headers=su_headers,
        json=payload,
    )
    assert create_response.status_code == 201, create_response.text
    create_body = create_response.json()
    token = create_body["invitation_url"]
    invitation_id = UUID(create_body["invitation_id"])
    project_id = UUID(create_body["id"])

    # Patch the LAST step of the SAVEPOINT block to raise. The hook is
    # placed AFTER the owner UPDATE + ProjectMember upsert; an exception
    # here must unwind every dirty change inside the SAVEPOINT + the
    # parent transaction.
    async def _explode_post_owner_update() -> None:
        raise RuntimeError("synthetic post-owner-update failure")

    monkeypatch.setattr(
        invitation_service,
        "_ownership_transfer_savepoint_finalize_hook",
        _explode_post_owner_update,
    )

    intended_headers = await _bff_session_headers(
        client, db_session, intended_user,
    )
    with pytest.raises(RuntimeError, match="synthetic post-owner-update failure"):
        await client.post(
            f"/web-api/v1/auth/invitations/{token}/accept",
            headers=intended_headers,
            json={"accept": True},
        )

    # Drop any in-flight state so SELECTs below see the post-rollback DB.
    await db_session.rollback()

    # The invitation row reverts to PENDING (the parent TX rolled back).
    invitation_row = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id,
            ),
        )
    ).scalar_one()
    assert invitation_row.status is ProjectInvitationStatus.PENDING

    # The owner UPDATE that *appeared* to succeed inside the SAVEPOINT
    # was unwound — ``owner_id`` is back to the SU placeholder.
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id

    # The ProjectMember upsert (Step 4 inside the SAVEPOINT) is undone:
    # no membership row exists for the SU (the prior owner — would have
    # been demoted to ADMIN) nor for the intended owner.
    prior_owner_member = (
        await db_session.execute(
            sa.select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == superuser.id,
                ProjectMember.removed_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    assert prior_owner_member is None

    intended_owner_member = (
        await db_session.execute(
            sa.select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == intended_user.id,
                ProjectMember.removed_at.is_(None),
            ),
        )
    ).scalar_one_or_none()
    assert intended_owner_member is None

    # No composite audit row was written.
    composite_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_audit_log "
                "WHERE project_id=:pid AND action=:action"
            ),
            {
                "pid": str(project_id),
                "action": AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER,
            },
        )
    ).scalar_one()
    assert composite_count == 0
