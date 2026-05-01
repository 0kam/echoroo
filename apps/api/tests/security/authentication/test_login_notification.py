"""TDD coverage for :class:`LoginNotificationService` (FR-104).

The contract:

* First login from (IP_A, UA_A) when no prior records exist → service
  returns ``True`` and an :class:`OutboxEvent` is enqueued.
* Subsequent login from the SAME (IP_A, UA_A) within 24 hours → service
  returns ``False`` and NO new OutboxEvent is enqueued. The
  ``last_seen_at`` row is refreshed so the suppression window slides.
* Login from a NEW IP (IP_B, UA_A) → service returns ``True`` and a
  fresh OutboxEvent is enqueued. The IP and UA are independent — only
  the *combined* tuple counts as "seen".
* IP_A login within the 30-day retention window does NOT generate a
  notification (already known).
* After 30 days the IP_A row is "expired"; a fresh login from the
  same IP generates a notification again. The service must not rely
  on a TTL-driven DELETE for correctness — it inspects ``last_seen_at``
  per call.

The fakes mirror the real Postgres behaviour just enough to satisfy
the service's queries: a single dict keyed by ``(user_id, ip_hash, ua_hash)``
with the usual upsert / SELECT semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.user import User
from echoroo.services import login_notification_service as login_module
from echoroo.services.login_notification_service import (
    LOGIN_NOTIFICATION_EVENT_TYPE,
    LOGIN_RECORD_RETENTION,
    LoginNotificationService,
)

pytestmark = pytest.mark.asyncio


class _FakeRow:
    def __init__(self, last_seen_at: datetime | None) -> None:
        self._value = last_seen_at

    def __getitem__(self, idx: int) -> Any:
        if idx != 0:
            raise IndexError(idx)
        return self._value


class _FakeResult:
    def __init__(self, row: _FakeRow | None) -> None:
        self._row = row

    def first(self) -> _FakeRow | None:
        return self._row


class _FakeSession:
    """Minimal AsyncSession stand-in for the upsert + select queries.

    Records every ``execute()`` call so individual tests can assert on
    the parameter shape (e.g. the suppression-window cutoff).
    """

    def __init__(self) -> None:
        self.seen: dict[tuple[Any, str, str], datetime] = {}
        self.executions: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> Any:
        sql = str(statement).strip()
        params = params or {}
        self.executions.append((sql, params))

        if sql.upper().startswith("SELECT "):
            user_id = params["user_id"]
            ip_hash = params["ip_hash"]
            ua_hash = params["ua_hash"]
            cutoff: datetime = params["retention_cutoff"]
            last_seen = self.seen.get((user_id, ip_hash, ua_hash))
            if last_seen is None:
                return _FakeResult(None)
            if last_seen <= cutoff:
                return _FakeResult(None)
            return _FakeResult(_FakeRow(last_seen))

        # The INSERT ... ON CONFLICT DO UPDATE branch.
        if "INSERT INTO user_login_notifications_seen" in sql:
            user_id = params["user_id"]
            ip_hash = params["ip_hash"]
            ua_hash = params["ua_hash"]
            now: datetime = params["now"]
            self.seen[(user_id, ip_hash, ua_hash)] = now
            return _FakeResult(None)

        # The outbox enqueue path lands here as a separate INSERT.
        if "INSERT INTO outbox_events" in sql:
            return _FakeOutboxInsert(params)

        return _FakeResult(None)

    async def commit(self) -> None:
        return None


class _FakeOutboxInsert:
    """Stand-in for the asyncpg cursor result of the outbox INSERT."""

    def __init__(self, params: dict[str, Any]) -> None:
        self._params = params

    def first(self) -> tuple[Any, ...] | None:
        return (uuid4(),)


class _OutboxRecorder:
    """Captures ``outbox_service.enqueue`` calls so tests can assert on them."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(
        self,
        session: AsyncSession,  # noqa: ARG002 - mirrors real signature
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        self.calls.append(
            {
                "event_type": event_type,
                "payload": payload,
                "idempotency_key": idempotency_key,
            }
        )
        return uuid4()


@pytest.fixture
def patch_kms(monkeypatch: pytest.MonkeyPatch) -> None:
    """``compute_pii_hash`` MUST NOT call boto3 in unit tests.

    Use a deterministic hash so we can assert on payload contents and
    on the (ip_hash, ua_hash) keying of the seen-table.
    """
    monkeypatch.setattr(
        login_module,
        "compute_pii_hash",
        lambda value: f"hash:{value}",
    )


@pytest.fixture
def outbox_recorder(monkeypatch: pytest.MonkeyPatch) -> _OutboxRecorder:
    recorder = _OutboxRecorder()
    monkeypatch.setattr(login_module.outbox_service, "enqueue", recorder.enqueue)
    return recorder


def _user(email: str = "alice@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash="hash",
        security_stamp="s" + "0" * 63,
        two_factor_enabled=True,
    )


# ---------------------------------------------------------------------------
# Case (a): first login from a fresh device → notification enqueued
# ---------------------------------------------------------------------------


