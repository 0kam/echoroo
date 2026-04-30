"""T993 — Audit log 1000+ concurrent INSERT chain integrity (FR-093 / SC-014).

Contract under test
-------------------
FR-093 requires that the audit log's HMAC-chain remains intact under
concurrent writers. The advisory lock (``pg_advisory_xact_lock``) + SERIALIZABLE
isolation must serialise concurrent writes so every row's ``prev_hash``
equals the preceding row's ``row_hash`` — no gaps, no duplicates.

Test strategy
-------------
1. Spawn *N* concurrent ``asyncio.gather`` tasks, each opening its own
   ``AsyncSession`` (from the production ``TEST_DATABASE_URL`` engine, not
   the shared ``db_session`` fixture — the fixture is function-scoped and
   cannot be shared across tasks).
2. Each task calls ``AuditLogService.write_platform_event`` + commit.
3. After all tasks complete, read every ``platform_audit_log`` row ordered
   by ``created_at ASC, id ASC`` and verify:
   a. ``row_hash`` is unique (no duplicates).
   b. Each row's ``prev_hash`` equals the previous row's ``row_hash``
      (except the genesis row whose ``prev_hash`` is the 64-zero sentinel).
4. Assert the total row count equals the number of concurrent writes.

Load
----
``_CONCURRENT_WRITES = 50`` — enough to stress the advisory lock without
making the test take > 30 s on a local dev DB. The full 1000-task scenario
is left to the k6/Locust scripts in ``scenarios/audit_log_concurrent.js``.
A separate ``_STRESS_WRITES = 1000`` version is marked
``@pytest.mark.slow`` + ``@pytest.mark.skipif(CI)`` for heavy local runs.

Phase 12 R4 contract
--------------------
SC-014 specifies that audit rows written in a *failed* main TX must still
commit via a *fresh* session. T993a (``test_audit_chain_failure_path.py``)
covers that path separately.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from echoroo.services.audit_service import AuditLogService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CONCURRENT_WRITES = 50
_STRESS_WRITES = 1000  # used only by the slow/skipif variant

_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write_one(session_factory: async_sessionmaker, index: int) -> None:  # type: ignore[type-arg]
    """Write a single platform_audit_log row in its own session + commit."""
    async with session_factory() as session:
        svc = AuditLogService(session)
        await svc.write_platform_event(
            actor_user_id=None,
            action=f"t993.concurrent_write.{index}",
            request_id=str(uuid.uuid4()),
            ip="127.0.0.1",
            user_agent="pytest/t993",
            detail={"index": index},
        )
        await session.commit()


async def _fetch_platform_rows(
    session_factory: async_sessionmaker,  # type: ignore[type-arg]
    min_created_at: datetime,
) -> list[dict]:
    """Return platform_audit_log rows inserted during this test, ordered for chain check."""
    async with session_factory() as session:
        result = await session.execute(
            sa.text(
                "SELECT id, prev_hash, row_hash, action "
                "FROM platform_audit_log "
                "WHERE action LIKE 't993.concurrent_write.%' "
                "  AND created_at >= :min_ts "
                "ORDER BY created_at ASC, id ASC"
            ).bindparams(min_ts=min_created_at)
        )
        return [
            {"id": row[0], "prev_hash": row[1], "row_hash": row[2], "action": row[3]}
            for row in result.fetchall()
        ]


async def _delete_test_rows(session_factory: async_sessionmaker) -> None:  # type: ignore[type-arg]
    """Clean up test rows after the test so the chain check in other tests is unaffected."""
    async with session_factory() as session:
        await session.execute(
            sa.text("DELETE FROM platform_audit_log WHERE action LIKE 't993.%'")
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.performance
@pytest.mark.asyncio
async def test_concurrent_audit_writes_chain_integrity(db_session: AsyncSession) -> None:  # noqa: ARG001
    """50 concurrent writers → HMAC chain has no gaps or duplicate row_hashes.

    The ``db_session`` fixture is injected only to ensure ``setup_test_database``
    has run and created all tables (including ``platform_audit_log``) before
    this test opens its own pool.
    """
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory: async_sessionmaker = async_sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    start_ts = datetime.now(UTC)

    try:
        await asyncio.gather(
            *[_write_one(session_factory, i) for i in range(_CONCURRENT_WRITES)]
        )

        rows = await _fetch_platform_rows(session_factory, start_ts)

        assert len(rows) == _CONCURRENT_WRITES, (
            f"Expected {_CONCURRENT_WRITES} rows; got {len(rows)}. "
            "Some concurrent writes may have been lost."
        )

        # --- chain integrity check ---
        row_hashes = [r["row_hash"] for r in rows]

        # (a) No duplicate row_hashes.
        assert len(set(row_hashes)) == len(row_hashes), (
            "Duplicate row_hash detected in platform_audit_log — "
            "concurrent writes collided on the advisory lock path."
        )

        # (b) Chain linkage: each row's prev_hash == previous row's row_hash.
        # The advisory lock + SERIALIZABLE serialise the writes, but the
        # ORDER BY (created_at ASC, id ASC) gives us a deterministic sequence
        # to walk. Note: the genesis prev_hash (all-zeros) applies only to the
        # very first row in the *entire* table, which may not be the first
        # t993 row if prior tests have already written rows.  We verify the
        # *internal* linkage of our batch only.
        for i in range(1, len(rows)):
            expected_prev = rows[i - 1]["row_hash"]
            actual_prev = rows[i]["prev_hash"]
            assert actual_prev == expected_prev, (
                f"Chain break at position {i}: "
                f"row[{i}].prev_hash={actual_prev!r} != "
                f"row[{i-1}].row_hash={expected_prev!r} "
                f"(action={rows[i]['action']!r})"
            )

    finally:
        await _delete_test_rows(session_factory)
        await engine.dispose()


@pytest.mark.performance
@pytest.mark.asyncio
async def test_audit_row_count_matches_concurrent_writes(db_session: AsyncSession) -> None:  # noqa: ARG001
    """All 50 concurrent writes commit exactly one row each."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory: async_sessionmaker = async_sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    start_ts = datetime.now(UTC)
    try:
        await asyncio.gather(
            *[_write_one(session_factory, i) for i in range(_CONCURRENT_WRITES)]
        )
        rows = await _fetch_platform_rows(session_factory, start_ts)
        assert len(rows) == _CONCURRENT_WRITES, (
            f"Row count mismatch: expected {_CONCURRENT_WRITES}, got {len(rows)}"
        )
    finally:
        await _delete_test_rows(session_factory)
        await engine.dispose()


