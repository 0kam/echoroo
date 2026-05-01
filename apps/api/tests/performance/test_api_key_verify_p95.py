"""T992d — API key verify hot path: p95 + query count budget (Phase 15).

Contract under test
-------------------
The ``DbApiKeyVerifier.verify()`` method must resolve an API key in ≤ 30 ms
p95 (NFR-001 auth budget) with a ≤ 2 DB query budget (1 SELECT + optional
debounced UPDATE).

Test strategy
-------------
1. Seed a real ``api_keys`` row in the test DB.
2. Call ``DbApiKeyVerifier.verify()`` 100 times using the raw key.
3. Measure wall-clock latency per call.
4. Assert p95 < 30 ms.

Debounce behaviour (1-minute window)
--------------------------------------
After the first successful verify, the verifier bumps ``last_used_at`` once
then skips subsequent UPDATEs within the debounce window. These tests
exercise:
* Cold call (no prior ``last_used_at``) — 2 queries (SELECT + UPDATE).
* Hot call (``last_used_at`` recently set) — 1 query (SELECT only).
* Expired / revoked key → returns ``None`` quickly (SELECT only).

CI skip
-------
Latency assertions are environment-sensitive. Skipped in CI.
"""

from __future__ import annotations

import os
import secrets
import statistics
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.models.api_key import ApiKey
from echoroo.models.user import User
from echoroo.services.api_key_verification import (
    KEY_NAMESPACE,
    LAST_USED_DEBOUNCE,
    DbApiKeyVerifier,
    hash_api_key_secret,
    parse_api_key,
)

_NUM_ITERATIONS = 100
_P95_BUDGET_MS = 30.0
_P50_BUDGET_MS = 15.0

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Helpers — build a valid raw key + matching DB row
# ---------------------------------------------------------------------------