async def test_first_login_from_fresh_device_enqueues_notification(
    patch_kms: None,  # noqa: ARG001
    outbox_recorder: _OutboxRecorder,
) -> None:
    session = _FakeSession()
    service = LoginNotificationService(session)  # type: ignore[arg-type]
    user = _user()

    result = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="Mozilla/5.0 (Macintosh)",
    )

    assert result is True
    assert len(outbox_recorder.calls) == 1
    enqueued = outbox_recorder.calls[0]
    assert enqueued["event_type"] == LOGIN_NOTIFICATION_EVENT_TYPE
    assert enqueued["payload"]["user_id"] == str(user.id)
    assert enqueued["payload"]["ip"] == "192.0.2.10"
    assert enqueued["payload"]["ip_hash"] == "hash:192.0.2.10"
    assert enqueued["payload"]["ua_hash"] == "hash:Mozilla/5.0 (Macintosh)"
    # The seen row was upserted as part of the same call.
    assert (user.id, "hash:192.0.2.10", "hash:Mozilla/5.0 (Macintosh)") in session.seen


# ---------------------------------------------------------------------------
# Case (b): same device within 1h → suppressed
# ---------------------------------------------------------------------------


async def test_same_device_within_one_hour_is_suppressed(
    patch_kms: None,  # noqa: ARG001
    outbox_recorder: _OutboxRecorder,
) -> None:
    session = _FakeSession()
    service = LoginNotificationService(session)  # type: ignore[arg-type]
    user = _user()

    first = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="UA-1",
    )
    assert first is True
    assert len(outbox_recorder.calls) == 1

    # Same tuple — must be suppressed regardless of how many times the
    # user logs in inside the 24h window.
    second = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="UA-1",
    )
    assert second is False

    # And the third + fourth attempts on the same device stay suppressed.
    third = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="UA-1",
    )
    assert third is False
    assert len(outbox_recorder.calls) == 1


# ---------------------------------------------------------------------------
# Case (c): different IP, same UA → notification enqueued
# ---------------------------------------------------------------------------


async def test_different_ip_same_ua_enqueues_notification(
    patch_kms: None,  # noqa: ARG001
    outbox_recorder: _OutboxRecorder,
) -> None:
    session = _FakeSession()
    service = LoginNotificationService(session)  # type: ignore[arg-type]
    user = _user()

    await service.record_and_maybe_notify(user, ip="192.0.2.10", user_agent="UA-1")
    assert len(outbox_recorder.calls) == 1

    # New IP — the (user, ip, ua) tuple has never been seen, so we
    # fire a notification even though the UA is identical.
    result = await service.record_and_maybe_notify(
        user,
        ip="198.51.100.99",
        user_agent="UA-1",
    )

    assert result is True
    assert len(outbox_recorder.calls) == 2
    second = outbox_recorder.calls[1]
    assert second["payload"]["ip"] == "198.51.100.99"


# ---------------------------------------------------------------------------
# Case (d): IP_A within retention window does NOT generate a notification
# ---------------------------------------------------------------------------


async def test_known_ip_within_retention_window_does_not_renotify(
    patch_kms: None,  # noqa: ARG001
    outbox_recorder: _OutboxRecorder,
) -> None:
    session = _FakeSession()
    service = LoginNotificationService(session)  # type: ignore[arg-type]
    user = _user()

    # Pre-seed: simulate a ``last_seen_at`` 5 days ago — comfortably
    # inside the 30-day retention window AND outside the 24h
    # suppression window. The service should treat this as "known
    # device, not noisy" → no notification.
    five_days_ago = datetime.now(UTC) - timedelta(days=5)
    session.seen[(user.id, "hash:192.0.2.10", "hash:UA-1")] = five_days_ago

    result = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="UA-1",
    )

    # The contract: a (user, ip, ua) tuple seen within the retention
    # window is "known". The service must NOT re-notify just because
    # the suppression window has elapsed — that would generate
    # daily emails for the user's primary workstation.
    assert result is False, (
        "tuple seen 5 days ago must be treated as known device — "
        "no notification email expected"
    )
    assert len(outbox_recorder.calls) == 0


# ---------------------------------------------------------------------------
# Case (e): after 30-day retention, the same IP is "new again"
# ---------------------------------------------------------------------------


async def test_after_retention_window_same_ip_renotifies(
    patch_kms: None,  # noqa: ARG001
    outbox_recorder: _OutboxRecorder,
) -> None:
    session = _FakeSession()
    service = LoginNotificationService(session)  # type: ignore[arg-type]
    user = _user()

    # Pre-seed: simulate a row that is OLDER than the retention
    # window — the service's SELECT filters on
    # ``last_seen_at > retention_cutoff`` so this row is invisible
    # to the lookup, even though the upsert path would still re-use
    # the unique constraint to refresh ``last_seen_at``.
    long_ago = datetime.now(UTC) - LOGIN_RECORD_RETENTION - timedelta(days=1)
    session.seen[(user.id, "hash:192.0.2.10", "hash:UA-1")] = long_ago

    result = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="UA-1",
    )

    assert result is True
    assert len(outbox_recorder.calls) == 1
    # The seen row was upserted with the *current* timestamp (the
    # service issues an INSERT ... ON CONFLICT DO UPDATE on every
    # call), so the next request inside the suppression window must
    # be blocked.
    refreshed_ts = session.seen[(user.id, "hash:192.0.2.10", "hash:UA-1")]
    assert refreshed_ts > long_ago

    follow_up = await service.record_and_maybe_notify(
        user,
        ip="192.0.2.10",
        user_agent="UA-1",
    )
    assert follow_up is False
    assert len(outbox_recorder.calls) == 1
