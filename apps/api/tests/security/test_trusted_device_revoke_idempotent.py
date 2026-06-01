"""Security tests for TrustedDeviceService.revoke_all_for_user (spec/011 T631).

FR-011-402 / T630 — verifies the idempotency, reason-allowlist, and audit
detail contract of the revoke-all primitive:

* First call revokes N active devices → emits one audit row with
  ``revoked_count=N``.
* Second call revokes 0 devices (none remain active) → still emits one audit
  row with ``revoked_count=0``.
* Unknown reason → raises ValueError.
* reason=None → raises ValueError.
* The audit detail carries all four required keys:
  ``{user_id, target_user_id, revoked_count, reason}``.
* actor_user_id defaults to user.id (self-revoke) and is overridable.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import echoroo.core.database as db_module
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.user import User
from echoroo.services import trusted_device_service as td_svc_mod
from echoroo.services.trusted_device_service import (
    AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
    REVOKE_ALL_REASONS,
    TrustedDeviceService,
)
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def audit_session_maker(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Rebind AsyncSessionLocal onto the test engine for audit row inspection.

    ``TrustedDeviceService._emit_revoke_all_audit`` does a local-import of
    ``AsyncSessionLocal`` from ``echoroo.core.database`` (PLC0415 guard),
    so the effective patch target is the module-level attribute on
    ``echoroo.core.database``, not on the service module itself.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Patch the canonical source that the local-import resolves at call time.
    monkeypatch.setattr(db_module, "AsyncSessionLocal", maker, raising=True)
    yield maker
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"revoke-all-{suffix or uuid4()}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"User {suffix}",
        security_stamp=secrets.token_hex(32),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_trusted_device(db: AsyncSession, *, user: User) -> TrustedDevice:
    now = datetime.now(UTC)
    device = TrustedDevice(
        user_id=user.id,
        device_secret_hash=secrets.token_hex(32),
        security_stamp=user.security_stamp,
        label="test-device",
        created_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=None,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    return device


async def _query_revoke_all_audit_rows(
    maker: async_sessionmaker[AsyncSession],
    *,
    target_user_id: UUID,
) -> list[dict]:
    """Fetch all auth.trusted_device.revoke_all rows for the target user."""
    async with maker() as session:
        result = await session.execute(
            sa.text(
                "SELECT id, actor_user_id_hash, detail "
                "FROM platform_audit_log "
                "WHERE action = :action "
                "ORDER BY created_at DESC"
            ),
            {"action": AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL},
        )
        rows = result.mappings().all()

    target_str = str(target_user_id)
    matching = []
    for row in rows:
        detail = row["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        if detail.get("target_user_id") == target_str:
            matching.append(dict(detail))
    return matching


# ---------------------------------------------------------------------------
# Tests — idempotency + audit emission
# ---------------------------------------------------------------------------


async def test_revoke_all_twice_emits_two_audit_rows(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """First call revokes N devices + one audit row; second call 0 + one row."""
    user = await _create_user(db_session, suffix="idempotent")
    user_id = user.id  # capture PK before ORM state changes
    await _create_trusted_device(db_session, user=user)
    await _create_trusted_device(db_session, user=user)

    svc = TrustedDeviceService(db_session)

    # First revoke: both devices active → revoked_count=2
    count1 = await svc.revoke_all_for_user(user=user, reason="password_change")
    await db_session.flush()

    # Second revoke: no devices left → revoked_count=0 but still emits
    count2 = await svc.revoke_all_for_user(user=user, reason="password_change")
    await db_session.flush()

    # Expunge ORM instances before commit so NullPool released connection
    # doesn't fail on lazy-load during SQLAlchemy post-commit expiry.
    db_session.expunge_all()
    await db_session.commit()

    assert count1 == 2, f"expected 2 devices revoked on first call, got {count1}"
    assert count2 == 0, f"expected 0 devices revoked on second call, got {count2}"

    # Two audit rows must have been emitted (one per call)
    audit_rows = await _query_revoke_all_audit_rows(
        audit_session_maker, target_user_id=user_id
    )
    assert len(audit_rows) == 2, (
        f"expected 2 audit rows (one per revoke call), got {len(audit_rows)}: {audit_rows}"
    )

    revoked_counts = {row["revoked_count"] for row in audit_rows}
    assert 2 in revoked_counts, "first audit row must have revoked_count=2"
    assert 0 in revoked_counts, "second audit row must have revoked_count=0"


async def test_revoke_all_audit_detail_carries_required_keys(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Audit detail must include user_id, target_user_id, revoked_count, reason."""
    user = await _create_user(db_session, suffix="detail-keys")
    svc = TrustedDeviceService(db_session)

    user_id = user.id
    await svc.revoke_all_for_user(user=user, reason="email_change")
    await db_session.flush()
    db_session.expunge_all()
    await db_session.commit()

    audit_rows = await _query_revoke_all_audit_rows(
        audit_session_maker, target_user_id=user_id
    )
    assert len(audit_rows) >= 1
    detail = audit_rows[0]

    assert "user_id" in detail, "detail must contain user_id"
    assert "target_user_id" in detail, "detail must contain target_user_id"
    assert "revoked_count" in detail, "detail must contain revoked_count"
    assert "reason" in detail, "detail must contain reason"

    assert detail["target_user_id"] == str(user.id)
    assert detail["user_id"] == str(user.id)
    assert detail["reason"] == "email_change"
    assert isinstance(detail["revoked_count"], int)