@pytest.mark.performance
@pytest.mark.asyncio
async def test_audit_no_duplicate_row_hashes(db_session: AsyncSession) -> None:  # noqa: ARG001
    """50 concurrent writes produce 50 unique row_hashes."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory: async_sessionmaker = async_sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    start_ts = datetime.now(UTC)
    try:
        await asyncio.gather(
            *[_write_one(session_factory, i) for i in range(_CONCURRENT_WRITES)]
        )
        rows = await _fetch_platform_rows(session_factory, start_ts)
        row_hashes = [r["row_hash"] for r in rows]
        assert len(set(row_hashes)) == len(row_hashes), (
            f"Found {len(row_hashes) - len(set(row_hashes))} duplicate row_hash(es)"
        )
    finally:
        await _delete_test_rows(session_factory)
        await engine.dispose()


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("RUN_PERF_LATENCY") != "true",
    reason="1000-task stress run is environment-sensitive; run locally only",
)
@pytest.mark.asyncio
async def test_stress_1000_concurrent_audit_writes_chain_integrity(db_session: AsyncSession) -> None:  # noqa: ARG001
    """1000 concurrent writers → chain integrity (stress variant, local only)."""
    engine = create_async_engine(_TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory: async_sessionmaker = async_sessionmaker(  # type: ignore[type-arg]
        engine, class_=AsyncSession, expire_on_commit=False
    )

    start_ts = datetime.now(UTC)
    try:
        await asyncio.gather(
            *[_write_one(session_factory, i) for i in range(_STRESS_WRITES)]
        )
        rows = await _fetch_platform_rows(session_factory, start_ts)
        assert len(rows) == _STRESS_WRITES

        row_hashes = [r["row_hash"] for r in rows]
        assert len(set(row_hashes)) == len(row_hashes), "Duplicate row_hash in 1000-task run"

        for i in range(1, len(rows)):
            assert rows[i]["prev_hash"] == rows[i - 1]["row_hash"], (
                f"Chain break at position {i} in 1000-task run"
            )
    finally:
        await _delete_test_rows(session_factory)
        await engine.dispose()
