"""At-most-once log guarantee for the outbox processor (T082, FR-076a, SC-021).

The outbox row's ``idempotency_key`` is the linchpin of the at-most-once
log guarantee: when a worker crashes between handler completion and
``mark_done``, the row is re-claimed and the handler runs again. The
handler MUST therefore be idempotent — keying its side-effects on the
``idempotency_key`` so a re-run is a no-op rather than a duplicate audit
log row.

These unit tests run with a fully-mocked AsyncSession so they exercise
only the contract of :mod:`echoroo.services.outbox_service` and the
processor's handler dispatch loop without touching PostgreSQL or
Celery's broker.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from echoroo.services import outbox_service
from echoroo.services.outbox_service import (
    MAX_RETRY,
    STATUS_DEAD_LETTER,
    STATUS_FAILED,
    STATUS_PENDING,
    enqueue,
    mark_done,
    mark_failed,
)
from echoroo.workers import outbox_processor
from echoroo.workers.outbox_processor import (
    OUTBOX_HANDLERS,
    _process_one,
    register_outbox_handler,
)

# ---------------------------------------------------------------------------
# Fake AsyncSession that records every executed SQL + params and lets the
# test return canned rows for SELECT-style statements.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row: tuple[Any, ...] | None = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or []

    def first(self) -> tuple[Any, ...] | None:
        return self._row

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


def _make_session_for_enqueue(returned_id: UUID) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
    """Build a mock AsyncSession that responds to enqueue's INSERT RETURNING id."""
    calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(stmt: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        calls.append((str(stmt), params or {}))
        # The enqueue helper issues a single INSERT ... RETURNING id.
        return _FakeResult(row=(returned_id,))

    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute)
    return session, calls


# ---------------------------------------------------------------------------
# enqueue: UNIQUE conflict on idempotency_key returns existing id.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_returns_existing_id_on_idempotency_key_conflict() -> None:
    """Two enqueue calls with the same idempotency_key share an id (no duplicate row).

    The implementation uses ``INSERT ... ON CONFLICT (idempotency_key) DO
    UPDATE ... RETURNING id`` so that both the first writer (insert) and
    every subsequent writer (conflict path) get back the same row id.
    """
    fixed_id = uuid4()
    session, calls = _make_session_for_enqueue(fixed_id)

    first = await enqueue(
        session,
        event_type="api_key_revoke_on_member_removal",
        payload={"user_id": "u1", "project_id": "p1"},
        idempotency_key="rev:u1:p1:1",
    )
    second = await enqueue(
        session,
        event_type="api_key_revoke_on_member_removal",
        payload={"user_id": "u1", "project_id": "p1"},
        idempotency_key="rev:u1:p1:1",
    )

    assert first == second == fixed_id

    # Both INSERTs should pass through the ON CONFLICT clause; we don't
    # commit between them, but the contract is that the SQL itself
    # carries the deduplication.
    assert len(calls) == 2
    for sql, params in calls:
        assert "ON CONFLICT (idempotency_key)" in sql
        assert params["idempotency_key"] == "rev:u1:p1:1"


@pytest.mark.asyncio
async def test_enqueue_rejects_empty_event_type_and_idempotency_key() -> None:
    """Defensive validation — empty discriminators are programmer errors."""
    session, _calls = _make_session_for_enqueue(uuid4())

    with pytest.raises(ValueError):
        await enqueue(
            session,
            event_type="",
            payload={},
            idempotency_key="k",
        )
    with pytest.raises(ValueError):
        await enqueue(
            session,
            event_type="t",
            payload={},
            idempotency_key="",
        )


# ---------------------------------------------------------------------------
# Worker crash + retry: handler is idempotent, audit log called once.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_handler_registry() -> Any:
    """Snapshot OUTBOX_HANDLERS so each test sees a clean registry."""
    snapshot = dict(OUTBOX_HANDLERS)
    yield
    OUTBOX_HANDLERS.clear()
    OUTBOX_HANDLERS.update(snapshot)


class _AuditWriter:
    """Idempotency-aware audit-log mock.

    Records every key the handler attempts to write and asserts the same
    key is never written twice. Mirrors the production sanity check: the
    real audit writer SELECTs ``WHERE detail->>'outbox_idempotency_key'
    = :key`` before INSERT (research.md §6).
    """

    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.attempts: list[str] = []

    def write(self, idempotency_key: str) -> None:
        self.attempts.append(idempotency_key)
        if idempotency_key in self.keys:
            raise AssertionError(
                f"duplicate audit-log write for idempotency_key={idempotency_key!r}"
            )
        self.keys.add(idempotency_key)


