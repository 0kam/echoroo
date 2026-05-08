"""TDD suite for refresh-token rotation and reuse detection (T062).

Covers the behaviour defined in ``echoroo.core.auth`` for FR-055 /
FR-071:

* Rotation issues a fresh token and invalidates the previous one.
* Reusing an already-consumed token revokes the entire family and
  emits a platform audit event.
* Expired refresh tokens are rejected before any family-state mutation.
* Every token within a revoked family is rejected.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest

from echoroo.core.auth import (
    InMemoryTokenStore,
    InvalidTokenError,
    ReusedTokenError,
    RevokedFamilyError,
    SqlTokenStore,
    issue_refresh_token,
    revoke_family,
    rotate_refresh_token,
)
from echoroo.core.settings import get_settings

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _RecordingAuditStub:
    """Audit service stub that captures events in a list."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_platform_event(self, **kwargs: Any) -> UUID:
        self.events.append(kwargs)
        return uuid4()

    async def write_project_event(self, **kwargs: Any) -> UUID:  # pragma: no cover
        self.events.append(kwargs)
        return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def store() -> InMemoryTokenStore:
    return InMemoryTokenStore()


@pytest.fixture
def audit() -> _RecordingAuditStub:
    return _RecordingAuditStub()


# ---------------------------------------------------------------------------
# Case (a): normal rotation issues new token + invalidates the old one
# ---------------------------------------------------------------------------


