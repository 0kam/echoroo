"""Coverage uplift unit tests for ``echoroo.workers.outbox_processor``.

Phase 17 §C medium-gap batch: targets ``register_outbox_handler``
duplicate-check (line 99), ``_default_handler`` raises (line 116),
``_worker_id`` (line 136), ``_record_failure`` exception swallow
(lines 189-195), ``_drain_batch`` empty-claim early-return + per-row
processing (line 225, 237), and ``process_outbox_batch`` happy path +
retry path (lines 292, 294, 296, 298-299, 306, 311-317, 319) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.workers import outbox_processor as mod

# ---------------------------------------------------------------------------
# register_outbox_handler / _resolve_handler / _default_handler
# ---------------------------------------------------------------------------


def test_register_outbox_handler_rejects_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    """register_outbox_handler raises on duplicate event_type (line 99)."""
    # Use a new isolated registry to avoid side-effects on other tests.
    monkeypatch.setattr(mod, "OUTBOX_HANDLERS", {}, raising=True)

    @mod.register_outbox_handler("e1")
    async def _h1(_session: Any, _payload: dict[str, Any]) -> None:
        return None

    with pytest.raises(ValueError, match="already registered"):
        @mod.register_outbox_handler("e1")
        async def _h2(_session: Any, _payload: dict[str, Any]) -> None:
            return None


def test_register_outbox_handler_returns_decorator(monkeypatch: pytest.MonkeyPatch) -> None:
    """The decorator returns the original handler."""
    monkeypatch.setattr(mod, "OUTBOX_HANDLERS", {}, raising=True)

    async def _h(_session: Any, _payload: dict[str, Any]) -> None:
        return None

    decorated = mod.register_outbox_handler("e2")(_h)
    assert decorated is _h
    assert mod.OUTBOX_HANDLERS["e2"] is _h


@pytest.mark.asyncio
async def test_default_handler_raises_not_implemented() -> None:
    """_default_handler logs + raises NotImplementedError (line 116)."""
    db = MagicMock()
    with pytest.raises(NotImplementedError):
        await mod._default_handler(db, {"k": "v"})


def test_resolve_handler_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """_resolve_handler returns _default_handler for unknown event_type."""
    monkeypatch.setattr(mod, "OUTBOX_HANDLERS", {}, raising=True)
    handler = mod._resolve_handler("never-seen")
    assert handler is mod._default_handler


def test_worker_id_includes_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """_worker_id returns ``host:pid`` (line 136)."""
    out = mod._worker_id()
    assert ":" in out
    host, pid = out.rsplit(":", 1)
    assert host
    assert pid.isdigit()


# ---------------------------------------------------------------------------
# _process_one
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_one_runs_handler_and_marks_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_process_one resolves the handler + marks the row done."""
    monkeypatch.setattr(mod, "OUTBOX_HANDLERS", {}, raising=True)

    handler_called: list[tuple[Any, dict[str, Any]]] = []

    async def _handler(session: Any, payload: dict[str, Any]) -> None:
        handler_called.append((session, payload))

    monkeypatch.setitem(mod.OUTBOX_HANDLERS, "evt", _handler)

    session = MagicMock()
    row = {"id": uuid4(), "event_type": "evt", "payload": {"k": "v"}}

    with patch.object(mod, "mark_done", new=AsyncMock()) as mark_done_mock:
        await mod._process_one(session, row)

    assert handler_called == [(session, {"k": "v"})]
    mark_done_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# _record_failure — exception swallow path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_failure_swallows_secondary_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If mark_failed raises, _record_failure logs and returns (lines 189-195)."""

    @asynccontextmanager
    async def _factory() -> Any:
        session = MagicMock()
        # session.begin() yields itself.
        @asynccontextmanager
        async def _begin() -> Any:
            yield session

        session.begin = _begin
        yield session

    with patch.object(mod, "mark_failed", new=AsyncMock(side_effect=RuntimeError("boom"))):
        # Should NOT raise.
        await mod._record_failure(
            _factory,  # type: ignore[arg-type]
            event_id=uuid4(),
            error="orig",
            current_retry_count=1,
        )


