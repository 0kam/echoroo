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
    canonicalize_email,
    create_invitation,
)

# ---------------------------------------------------------------------------
# Fixtures (mirror tests/integration/test_member_invitation_flow.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_response_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable the 300ms constant-timing pad so tests stay fast."""
    from echoroo.api.web_v1 import auth as auth_module

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr(
        auth_module,
        "_invitation_public_sleep_for_minimum",
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
    """Decline leaves the project SU-owned (FR-011-124)."""
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

    # Flip the invitation row directly to DECLINED (mirrors the public
    # decline endpoint; the endpoint surface lives in the existing
    # ``_members.py`` recipient decline handler and is exercised by
    # ``test_member_invitation_flow``).
    await db_session.execute(
        sa.text(
            "UPDATE project_invitations "
            "SET status='declined', declined_at=now() "
            "WHERE id=:id"
        ),
        {"id": invitation_id},
    )
    await db_session.commit()

    # Project owner stays the SU.
    project_row = (
        await db_session.execute(
            sa.select(Project).where(Project.id == project_id),
        )
    ).scalar_one()
    assert project_row.owner_id == superuser.id
    # The intended owner is NOT a member.
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
            license=ProjectLicense.CC_BY,
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