@pytest.mark.asyncio
async def test_handler_rerun_on_worker_crash_does_not_duplicate_audit_log() -> None:
    """Simulate worker crash AFTER handler side-effect but BEFORE mark_done.

    The handler must be idempotent: a re-claim of the same row triggers
    a second handler invocation, but the side-effect (audit log write)
    must only land once because it is keyed on ``idempotency_key``.
    """
    audit = _AuditWriter()
    crash_after_first_call = {"crash": True}
    payload = {"user_id": "u42", "project_id": "p9"}
    idempotency_key = "rev:u42:p9:abc"

    @register_outbox_handler("test_at_most_once")
    async def handler(_session: Any, p: dict[str, Any]) -> None:
        # Idempotency check: only write the audit log once per key.
        key = p["idempotency_key"]
        if key not in audit.keys:
            audit.write(key)
        # First invocation crashes BEFORE mark_done is called.
        if crash_after_first_call["crash"]:
            crash_after_first_call["crash"] = False
            raise RuntimeError("simulated worker crash mid-flight")

    # First attempt — will raise, mark_failed is invoked, retry_count→1.
    session1 = MagicMock()
    session1.execute = AsyncMock(return_value=_FakeResult())
    row1 = {
        "id": uuid4(),
        "event_type": "test_at_most_once",
        "payload": {**payload, "idempotency_key": idempotency_key},
        "retry_count": 0,
        "idempotency_key": idempotency_key,
    }
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        await _process_one(session1, row1)

    # The handler logged the audit-log write once before crashing.
    assert audit.attempts == [idempotency_key]
    assert audit.keys == {idempotency_key}

    # Second attempt (re-claim of the SAME row, retry_count bumped to 1).
    session2 = MagicMock()
    session2.execute = AsyncMock(return_value=_FakeResult())
    row2 = {
        "id": row1["id"],
        "event_type": "test_at_most_once",
        "payload": {**payload, "idempotency_key": idempotency_key},
        "retry_count": 1,
        "idempotency_key": idempotency_key,
    }
    await _process_one(session2, row2)

    # Re-run: the handler is idempotent — no duplicate audit-log write.
    assert audit.attempts == [idempotency_key], (
        "handler must skip audit-log write on retry once the key is recorded"
    )
    assert audit.keys == {idempotency_key}

    # mark_done was invoked on the successful retry.
    rendered = [str(c.args[0]).lower() for c in session2.execute.await_args_list]
    assert any("update outbox_events" in sql and "status = :done" in sql for sql in rendered)


@pytest.mark.asyncio
async def test_mark_failed_promotes_row_to_dead_letter_after_max_retry() -> None:
    """Once retry_count + 1 >= MAX_RETRY the row enters dead_letter status."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult())

    final_status = await mark_failed(
        session,
        uuid4(),
        error="repeated handler failure",
        current_retry_count=MAX_RETRY - 1,  # i.e. one more failure exhausts the budget.
    )
    assert final_status == STATUS_DEAD_LETTER

    rendered = [str(c.args[0]).lower() for c in session.execute.await_args_list]
    assert any("status = :dead_letter" in sql for sql in rendered)


@pytest.mark.asyncio
async def test_mark_failed_reschedules_with_backoff_when_budget_remains() -> None:
    """A failure with budget left reschedules the row with status='pending'."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult())

    final_status = await mark_failed(
        session,
        uuid4(),
        error="transient failure",
        current_retry_count=0,
    )
    assert final_status == STATUS_FAILED  # Reported status is "failed".

    # The actual row is moved BACK to ``pending`` so it can be re-claimed,
    # while a non-NULL next_retry_at enforces the backoff window.
    rendered_calls = list(session.execute.await_args_list)
    assert rendered_calls, "mark_failed must execute at least one statement"
    sql = str(rendered_calls[0].args[0]).lower()
    assert "status = :pending" in sql
    assert "next_retry_at = :next_retry_at" in sql

    params = rendered_calls[0].args[1]
    assert params["pending"] == STATUS_PENDING
    assert params["retry_count"] == 1


@pytest.mark.asyncio
async def test_mark_done_clears_last_error_and_sets_processed_at() -> None:
    """mark_done must wipe last_error and SCRUB the payload (FR-105).

    The payload column may carry transient PII (e.g. raw IP / UA on a
    ``login_notification`` row). Once the handler has succeeded the
    payload is no longer needed; ``mark_done`` therefore replaces it
    with a small ``{"scrubbed_at": ...}`` marker in the same UPDATE so
    the row never retains long-term PII.
    """
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult())

    await mark_done(session, uuid4())

    rendered = [str(c.args[0]).lower() for c in session.execute.await_args_list]
    assert any(
        "status = :done" in sql
        and "processed_at = :now" in sql
        and "last_error = null" in sql
        and "payload = cast(:payload as jsonb)" in sql
        for sql in rendered
    ), rendered

    # The bound payload parameter must be the scrub marker, NOT the
    # original payload contents.
    rendered_calls = list(session.execute.await_args_list)
    payload_param = rendered_calls[0].args[1]["payload"]
    assert "scrubbed_at" in payload_param
    assert "ip" not in payload_param  # raw fields gone
    assert "user_agent" not in payload_param


@pytest.mark.asyncio
async def test_mark_failed_dead_letter_branch_scrubs_payload() -> None:
    """Dead-letter rows must also have their payload scrubbed (FR-105)."""
    session = MagicMock()
    session.execute = AsyncMock(return_value=_FakeResult())

    final_status = await mark_failed(
        session,
        uuid4(),
        error="repeated handler failure",
        current_retry_count=MAX_RETRY - 1,
    )
    assert final_status == STATUS_DEAD_LETTER

    rendered_calls = list(session.execute.await_args_list)
    sql = str(rendered_calls[0].args[0]).lower()
    assert "status = :dead_letter" in sql
    assert "payload = cast(:payload as jsonb)" in sql

    payload_param = rendered_calls[0].args[1]["payload"]
    assert "scrubbed_at" in payload_param
    assert "dead_letter" in payload_param  # scrub_reason marker
    assert "ip" not in payload_param  # raw fields gone


def test_max_retry_constant_matches_spec() -> None:
    """spec data-model.md §3.18 fixes MAX_RETRY=5; the impl must agree."""
    assert outbox_service.MAX_RETRY == 5
    assert outbox_processor.CELERY_TASK_MAX_RETRIES == 3