async def test_revoke_all_with_explicit_actor_user_id(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """actor_user_id param overrides the default (user.id)."""
    target = await _create_user(db_session, suffix="target-actor")
    operator = await _create_user(db_session, suffix="operator-actor")
    svc = TrustedDeviceService(db_session)

    target_id = target.id
    await svc.revoke_all_for_user(
        user=target,
        reason="password_reset",
        actor_user_id=operator.id,
    )
    await db_session.flush()
    db_session.expunge_all()
    await db_session.commit()

    audit_rows = await _query_revoke_all_audit_rows(
        audit_session_maker, target_user_id=target_id
    )
    assert len(audit_rows) == 1
    detail = audit_rows[0]
    assert detail["target_user_id"] == str(target.id)
    assert detail["user_id"] == str(target.id), "user_id should still be the target"
    # The actor_user_id_hash column is hashed so we can't directly assert operator.id,
    # but the detail should reflect the target correctly.
    assert detail["reason"] == "password_reset"


# ---------------------------------------------------------------------------
# Tests — reason allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", sorted(REVOKE_ALL_REASONS))
async def test_revoke_all_valid_reasons_do_not_raise(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
    reason: str,
) -> None:
    """Every reason in REVOKE_ALL_REASONS is accepted without raising."""
    user = await _create_user(db_session, suffix=f"valid-{reason}")
    svc = TrustedDeviceService(db_session)

    # Must not raise
    await svc.revoke_all_for_user(user=user, reason=reason)
    await db_session.flush()
    db_session.expunge_all()
    await db_session.commit()


async def test_revoke_all_unknown_reason_raises_value_error(
    db_session: AsyncSession,
) -> None:
    """An unknown reason string raises ValueError immediately."""
    user = await _create_user(db_session, suffix="bad-reason")
    svc = TrustedDeviceService(db_session)

    with pytest.raises(ValueError, match="unknown revoke_all_for_user reason"):
        await svc.revoke_all_for_user(user=user, reason="not_a_valid_reason")


async def test_revoke_all_legacy_password_changed_raises_value_error(
    db_session: AsyncSession,
) -> None:
    """The legacy 'password_changed' reason (not in allowlist) raises ValueError."""
    user = await _create_user(db_session, suffix="legacy-reason")
    svc = TrustedDeviceService(db_session)

    with pytest.raises(ValueError):
        await svc.revoke_all_for_user(user=user, reason="password_changed")


async def test_revoke_all_none_reason_raises_value_error(
    db_session: AsyncSession,
) -> None:
    """reason=None raises ValueError — the allowlist does not include None."""
    user = await _create_user(db_session, suffix="none-reason")
    svc = TrustedDeviceService(db_session)

    with pytest.raises((ValueError, TypeError)):
        # Type annotation says str but test the runtime guard
        await svc.revoke_all_for_user(user=user, reason=None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests — zero-device idempotency
# ---------------------------------------------------------------------------


async def test_revoke_all_no_devices_emits_audit_row(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Revoking a user with no active devices still emits one audit row."""
    user = await _create_user(db_session, suffix="no-devices")
    svc = TrustedDeviceService(db_session)

    user_id = user.id
    count = await svc.revoke_all_for_user(user=user, reason="user_deleted")
    await db_session.flush()
    db_session.expunge_all()
    await db_session.commit()

    assert count == 0

    audit_rows = await _query_revoke_all_audit_rows(
        audit_session_maker, target_user_id=user_id
    )
    assert len(audit_rows) == 1, "must emit audit row even when revoked_count=0"
    assert audit_rows[0]["revoked_count"] == 0
    assert audit_rows[0]["reason"] == "user_deleted"
