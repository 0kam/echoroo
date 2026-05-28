"""FR-053 idempotency-key contract tests (T531).

The accept endpoint authenticates retries via the ``X-Idempotency-Key``
header (mapped to the :func:`accept_invitation` ``idempotency_key``
argument). The Redis-backed dedupe lives at the service layer and this
module pins the security-critical edges:

1. Same key + same token + replay              → HTTP 200 / ``is_replay=True``.
2. Same key + different token                  → ``InvitationConflictError`` (409).
3. Different key + already-accepted token      → ``InvitationStateError`` (410).
4. No key + already-accepted token             → ``InvitationStateError`` (410).
5. Concurrent accepts on the same row          → one wins, the other 410/409.
6. Redis GET fault during the short-circuit    → ``InvitationInfraUnavailableError``.
7. Redis SET fault during the post-success pin → ``InvitationInfraUnavailableError``.

These tests run against the real test DB so the FOR UPDATE row lock,
the partial-unique pending invitation, and the
``ux_project_trusted_users_active`` partial unique are exercised. Redis
is replaced with an in-memory fake so we can deterministically inject
faults.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectInvitationStatus
from echoroo.models.project import ProjectInvitation
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    InvitationConflictError,
    InvitationInfraUnavailableError,
    InvitationStateError,
    accept_invitation,
    sign_invitation_token,
)

HMAC_SECRET = "t531-idempotency-secret-32-bytes-of-entropy!!!!"


class _FakeRedis:
    """In-memory Redis fake with controllable fault injection."""

    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.fail_on_get: bool = False
        self.fail_on_set: bool = False

    async def incr(self, name: str) -> int:
        v = int(self.values.get(name, 0)) + 1
        self.values[name] = v
        return v

    async def expire(self, name: str, time: int) -> bool:
        if name in self.values:
            self.ttls[name] = time
            return True
        return False

    async def get(self, name: str) -> Any:
        if self.fail_on_get:
            raise ConnectionError("redis unreachable")
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if self.fail_on_set:
            raise ConnectionError("redis unreachable")
        if nx and name in self.values:
            return None
        self.values[name] = value
        if ex is not None:
            self.ttls[name] = ex
        return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_member_invitation(
    db: AsyncSession,
    *,
    email: str,
    invited_by_id: Any,
    project_id: Any,
    raw_seed: bytes = b"\x55" * 32,
) -> tuple[ProjectInvitation, str]:
    """Insert a pending Member invitation via raw SQL (FR JSONB NULL handling)."""
    raw_token_b64u = invitation_service._b64u_encode(raw_seed)
    token_hash = invitation_service.hash_token(raw_token_b64u)
    expires_at = datetime.now(UTC) + timedelta(days=1)
    signed = sign_invitation_token(
        raw_token_b64u=raw_token_b64u,
        expires_at=expires_at,
        hmac_secret=HMAC_SECRET,
    )
    email_hash_value = invitation_service.hash_email(
        email, hmac_secret=HMAC_SECRET
    )
    invitation_id = uuid4()
    await db.execute(
        sa.text(
            """
            INSERT INTO project_invitations
                (id, project_id, kind, email, email_hash, role,
                 granted_permissions, trusted_duration_seconds,
                 token_hash, invited_by_id, expires_at, status,
                 created_at, updated_at)
            VALUES
                (:id, :project_id, 'member', :email, :email_hash, 'member',
                 NULL, NULL,
                 :token_hash, :invited_by_id, :expires_at, 'pending',
                 NOW(), NOW())
            """
        ),
        {
            "id": invitation_id,
            "project_id": project_id,
            "email": email,
            "email_hash": email_hash_value,
            "token_hash": token_hash,
            "invited_by_id": invited_by_id,
            "expires_at": expires_at,
        },
    )
    await db.commit()
    invitation = (
        await db.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation_id
            )
        )
    ).scalar_one()
    return invitation, signed


async def _seed_project(db: AsyncSession, owner_id: Any) -> Any:
    from echoroo.models.enums import ProjectVisibility
    from echoroo.models.project import Project

    project = Project(
        name=f"T531 {uuid4().hex[:8]}",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
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


async def _seed_recipient(db: AsyncSession) -> Any:
    from echoroo.models.user import User

    user = User(
        email=f"t531-recip-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T531 Recipient",
        security_stamp="t531" + "r" * 60,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id


@pytest_asyncio.fixture
async def t531_owner_id(db_session: AsyncSession) -> Any:
    from echoroo.models.user import User

    user = User(
        email=f"t531-owner-{uuid4().hex[:8]}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T531 Owner",
        security_stamp="t531" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    return user.id


async def _purge_invitations(db: AsyncSession) -> None:
    await db.execute(sa.text("DELETE FROM project_members"))
    await db.execute(sa.text("DELETE FROM project_invitations"))
    await db.commit()


# ---------------------------------------------------------------------------
# 1. Same key + same token replay → is_replay=True, no duplicate member row.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_key_same_token_replay_is_idempotent(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email = "alice-idem-1@example.com"
    project_id = await _seed_project(db_session, t531_owner_id)
    invitation, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id,
        raw_seed=b"\x10" * 32,
    )
    user_id = await _seed_recipient(db_session)
    fake_redis = _FakeRedis()
    key = "client-key-1"

    first = await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=user_id,
        current_user_email=email,
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        idempotency_key=key,
    )
    assert first.invitation.status is ProjectInvitationStatus.ACCEPTED
    assert first.is_replay is False

    # Replay under the same key + same token → returns the cached outcome.
    replay = await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=user_id,
        current_user_email=email,
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        idempotency_key=key,
    )
    assert replay.is_replay is True
    assert replay.invitation.id == invitation.id
    # Should not have created a second ProjectMember row.
    member_count = (
        await db_session.execute(
            sa.text(
                "SELECT COUNT(*) FROM project_members "
                "WHERE project_id = :pid AND user_id = :uid"
            ),
            {"pid": str(invitation.project_id), "uid": str(user_id)},
        )
    ).scalar_one()
    assert member_count == 1


# ---------------------------------------------------------------------------
# 2. Same key + different token → 409 conflict.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_key_different_token_raises_conflict(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email_a = "alice-idem-2a@example.com"
    email_b = "alice-idem-2b@example.com"
    project_id_a = await _seed_project(db_session, t531_owner_id)
    project_id_b = await _seed_project(db_session, t531_owner_id)
    _, signed_a = await _seed_member_invitation(
        db_session,
        email=email_a,
        invited_by_id=t531_owner_id,
        project_id=project_id_a,
        raw_seed=b"\x20" * 32,
    )
    _, signed_b = await _seed_member_invitation(
        db_session,
        email=email_b,
        invited_by_id=t531_owner_id,
        project_id=project_id_b,
        raw_seed=b"\x21" * 32,
    )
    fake_redis = _FakeRedis()
    key = "client-key-2"

    # First accept pins the key to invitation A.
    await accept_invitation(
        db_session,
        signed_token=signed_a,
        current_user_id=await _seed_recipient(db_session),
        current_user_email=email_a,
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        idempotency_key=key,
    )

    # Reusing the same key with token B → 409.
    with pytest.raises(InvitationConflictError):
        await accept_invitation(
            db_session,
            signed_token=signed_b,
            current_user_id=await _seed_recipient(db_session),
            current_user_email=email_b,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key=key,
        )


# ---------------------------------------------------------------------------
# 3. Different key + already-accepted token → 410.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_key_already_accepted_token_raises_state_error(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email = "alice-idem-3@example.com"
    project_id = await _seed_project(db_session, t531_owner_id)
    _, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id,
        raw_seed=b"\x30" * 32,
    )
    fake_redis = _FakeRedis()
    user_id = await _seed_recipient(db_session)

    # First accept under key-A.
    await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=user_id,
        current_user_email=email,
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        idempotency_key="key-a",
    )

    # Different key against the same (now ACCEPTED) row → state error,
    # because the replay short-circuit refuses to honour an unknown key.
    with pytest.raises(InvitationStateError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key="key-b-different",
        )


# ---------------------------------------------------------------------------
# 4. No key + already-accepted token → 410.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_key_already_accepted_raises_state_error(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email = "alice-idem-4@example.com"
    project_id = await _seed_project(db_session, t531_owner_id)
    _, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id,
        raw_seed=b"\x40" * 32,
    )
    fake_redis = _FakeRedis()
    user_id = await _seed_recipient(db_session)

    # First accept WITH a key.
    await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=user_id,
        current_user_email=email,
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        idempotency_key="key-with-record",
    )

    # Second accept WITHOUT a key against the ACCEPTED row → state error.
    with pytest.raises(InvitationStateError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key=None,
        )


# ---------------------------------------------------------------------------
# 5. Concurrent accept (sequential because asyncio semantics are
#    single-threaded with await points): one accept wins, the second
#    sees the ACCEPTED row and either replays (matching key) or 410.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_accept_one_wins_other_replays_or_410(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email = "alice-idem-5@example.com"
    project_id = await _seed_project(db_session, t531_owner_id)
    _, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id,
        raw_seed=b"\x50" * 32,
    )
    fake_redis = _FakeRedis()
    user_id = await _seed_recipient(db_session)

    async def _attempt(key: str) -> str:
        try:
            await accept_invitation(
                db_session,
                signed_token=signed,
                current_user_id=user_id,
                current_user_email=email,
                hmac_secret=HMAC_SECRET,
                redis=fake_redis,  # type: ignore[arg-type]
                idempotency_key=key,
            )
            return "ok"
        except InvitationStateError:
            return "state"
        except InvitationConflictError:
            return "conflict"

    # SQLAlchemy AsyncSession is not safe for concurrent use; we exercise
    # the "race" sequentially because the ``FOR UPDATE`` row lock + status
    # check inside :func:`accept_invitation` is the load-bearing serial
    # point. The first call wins (ACCEPTED), the second sees the terminal
    # row + non-matching cached record under a different key → state error.
    first = await _attempt("concurrent-key-a")
    second = await _attempt("concurrent-key-b")
    assert first == "ok"
    assert second in {"state", "conflict"}, (first, second)
    # Exactly one ProjectMember row exists.
    member_count = (
        await db_session.execute(sa.text("SELECT COUNT(*) FROM project_members"))
    ).scalar_one()
    assert member_count == 1


# ---------------------------------------------------------------------------
# 6. Redis GET fault → InvitationInfraUnavailableError.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_get_fault_during_short_circuit_fails_closed(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email = "alice-idem-6@example.com"
    project_id = await _seed_project(db_session, t531_owner_id)
    _, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id,
        raw_seed=b"\x60" * 32,
    )
    fake_redis = _FakeRedis()
    fake_redis.fail_on_get = True

    with pytest.raises(InvitationInfraUnavailableError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=await _seed_recipient(db_session),
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key="any-key",
        )


# ---------------------------------------------------------------------------
# 7. Redis SET fault during the post-success pin → fail-closed.
#
# We seed a fresh invitation then trip ``fail_on_set`` before invoking
# accept. The pin happens AFTER the DB mutation but the service raises
# the fault so callers see HTTP 503 — the persisted DB row is the
# security-critical bit; the dedupe pin is best-effort but failing it
# loudly is the correct policy (FR-053 says fail-closed).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_set_fault_during_pin_fails_closed(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    await _purge_invitations(db_session)
    email = "alice-idem-7@example.com"
    project_id = await _seed_project(db_session, t531_owner_id)
    _, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id,
        raw_seed=b"\x70" * 32,
    )
    fake_redis = _FakeRedis()
    fake_redis.fail_on_set = True

    with pytest.raises(InvitationInfraUnavailableError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=await _seed_recipient(db_session),
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key="will-fail-on-pin",
        )


# ---------------------------------------------------------------------------
# 8. Cross-project ``project_id_scope`` mismatch → InvitationTokenInvalidError.
#    Phase 10 Batch 2 Round 2 polish (致命 3): the service now accepts a
#    ``project_id_scope`` argument so an attacker cannot accept a valid
#    token under a different project's URL.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_with_wrong_project_id_scope_raises_token_invalid(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    from echoroo.services.invitation_service import (
        InvitationTokenInvalidError,
    )

    await _purge_invitations(db_session)
    email = "alice-cross-project@example.com"
    project_id_a = await _seed_project(db_session, t531_owner_id)
    project_id_b = await _seed_project(db_session, t531_owner_id)
    invitation, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id_a,
        raw_seed=b"\x80" * 32,
    )
    user_id = await _seed_recipient(db_session)
    fake_redis = _FakeRedis()

    # The token resolves the row under project A. Pinning the scope to
    # project B must raise InvitationTokenInvalidError("invitation not
    # found") so the handler maps to 404.
    with pytest.raises(InvitationTokenInvalidError):
        await accept_invitation(
            db_session,
            signed_token=signed,
            current_user_id=user_id,
            current_user_email=email,
            hmac_secret=HMAC_SECRET,
            redis=fake_redis,  # type: ignore[arg-type]
            idempotency_key=None,
            project_id_scope=project_id_b,
        )

    # Row is still PENDING — no leak.
    refreshed = (
        await db_session.execute(
            sa.select(ProjectInvitation).where(
                ProjectInvitation.id == invitation.id
            )
        )
    ).scalar_one()
    assert refreshed.status is ProjectInvitationStatus.PENDING


@pytest.mark.asyncio
async def test_accept_with_matching_project_id_scope_succeeds(
    db_session: AsyncSession,
    t531_owner_id: Any,
) -> None:
    """Sanity — the path scope guard does NOT regress the happy path."""
    await _purge_invitations(db_session)
    email = "alice-correct-project@example.com"
    project_id_a = await _seed_project(db_session, t531_owner_id)
    invitation, signed = await _seed_member_invitation(
        db_session,
        email=email,
        invited_by_id=t531_owner_id,
        project_id=project_id_a,
        raw_seed=b"\x81" * 32,
    )
    user_id = await _seed_recipient(db_session)
    fake_redis = _FakeRedis()

    outcome = await accept_invitation(
        db_session,
        signed_token=signed,
        current_user_id=user_id,
        current_user_email=email,
        hmac_secret=HMAC_SECRET,
        redis=fake_redis,  # type: ignore[arg-type]
        idempotency_key="cross-project-happy-path",
        project_id_scope=project_id_a,
    )
    assert outcome.invitation.id == invitation.id
    assert outcome.invitation.status is ProjectInvitationStatus.ACCEPTED


__all__ = [
    "test_accept_with_matching_project_id_scope_succeeds",
    "test_accept_with_wrong_project_id_scope_raises_token_invalid",
    "test_concurrent_accept_one_wins_other_replays_or_410",
    "test_different_key_already_accepted_token_raises_state_error",
    "test_no_key_already_accepted_raises_state_error",
    "test_redis_get_fault_during_short_circuit_fails_closed",
    "test_redis_set_fault_during_pin_fails_closed",
    "test_same_key_different_token_raises_conflict",
    "test_same_key_same_token_replay_is_idempotent",
]