# ---------------------------------------------------------------------------
# _drain_batch — empty claim early return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_batch_returns_zero_when_no_rows_claimed() -> None:
    """No rows claimed → returns 0 (line 225)."""

    @asynccontextmanager
    async def _factory() -> Any:
        session = MagicMock()

        @asynccontextmanager
        async def _begin() -> Any:
            yield session

        session.begin = _begin
        yield session

    with patch.object(mod, "requeue_stuck_processing", new=AsyncMock()), \
            patch.object(mod, "claim_batch", new=AsyncMock(return_value=[])):
        result = await mod._drain_batch(
            _factory,  # type: ignore[arg-type]
            batch_size=10,
            worker_id="host:1",
        )
    assert result == 0


@pytest.mark.asyncio
async def test_drain_batch_processes_rows_and_records_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed rows: success counted, failure delegated to _record_failure."""
    monkeypatch.setattr(mod, "OUTBOX_HANDLERS", {}, raising=True)

    async def _good(_session: Any, _payload: dict[str, Any]) -> None:
        return None

    async def _bad(_session: Any, _payload: dict[str, Any]) -> None:
        raise RuntimeError("nope")

    monkeypatch.setitem(mod.OUTBOX_HANDLERS, "ok", _good)
    monkeypatch.setitem(mod.OUTBOX_HANDLERS, "fail", _bad)

    rows = [
        {"id": uuid4(), "event_type": "ok", "payload": {}, "retry_count": 0},
        {"id": uuid4(), "event_type": "fail", "payload": {}, "retry_count": 0},
    ]

    @asynccontextmanager
    async def _factory() -> Any:
        session = MagicMock()

        @asynccontextmanager
        async def _begin() -> Any:
            yield session

        session.begin = _begin
        yield session

    with patch.object(mod, "requeue_stuck_processing", new=AsyncMock()), \
            patch.object(mod, "claim_batch", new=AsyncMock(return_value=rows)), \
            patch.object(mod, "mark_done", new=AsyncMock()), \
            patch.object(mod, "_record_failure", new=AsyncMock()) as rec_mock:
        result = await mod._drain_batch(
            _factory,  # type: ignore[arg-type]
            batch_size=10,
            worker_id="host:1",
            stale_age=timedelta(minutes=5),
        )
    # Only one row succeeded.
    assert result == 1
    rec_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# process_outbox_batch — happy path + retry path
# ---------------------------------------------------------------------------


def test_process_outbox_batch_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path returns the processed count + worker_id (lines 292-305, 319).

    The Celery task is decorated with ``bind=True``; calling via
    ``apply()`` runs the task synchronously while the celery framework
    handles the ``self`` plumbing so ``self.request.retries`` is 0.
    """
    fake_engine = MagicMock()
    fake_factory = MagicMock()

    monkeypatch.setattr(
        "echoroo.workers.db_utils.get_worker_engine_and_session_factory",
        lambda: (fake_engine, fake_factory),
    )

    async def _drain(*args: Any, **kwargs: Any) -> int:
        return 7

    monkeypatch.setattr(mod, "_drain_batch", _drain)

    result = mod.process_outbox_batch.apply(kwargs={"batch_size": 10})
    out = result.get()
    assert out["processed"] == 7
    assert "worker_id" in out


def test_process_outbox_batch_retry_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient failure routed through self.retry (lines 306-317).

    Patch the bound ``retry`` method on the task to raise a marker so we
    can detect the retry call without a Celery broker. ``apply()`` with
    ``throw=False`` captures the marker on ``result.result``.
    """
    fake_engine = MagicMock()
    fake_factory = MagicMock()

    monkeypatch.setattr(
        "echoroo.workers.db_utils.get_worker_engine_and_session_factory",
        lambda: (fake_engine, fake_factory),
    )

    async def _drain(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("broker down")

    monkeypatch.setattr(mod, "_drain_batch", _drain)

    retry_calls: list[dict[str, Any]] = []

    def _fake_retry(*args: Any, **kwargs: Any) -> None:
        retry_calls.append(kwargs)
        # Use a built-in exception so Celery's serialiser doesn't wrap it.
        raise RuntimeError("retry-called")

    monkeypatch.setattr(mod.process_outbox_batch, "retry", _fake_retry)

    # apply() captures the exception; throw=False stops it from re-raising.
    result = mod.process_outbox_batch.apply(kwargs={"batch_size": 10}, throw=False)
    assert result.failed()
    # The retry path was traversed at least once.
    assert retry_calls, "self.retry was not invoked"
    assert "countdown" in retry_calls[0]
