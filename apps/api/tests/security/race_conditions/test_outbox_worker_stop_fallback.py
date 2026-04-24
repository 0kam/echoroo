"""Worker-stoppage fallback to ``enforce_at_auth_time`` (T083, FR-076d, SC-021).

Background
----------
When the outbox worker pool stops draining the queue (deployment outage,
broker failure, all 4 worker pods crashing), permission revocations
queued via the outbox would otherwise be silently delayed. The spec
(FR-076d) mandates that, after 5 minutes of stalled rows,
:class:`OutboxStallDetector` reports the system as stalled so the auth
middleware can flip its global ``enforce_at_auth_time`` flag and bypass
permission caches in favour of synchronous recomputation.

This test exercises the contract of ``count_pending_older_than`` and
``OutboxStallDetector`` against a fully-mocked AsyncSession, asserting:

1. The SQL emitted by ``count_pending_older_than`` filters by
   ``status='pending'`` AND ``created_at < :threshold``.
2. ``OutboxStallDetector.is_stalled`` returns True iff the count is > 0.
3. The ``should_enforce_at_auth_time`` helper is wired to the same
   detector logic, so middleware can call either name.
4. The default stall threshold is 5 minutes (FR-076d).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from echoroo.services.outbox_service import (
    STALL_THRESHOLD,
    STATUS_PENDING,
    OutboxStallDetector,
    count_pending_older_than,
)


class _FakeResult:
    def __init__(self, count: int) -> None:
        self._count = count

    def first(self) -> tuple[int, ...]:
        return (self._count,)


def _make_session(count_response: int) -> tuple[MagicMock, list[tuple[str, dict[str, Any]]]]:
    """Build an AsyncSession mock that returns ``count_response`` for COUNT(*)."""
    calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        calls.append((str(stmt), params or {}))
        return _FakeResult(count_response)

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    return session, calls


# ---------------------------------------------------------------------------
# count_pending_older_than: SQL contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_pending_older_than_filters_status_and_age() -> None:
    """The query must filter by ``status='pending'`` and ``created_at < :threshold``."""
    session, calls = _make_session(count_response=0)

    await count_pending_older_than(session, timedelta(minutes=5))

    assert len(calls) == 1
    sql, params = calls[0]
    sql_lower = sql.lower()

    # Body of the query.
    assert "from outbox_events" in sql_lower
    assert "status = :pending" in sql_lower
    assert "created_at < :threshold" in sql_lower
    assert params["pending"] == STATUS_PENDING
    # Threshold parameter is bound and represents a UTC datetime.
    assert "threshold" in params


@pytest.mark.asyncio
async def test_count_pending_older_than_returns_count_value() -> None:
    """The helper must propagate the integer COUNT(*) result."""
    session, _calls = _make_session(count_response=42)
    result = await count_pending_older_than(session, timedelta(minutes=5))
    assert result == 42


# ---------------------------------------------------------------------------
# OutboxStallDetector behaviour
# ---------------------------------------------------------------------------


def test_default_stall_threshold_is_five_minutes() -> None:
    """FR-076d fixes the worker-stoppage threshold at 5 minutes."""
    five_minutes = timedelta(minutes=5)
    assert five_minutes == STALL_THRESHOLD
    detector = OutboxStallDetector()
    assert detector.threshold == five_minutes


@pytest.mark.asyncio
async def test_is_stalled_returns_true_when_pending_rows_are_old() -> None:
    """A non-zero count of pending rows older than 5 minutes -> stalled."""
    session, _calls = _make_session(count_response=3)
    detector = OutboxStallDetector(threshold=timedelta(minutes=5))

    assert await detector.is_stalled(session) is True


@pytest.mark.asyncio
async def test_is_stalled_returns_false_when_queue_is_drained() -> None:
    """Zero stalled rows -> healthy queue, no fallback needed."""
    session, _calls = _make_session(count_response=0)
    detector = OutboxStallDetector(threshold=timedelta(minutes=5))

    assert await detector.is_stalled(session) is False


@pytest.mark.asyncio
async def test_should_enforce_at_auth_time_aliases_is_stalled() -> None:
    """Middleware-friendly alias must agree with ``is_stalled`` for both arms."""
    # Stalled case
    session_stall, _ = _make_session(count_response=7)
    detector = OutboxStallDetector()
    assert await detector.should_enforce_at_auth_time(session_stall) is True

    # Healthy case
    session_ok, _ = _make_session(count_response=0)
    assert await detector.should_enforce_at_auth_time(session_ok) is False


@pytest.mark.asyncio
async def test_custom_threshold_is_propagated_to_query() -> None:
    """A non-default threshold must reach the SQL bound parameter."""
    session, calls = _make_session(count_response=0)
    detector = OutboxStallDetector(threshold=timedelta(minutes=10))

    await detector.is_stalled(session)
    assert len(calls) == 1
    _sql, params = calls[0]
    # The threshold is converted to an absolute datetime; we cannot pin
    # the exact value without freezing the clock, but its delta from
    # "now" must be in the right ballpark (10 minutes ± 5 seconds).
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    delta = now - params["threshold"]
    assert timedelta(minutes=10) - timedelta(seconds=5) <= delta <= timedelta(minutes=10) + timedelta(seconds=5)
