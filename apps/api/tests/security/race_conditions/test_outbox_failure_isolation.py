"""Outbox failure-state isolation + stale-processing reaper (Phase 2.10 #1).

Two related guarantees tested here:

1. ``_drain_batch`` records a failed row's failure-state UPDATE in a
   *fresh* AsyncSession after the work transaction has rolled back.
   Inlining ``mark_failed`` inside the same TX would have its UPDATE
   wiped by the rollback, leaving the row stuck in ``processing``
   forever.

2. ``requeue_stuck_processing`` resets rows that were claimed but never
   marked done/failed (worker crash) back to ``pending`` so they
   become eligible for the next claim cycle.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.services import outbox_service
from echoroo.services.outbox_service import (
    STATUS_PENDING,
    STATUS_PROCESSING,
    requeue_stuck_processing,
)
from echoroo.workers import outbox_processor
from echoroo.workers.outbox_processor import (
    OUTBOX_HANDLERS,
    _drain_batch,
    register_outbox_handler,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Result:
    """Minimal mock of SQLAlchemy ``Result``."""

    def __init__(
        self,
        *,
        row: tuple[Any, ...] | None = None,
        rows: list[dict[str, Any]] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def first(self) -> tuple[Any, ...] | None:
        return self._row

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _RecordingSession:
    """AsyncSession stand-in that records every executed statement."""

    def __init__(self, claim_rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self.rollbacks = 0
        self._claim_rows = claim_rows or []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(stmt).lower()
        self.calls.append((sql, params or {}))
        # SELECT ... FOR UPDATE SKIP LOCKED → rows for the claim phase.
        if "select id, event_type" in sql and "skip locked" in sql:
            return _Result(rows=self._claim_rows)
        # UPDATE outbox_events SET status = :processing → rowcount irrelevant.
        if "update outbox_events" in sql and "status = :processing" in sql:
            return _Result(rowcount=len(self._claim_rows))
        # UPDATE outbox_events SET status = :pending (reaper / failure paths).
        if "update outbox_events" in sql:
            return _Result(rowcount=1)
        # COUNT(*) → return 0 by default (no stalls).
        if "count(*)" in sql:
            return _Result(row=(0,))
        return _Result()

    async def __aenter__(self) -> _RecordingSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def begin(self) -> Any:
        @asynccontextmanager
        async def _cm() -> Any:
            try:
                yield self
                self.commits += 1
            except Exception:
                self.rollbacks += 1
                raise

        return _cm()


def _session_factory(sessions: list[_RecordingSession]) -> Any:
    """Return a callable that yields the next prepared session each call."""
    iterator = iter(sessions)

    def factory() -> _RecordingSession:
        return next(iterator)

    return factory


# ---------------------------------------------------------------------------
# requeue_stuck_processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requeue_stuck_processing_emits_correct_update() -> None:
    """The reaper must SET status=pending WHERE status=processing AND aged."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rowcount=3))

    requeued = await requeue_stuck_processing(session, timedelta(minutes=10))

    assert requeued == 3
    assert session.execute.await_count == 1
    sql = str(session.execute.await_args.args[0]).lower()
    assert "update outbox_events" in sql
    assert "status = :pending" in sql
    assert "where status = :processing" in sql
    assert "next_retry_at < :threshold" in sql
    assert "retry_count = retry_count + 1" in sql

    params = session.execute.await_args.args[1]
    assert params["pending"] == STATUS_PENDING
    assert params["processing"] == STATUS_PROCESSING
    assert isinstance(params["threshold"], datetime)
    # threshold must be in the past.
    assert params["threshold"] <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_requeue_stuck_processing_returns_zero_when_nothing_stuck() -> None:
    session = MagicMock()
    session.execute = AsyncMock(return_value=_Result(rowcount=0))

    requeued = await requeue_stuck_processing(session, timedelta(minutes=10))

    assert requeued == 0


def test_requeue_stuck_processing_is_exported() -> None:
    """Ensure the helper is importable from the module's public surface."""
    assert hasattr(outbox_service, "requeue_stuck_processing")
    assert "requeue_stuck_processing" in outbox_service.__all__


# ---------------------------------------------------------------------------
# _drain_batch: failure UPDATE survives the work-session rollback
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_handler_registry() -> Any:
    snapshot = dict(OUTBOX_HANDLERS)
    yield
    OUTBOX_HANDLERS.clear()
    OUTBOX_HANDLERS.update(snapshot)


@pytest.mark.asyncio
async def test_drain_batch_records_failure_in_fresh_transaction() -> None:
    """Handler raise → work TX rolls back → failure TX commits separately.

    The fresh failure session must commit (rowcount > 0 against
    outbox_events) and the work session must have rolled back without
    hosting the failure-state update.
    """
    row_id = uuid4()
    claim_rows = [
        {
            "id": row_id,
            "event_type": "test_failure_isolation",
            "payload": {},
            "retry_count": 0,
            "idempotency_key": "k:1",
        }
    ]

    @register_outbox_handler("test_failure_isolation")
    async def handler(_session: Any, _payload: dict[str, Any]) -> None:
        raise RuntimeError("simulated handler crash")

    reap_session = _RecordingSession()
    claim_session = _RecordingSession(claim_rows=claim_rows)
    work_session = _RecordingSession()
    failure_session = _RecordingSession()

    factory = _session_factory(
        [reap_session, claim_session, work_session, failure_session]
    )

    processed = await _drain_batch(factory, batch_size=10, worker_id="test:1")

    # The failed row does NOT count as processed.
    assert processed == 0

    # Work session: opened, handler raised → rolled back, no commit.
    assert work_session.rollbacks == 1
    assert work_session.commits == 0

    # Failure session: opened independently, committed.
    assert failure_session.commits == 1
    assert failure_session.rollbacks == 0
    failure_sql = " ".join(sql for sql, _ in failure_session.calls)
    assert "update outbox_events" in failure_sql
    # mark_failed sets either status=pending (retry) or status=dead_letter.
    assert "status = :pending" in failure_sql or "status = :dead_letter" in failure_sql

    # Reap session: committed (no stuck rows present, but the call must
    # have happened so future workers get the safety net).
    assert reap_session.commits == 1


@pytest.mark.asyncio
async def test_drain_batch_reaps_stuck_rows_before_claiming() -> None:
    """``_drain_batch`` must run the reaper BEFORE the claim phase."""
    reap_session = _RecordingSession()
    claim_session = _RecordingSession(claim_rows=[])

    factory = _session_factory([reap_session, claim_session])

    processed = await _drain_batch(factory, batch_size=10, worker_id="test:reap")
    assert processed == 0

    # Reap session must have executed the stale-processing UPDATE.
    assert reap_session.commits == 1
    reap_sql = " ".join(sql for sql, _ in reap_session.calls)
    assert "update outbox_events" in reap_sql
    assert "where status = :processing" in reap_sql


def test_stale_processing_reset_age_is_sane() -> None:
    """Sanity bound on the configured reaper threshold."""
    age = outbox_processor.STALE_PROCESSING_RESET_AGE
    assert isinstance(age, timedelta)
    # Must be longer than the documented p99 SLO (60s) so live work is
    # not yanked, but not so long it leaves the queue stalled all day.
    assert age >= timedelta(minutes=1)
    assert age <= timedelta(hours=1)
