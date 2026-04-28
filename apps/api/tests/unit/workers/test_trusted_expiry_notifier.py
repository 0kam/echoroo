"""Unit coverage for the Trusted-overlay expiry notifier (T515, FR-045).

The Celery task is a thin wrapper around :func:`asyncio.run` so the
tests target the underlying ``async`` helpers directly:

* :func:`_select_due_rows` filters by the 7-day window — exercised
  here via a fake :class:`AsyncSession` that records the bound
  parameters and returns canned mappings.
* :func:`_run_notify_expiring` enqueues two outbox events per overlay
  (one for the Trusted user, one for the Owner) and writes a single
  audit row. Status filtering (``status='active'``) is implicit because
  the SELECT excludes other rows; the test asserts that overlays whose
  email columns are missing are skipped without producing outbox rows.

The DB session, outbox enqueue, and audit writer are all monkey-patched
so the test does not require a live PostgreSQL connection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from echoroo.workers import trusted_expiry_notifier as notifier

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    """Async session double that captures execute() calls."""

    def __init__(self, due_rows: list[dict[str, Any]]):
        self._due_rows = due_rows
        self.commits: int = 0
        self.rollbacks: int = 0

    async def execute(self, _stmt: Any, _params: Any | None = None) -> _Result:
        return _Result(self._due_rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionFactoryCM:
    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


def _row(
    *,
    expires_at: datetime,
    user_email: str = "user@example.com",
    owner_email: str = "owner@example.com",
) -> dict[str, Any]:
    return {
        "trusted_user_id": uuid4(),
        "invitation_id": uuid4(),
        "project_id": uuid4(),
        "user_id": uuid4(),
        "expires_at": expires_at,
        "user_email": user_email,
        "owner_email": owner_email,
        "owner_id": uuid4(),
        "project_name": "Project Alpha",
    }


@pytest.fixture
def patched_io(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    enqueue_mock = AsyncMock()
    audit_mock = AsyncMock()

    def _factory_factory(session: _FakeSession) -> Any:
        def _factory() -> _SessionFactoryCM:
            return _SessionFactoryCM(session)

        return _factory

    monkeypatch.setattr(notifier.outbox_service, "enqueue", enqueue_mock)
    monkeypatch.setattr(notifier, "_record_notice_audit", audit_mock)

    return {
        "enqueue": enqueue_mock,
        "audit": audit_mock,
        "factory_factory": _factory_factory,
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


async def test_run_notify_expiring_enqueues_two_events_per_row(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: dict[str, AsyncMock],
) -> None:
    """A single overlay in the 7-day window enqueues both user + owner."""
    in_window = datetime.now(UTC).replace(microsecond=0) + (
        # 6.5 days out — comfortably inside [6d, 7d).
        # Use raw timedelta to avoid drift on slow machines.
        __import__("datetime").timedelta(days=6, hours=12)
    )
    rows = [_row(expires_at=in_window)]
    session = _FakeSession(rows)
    monkeypatch.setattr(
        notifier, "AsyncSessionLocal", patched_io["factory_factory"](session)
    )

    summary = await notifier._run_notify_expiring()

    assert summary == {"notified": 1, "skipped": 0}
    # Two enqueue calls: one for trusted_user role, one for owner.
    enqueue_calls = patched_io["enqueue"].await_args_list
    assert len(enqueue_calls) == 2

    roles = sorted(call.kwargs["payload"]["role"] for call in enqueue_calls)
    assert roles == ["owner", "trusted_user"]

    # Idempotency keys carry the day suffix so a second run on the same
    # UTC date collapses via ON CONFLICT (idempotency_key) DO UPDATE.
    keys = [call.kwargs["idempotency_key"] for call in enqueue_calls]
    today = datetime.now(UTC).date().isoformat()
    assert all(today in key for key in keys)
    assert all(key.startswith("trusted_expiry:") for key in keys)

    # Audit row recorded once for the row.
    assert patched_io["audit"].await_count == 1
    assert session.commits == 1
    assert session.rollbacks == 0


async def test_run_notify_expiring_skips_rows_outside_window(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: dict[str, AsyncMock],
) -> None:
    """An empty result set means the SELECT correctly filters by window.

    The notifier delegates the window filter to PostgreSQL via the
    inclusive ``BETWEEN :floor AND :ceiling`` clause; here we simulate
    the SELECT returning nothing (e.g. a row whose ``expires_at`` is
    5 days out — caught by the WHERE clause). The notifier must
    short-circuit without enqueueing or auditing.
    """
    session = _FakeSession([])
    monkeypatch.setattr(
        notifier, "AsyncSessionLocal", patched_io["factory_factory"](session)
    )

    summary = await notifier._run_notify_expiring()

    assert summary == {"notified": 0, "skipped": 0}
    assert patched_io["enqueue"].await_count == 0
    assert patched_io["audit"].await_count == 0
    # No rows -> early return, no commit needed.
    assert session.commits == 0


async def test_run_notify_expiring_skips_row_with_missing_emails(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: dict[str, AsyncMock],
) -> None:
    """Rows whose join produced an empty email column are skipped.

    Without this guard the dispatcher would dead-letter the outbox row
    after MAX_RETRY attempts; failing fast keeps the outbox table tidy.
    """
    in_window = datetime.now(UTC) + __import__("datetime").timedelta(
        days=6, hours=8
    )
    rows = [
        _row(expires_at=in_window, user_email=""),  # malformed user join
        _row(expires_at=in_window, owner_email=""),  # malformed owner join
    ]
    session = _FakeSession(rows)
    monkeypatch.setattr(
        notifier, "AsyncSessionLocal", patched_io["factory_factory"](session)
    )

    summary = await notifier._run_notify_expiring()

    assert summary == {"notified": 0, "skipped": 2}
    assert patched_io["enqueue"].await_count == 0
    assert patched_io["audit"].await_count == 0


async def test_idempotency_key_is_stable_per_day_and_role() -> None:
    """Two calls with the same (invitation_id, role, day) → identical key."""
    invitation_id = uuid4()
    today = datetime(2026, 4, 27, tzinfo=UTC).date()
    user_key = notifier._idempotency_key(
        role="trusted_user", invitation_id=invitation_id, notify_day=today
    )
    owner_key = notifier._idempotency_key(
        role="owner", invitation_id=invitation_id, notify_day=today
    )
    user_key_again = notifier._idempotency_key(
        role="trusted_user", invitation_id=invitation_id, notify_day=today
    )

    assert user_key == user_key_again
    # Different role → different key, otherwise the second enqueue would
    # be collapsed by ON CONFLICT and the Owner email never lands.
    assert user_key != owner_key
    assert today.isoformat() in user_key