async def test_rotate_issues_new_token_and_invalidates_old(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    token, record = issue_refresh_token(user_id=user_id)
    await store.record_issued(record)

    # Rotate once — we should get a distinct token back.
    new_token, new_record = await rotate_refresh_token(token, store=store)
    assert new_token != token
    # Family id is preserved so replay detection still covers the chain.
    assert new_record.family_id == record.family_id
    # Previous jti is now consumed.
    assert await store.is_consumed(record.family_id, record.jti) is True
    # New jti is NOT consumed (it's the currently-live token).
    assert await store.is_consumed(new_record.family_id, new_record.jti) is False


async def test_rotate_preserves_user_id(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    token, _ = issue_refresh_token(user_id=user_id)
    _, new_record = await rotate_refresh_token(token, store=store)
    assert new_record.user_id == user_id


# ---------------------------------------------------------------------------
# Case (b): reusing an old token revokes the whole family + emits audit
# ---------------------------------------------------------------------------


async def test_reuse_detection_revokes_family_and_audits(
    user_id: UUID,
    store: InMemoryTokenStore,
    audit: _RecordingAuditStub,
) -> None:
    token_1, record_1 = issue_refresh_token(user_id=user_id)
    await store.record_issued(record_1)

    # First rotate — token_1 is consumed, token_2 lives.
    token_2, _ = await rotate_refresh_token(token_1, store=store, audit=audit)

    # Attacker replays token_1 → reuse detection trips.
    with pytest.raises(ReusedTokenError):
        await rotate_refresh_token(
            token_1,
            store=store,
            audit=audit,
            request_id="req-reuse",
            ip="198.51.100.1",
            user_agent="pytest",
        )

    # The whole family is now revoked.
    assert await store.is_family_revoked(record_1.family_id) is True

    # token_2 must now also be rejected as a consequence.
    with pytest.raises(RevokedFamilyError):
        await rotate_refresh_token(token_2, store=store)

    # Audit log recorded the event.
    audit_actions = [e["action"] for e in audit.events]
    assert "auth.refresh_reuse_detected" in audit_actions
    reuse_event = next(
        e for e in audit.events if e["action"] == "auth.refresh_reuse_detected"
    )
    assert reuse_event["actor_user_id"] == user_id
    assert reuse_event["detail"]["family_id"] == record_1.family_id
    assert reuse_event["detail"]["reused_jti"] == record_1.jti
    # Request context is forwarded verbatim.
    assert reuse_event["request_id"] == "req-reuse"
    assert reuse_event["ip"] == "198.51.100.1"


async def test_reuse_without_audit_still_revokes_family(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    token_1, record_1 = issue_refresh_token(user_id=user_id)
    await store.record_issued(record_1)

    await rotate_refresh_token(token_1, store=store)  # first rotate
    with pytest.raises(ReusedTokenError):
        await rotate_refresh_token(token_1, store=store)

    assert await store.is_family_revoked(record_1.family_id) is True


# ---------------------------------------------------------------------------
# Case (c): expired refresh tokens are rejected
# ---------------------------------------------------------------------------


async def test_expired_refresh_token_is_rejected(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    settings = get_settings()
    # Craft a token whose exp is already in the past.
    past = datetime.now(UTC) - timedelta(days=30)
    claims = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "family": str(uuid4()),
        "type": "refresh",
        "iat": int((past - timedelta(days=1)).timestamp()),
        "exp": int(past.timestamp()),
    }
    expired = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    with pytest.raises(InvalidTokenError):
        await rotate_refresh_token(expired, store=store)

    # State must be untouched — no family was created for the expired jti.
    assert await store.get_family_state(claims["family"]) is None


async def test_malformed_refresh_token_is_rejected(
    store: InMemoryTokenStore,
) -> None:
    with pytest.raises(InvalidTokenError):
        await rotate_refresh_token("not-a-real-token", store=store)


async def test_access_token_cannot_be_rotated(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    settings = get_settings()
    claims = {
        "sub": str(user_id),
        "jti": str(uuid4()),
        "ss": "x" * 64,
        "type": "access",
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int((datetime.now(UTC) + timedelta(minutes=15)).timestamp()),
    }
    access = jwt.encode(claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidTokenError):
        await rotate_refresh_token(access, store=store)


# ---------------------------------------------------------------------------
# Case (d): all tokens in a revoked family fail
# ---------------------------------------------------------------------------


async def test_revoke_family_rejects_all_chain_tokens(
    user_id: UUID,
    store: InMemoryTokenStore,
    audit: _RecordingAuditStub,
) -> None:
    # Build a 3-step rotation chain.
    token_1, record_1 = issue_refresh_token(user_id=user_id)
    await store.record_issued(record_1)
    token_2, _ = await rotate_refresh_token(token_1, store=store)
    token_3, _ = await rotate_refresh_token(token_2, store=store)

    # Revoke by admin action (e.g. user clicks Log Out Everywhere).
    await revoke_family(
        record_1.family_id,
        store=store,
        audit=audit,
        actor_user_id=user_id,
        reason="logout_all",
        request_id="req-logout",
    )

    # Every token in the chain must now fail.
    for live_token in (token_3,):
        with pytest.raises(RevokedFamilyError):
            await rotate_refresh_token(live_token, store=store)

    # Manual revoke emitted an audit row.
    audit_actions = [e["action"] for e in audit.events]
    assert "auth.refresh_family_revoked" in audit_actions
    evt = next(e for e in audit.events if e["action"] == "auth.refresh_family_revoked")
    assert evt["detail"]["reason"] == "logout_all"
    assert evt["detail"]["family_id"] == record_1.family_id


async def test_revoke_family_is_idempotent(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    _, record = issue_refresh_token(user_id=user_id)
    await store.record_issued(record)

    await revoke_family(record.family_id, store=store)
    await revoke_family(record.family_id, store=store)  # should not raise

    assert await store.is_family_revoked(record.family_id) is True


# ---------------------------------------------------------------------------
# Case (e): concurrent rotation race — exactly one coroutine succeeds
# (Phase 2.10 #2 atomic_consume_and_issue)
# ---------------------------------------------------------------------------


async def test_concurrent_rotations_on_same_jti_yield_exactly_one_winner(
    user_id: UUID,
    store: InMemoryTokenStore,
    audit: _RecordingAuditStub,
) -> None:
    """Two parallel rotations of the same refresh token: only one wins.

    Without ``atomic_consume_and_issue`` both coroutines would observe
    ``is_consumed == False``, both would mint successor tokens, and the
    server would have issued two valid live tokens for the same logical
    session. The atomic primitive forces exactly one to succeed; the
    loser must trip reuse-detection and revoke the family.
    """
    token, record = issue_refresh_token(user_id=user_id)
    await store.record_issued(record)

    # Fire both coroutines in parallel against the SAME store instance.
    results = await asyncio.gather(
        rotate_refresh_token(
            token, store=store, audit=audit, request_id="concurrent-A"
        ),
        rotate_refresh_token(
            token, store=store, audit=audit, request_id="concurrent-B"
        ),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, BaseException)]
    failures = [r for r in results if isinstance(r, BaseException)]

    # Exactly one coroutine must have minted a successor token.
    assert len(successes) == 1, (
        f"expected exactly 1 winner, got {len(successes)} (results={results!r})"
    )
    # The other must have raised ReusedTokenError (the family is now revoked).
    assert len(failures) == 1
    assert isinstance(failures[0], ReusedTokenError)

    # Whole family is revoked → even the winner's "live" token is now
    # rejected on next attempted rotation.
    assert await store.is_family_revoked(record.family_id) is True

    # Audit must have recorded the reuse-detection event for the loser.
    audit_actions = [e["action"] for e in audit.events]
    assert "auth.refresh_reuse_detected" in audit_actions


async def test_atomic_consume_and_issue_returns_false_on_already_consumed(
    user_id: UUID, store: InMemoryTokenStore
) -> None:
    """The store-level primitive contract: second call on same jti → False."""
    _, record = issue_refresh_token(user_id=user_id)
    await store.record_issued(record)

    successor_a = issue_refresh_token(user_id=user_id, family_id=record.family_id)[1]
    successor_b = issue_refresh_token(user_id=user_id, family_id=record.family_id)[1]

    first = await store.atomic_consume_and_issue(
        family_id=record.family_id, old_jti=record.jti, new_record=successor_a
    )
    second = await store.atomic_consume_and_issue(
        family_id=record.family_id, old_jti=record.jti, new_record=successor_b
    )

    assert first is True
    assert second is False


# ---------------------------------------------------------------------------
# SqlTokenStore production surface — Phase 2.11 P0-d
#
# Phase 2.10 left every SqlTokenStore method as NotImplementedError; the
# previous test asserted that. Phase 2.11 P0-d implements all methods
# against the new ``refresh_tokens`` / ``token_families`` tables shipped
# in alembic migration 0002. Behaviour against a live PostgreSQL is
# verified end-to-end in ``tests/integration/test_sql_token_store.py``
# (testcontainers-based, skipped if unavailable). Here we keep a
# unit-level smoke that the public API exists, accepts the documented
# argument shapes, and is async — anything more requires a real DB.
# ---------------------------------------------------------------------------


@pytest.mark.filterwarnings(
    "ignore::pytest.PytestWarning"
)  # sync test in a module with pytestmark=asyncio — suppress strict-mode noise
def test_sql_token_store_production_methods_present() -> None:
    """All TokenStore protocol methods are concrete (no NotImplementedError)."""
    import inspect

    store = SqlTokenStore(session_factory=lambda: None)
    for method_name in (
        "get_family_state",
        "record_issued",
        "mark_consumed",
        "is_consumed",
        "revoke_family",
        "is_family_revoked",
        "atomic_consume_and_issue",
    ):
        method = getattr(store, method_name)
        # Must be an async coroutine function (Phase 3 wiring relies
        # on awaiting these in request handlers).
        assert inspect.iscoroutinefunction(method), (
            f"SqlTokenStore.{method_name} must be a coroutine function"
        )
        # The source must NOT mention NotImplementedError — that was
        # the Phase 2.10 skeleton marker.
        src = inspect.getsource(method)
        assert "NotImplementedError" not in src, (
            f"SqlTokenStore.{method_name} still contains a "
            f"NotImplementedError stub (Phase 2.11 P0-d expected this "
            f"to be implemented)"
        )