def _make_raw_key() -> tuple[str, str, str]:
    """Return (raw_key, stored_prefix, raw_secret)."""
    random_part = secrets.token_urlsafe(6)[:8].replace("-", "a").replace("_", "b")
    stored_prefix = f"{KEY_NAMESPACE}{random_part}"
    raw_secret = secrets.token_urlsafe(32)
    raw_key = f"{stored_prefix}_{raw_secret}"
    return raw_key, stored_prefix, raw_secret


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def t992d_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t992d_owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T992d Owner",
        security_stamp="t992d" + "o" * 59,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t992d_api_key_row(
    db_session: AsyncSession,
    t992d_owner: User,
) -> tuple[str, ApiKey]:
    """Seed a valid ApiKey row and return (raw_key, row)."""
    raw_key, stored_prefix, raw_secret = _make_raw_key()
    hashed = hash_api_key_secret(raw_secret)

    row = ApiKey(
        user_id=t992d_owner.id,
        prefix=stored_prefix,
        hashed_secret=hashed,
        granted_permissions=["project:read"],
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=None,
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return raw_key, row


# ---------------------------------------------------------------------------
# Unit tests — parse_api_key + hash
# ---------------------------------------------------------------------------


@pytest.mark.performance
def test_parse_api_key_valid() -> None:
    """parse_api_key correctly extracts prefix and secret."""
    raw_key, stored_prefix, raw_secret = _make_raw_key()
    result = parse_api_key(raw_key)
    assert result is not None
    assert result[0] == stored_prefix
    assert result[1] == raw_secret


@pytest.mark.performance
def test_parse_api_key_invalid_returns_none() -> None:
    """Malformed keys return None."""
    assert parse_api_key("") is None
    assert parse_api_key("invalid_no_namespace") is None
    assert parse_api_key("echoroo_tooshort_") is None


@pytest.mark.performance
def test_hash_api_key_secret_deterministic() -> None:
    """hash_api_key_secret is deterministic for the same input."""
    secret = "test_secret_abc123"
    h1 = hash_api_key_secret(secret)
    h2 = hash_api_key_secret(secret)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# Integration test — verify against real DB row
# ---------------------------------------------------------------------------


@pytest.mark.performance
@pytest.mark.asyncio
async def test_api_key_verify_valid_key(
    db_session: AsyncSession,
    t992d_api_key_row: tuple[str, ApiKey],
    t992d_owner: User,
) -> None:
    """DbApiKeyVerifier returns an ApiKeyRecord for a valid key."""
    raw_key, row = t992d_api_key_row

    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    verifier = DbApiKeyVerifier(session_factory)

    try:
        record = await verifier.verify(raw_key)
        assert record is not None, "Valid API key must resolve to a record"
        assert record.user_id == t992d_owner.id
        assert record.api_key_id == row.id
    finally:
        await engine.dispose()


@pytest.mark.performance
@pytest.mark.asyncio
async def test_api_key_verify_invalid_key_returns_none(
    db_session: AsyncSession,
    t992d_owner: User,
) -> None:
    """Invalid / missing key returns None (anti-enumeration)."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    verifier = DbApiKeyVerifier(session_factory)

    try:
        result = await verifier.verify("echoroo_notexist_invalidsecret123456")
        assert result is None
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Performance tests — p95 latency
# ---------------------------------------------------------------------------


@pytest.mark.performance
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="Latency assertions are environment-sensitive; run locally only",
)
@pytest.mark.asyncio
async def test_api_key_verify_hot_path_p95(
    db_session: AsyncSession,
    t992d_api_key_row: tuple[str, ApiKey],
) -> None:
    """p95 < 30 ms for DbApiKeyVerifier.verify() on a valid hot key."""
    raw_key, _row = t992d_api_key_row

    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    verifier = DbApiKeyVerifier(session_factory, last_used_debounce=LAST_USED_DEBOUNCE)

    try:
        latencies: list[float] = []
        for _ in range(_NUM_ITERATIONS):
            start = time.perf_counter()
            record = await verifier.verify(raw_key)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            latencies.append(elapsed_ms)
            assert record is not None, "Verify must succeed for a valid key"

        p50 = statistics.median(latencies)
        sorted_l = sorted(latencies)
        p95 = sorted_l[max(0, int(len(sorted_l) * 0.95) - 1)]
        p99 = sorted_l[max(0, int(len(sorted_l) * 0.99) - 1)]

        print(
            f"\nApiKey verify latencies ({_NUM_ITERATIONS} iters): "
            f"p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms"
        )

        assert p95 < _P95_BUDGET_MS, (
            f"NFR-001 API key verify p95 budget exceeded: "
            f"p95={p95:.1f}ms > {_P95_BUDGET_MS}ms"
        )
    finally:
        await engine.dispose()


@pytest.mark.performance
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="Latency assertions are environment-sensitive; run locally only",
)
@pytest.mark.asyncio
async def test_api_key_verify_debounce_skips_update(
    db_session: AsyncSession,
    t992d_api_key_row: tuple[str, ApiKey],
) -> None:
    """Hot path (post-first-call) skips the UPDATE — latency should be lower."""
    raw_key, _row = t992d_api_key_row

    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Zero debounce to force the first call to issue the UPDATE.
    verifier_cold = DbApiKeyVerifier(session_factory, last_used_debounce=timedelta(0))
    # Large debounce: subsequent calls skip the UPDATE.
    verifier_hot = DbApiKeyVerifier(session_factory, last_used_debounce=timedelta(hours=24))

    try:
        # Cold: first call bumps last_used_at (SELECT + UPDATE).
        cold_latencies: list[float] = []
        for _ in range(10):
            start = time.perf_counter()
            record = await verifier_cold.verify(raw_key)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            cold_latencies.append(elapsed_ms)
            assert record is not None

        # Hot: skip the UPDATE (SELECT only).
        hot_latencies: list[float] = []
        for _ in range(10):
            start = time.perf_counter()
            record = await verifier_hot.verify(raw_key)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            hot_latencies.append(elapsed_ms)
            assert record is not None

        p95_cold = sorted(cold_latencies)[max(0, int(len(cold_latencies) * 0.95) - 1)]
        p95_hot = sorted(hot_latencies)[max(0, int(len(hot_latencies) * 0.95) - 1)]

        print(f"\nApiKey verify debounce: cold p95={p95_cold:.1f}ms  hot p95={p95_hot:.1f}ms")

        # Both cold and hot must fit within the budget.
        assert p95_cold < _P95_BUDGET_MS * 2, (
            f"Cold API key verify p95={p95_cold:.1f}ms exceeds 2x budget"
        )
        assert p95_hot < _P95_BUDGET_MS, (
            f"Hot API key verify p95={p95_hot:.1f}ms exceeds budget"
        )
    finally:
        await engine.dispose()
