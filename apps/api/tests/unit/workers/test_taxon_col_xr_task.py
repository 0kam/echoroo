"""Unit tests for the ``resolve_col_xr_batch`` Celery task (WS-A v2 slice 3).

The task itself is a thin ``asyncio.run`` wrapper, so what is worth locking is
the wiring: the registered task name (a rename silently orphans queued jobs),
the time limits, that the caller's ``batch_size`` / ``force`` reach the service,
that the session is committed, and that the returned counters are surfaced
verbatim alongside ``status``.

No database, no broker, no network — the session factory, the engine and the
service call are all stubbed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from echoroo.workers import taxon_tasks


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _patch_worker_session(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Stub the worker engine/session factory; return ``(engine, session)``."""
    session = MagicMock()
    session.commit = AsyncMock()
    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(
        taxon_tasks,
        "get_worker_engine_and_session_factory",
        lambda: (engine, lambda: _SessionContext(session)),
    )
    return engine, session


@pytest.mark.asyncio
async def test_async_impl_forwards_args_commits_and_surfaces_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session = _patch_worker_session(monkeypatch)

    resolve = AsyncMock(
        return_value={
            "processed": 3,
            "accepted": 2,
            "review": 1,
            "rejected": 0,
            "unavailable": 0,
            "release": "COL26.6 XR",
            "clb_dataset_key": 315557,
        }
    )
    monkeypatch.setattr(
        "echoroo.services.taxon.resolve_col_xr_batch", resolve, raising=False
    )

    out = await taxon_tasks._run_resolve_col_xr_batch(250, True)

    resolve.assert_awaited_once()
    assert resolve.await_args.args[0] is session
    assert resolve.await_args.kwargs == {"batch_size": 250, "force": True}
    session.commit.assert_awaited_once()
    engine.dispose.assert_awaited_once()

    assert out["status"] == "completed"
    assert out["processed"] == 3
    assert out["accepted"] == 2
    assert out["review"] == 1
    assert out["release"] == "COL26.6 XR"


@pytest.mark.asyncio
async def test_async_impl_disposes_engine_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, _session = _patch_worker_session(monkeypatch)
    monkeypatch.setattr(
        "echoroo.services.taxon.resolve_col_xr_batch",
        AsyncMock(side_effect=RuntimeError("boom")),
        raising=False,
    )

    with pytest.raises(RuntimeError):
        await taxon_tasks._run_resolve_col_xr_batch(10, False)

    engine.dispose.assert_awaited_once()


def test_task_registration_name_and_limits() -> None:
    task = taxon_tasks.resolve_col_xr_batch

    # Renaming a registered task orphans anything already queued under the
    # old name, so the name is part of the contract.
    assert task.name == "echoroo.workers.taxon_tasks.resolve_col_xr_batch"
    assert task.time_limit == 900
    assert task.soft_time_limit == 840
    assert task.soft_time_limit < task.time_limit


def test_task_delegates_to_the_async_impl(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, bool]] = []

    async def _fake(batch_size: int, force: bool) -> dict[str, object]:
        seen.append((batch_size, force))
        return {"status": "completed", "processed": 0}

    monkeypatch.setattr(taxon_tasks, "_run_resolve_col_xr_batch", _fake)

    # Defaults: a full-catalogue-friendly batch, non-destructive.
    result = taxon_tasks.resolve_col_xr_batch.run()

    assert seen == [(500, False)]
    assert result["status"] == "completed"


def test_task_reraises_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_batch_size: int, _force: bool) -> dict[str, object]:
        raise RuntimeError("upstream down")

    monkeypatch.setattr(taxon_tasks, "_run_resolve_col_xr_batch", _fake)

    # Must NOT swallow: the Celery task state has to become FAILURE.
    with pytest.raises(RuntimeError):
        taxon_tasks.resolve_col_xr_batch.run(batch_size=1)


def test_task_clamps_batch_size_to_the_time_limit_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller (or a stale queued job) must not be able to request a batch
    that cannot finish inside the 900s hard limit."""
    seen: list[tuple[int, bool]] = []

    async def _fake(batch_size: int, force: bool) -> dict[str, object]:
        seen.append((batch_size, force))
        return {"status": "completed", "processed": 0}

    monkeypatch.setattr(taxon_tasks, "_run_resolve_col_xr_batch", _fake)

    taxon_tasks.resolve_col_xr_batch.run(batch_size=999_999)
    taxon_tasks.resolve_col_xr_batch.run(batch_size=0)

    assert seen == [(taxon_tasks._COL_XR_MAX_BATCH_SIZE, False), (1, False)]


def test_task_forwards_force_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[int, bool]] = []

    async def _fake(batch_size: int, force: bool) -> dict[str, object]:
        seen.append((batch_size, force))
        return {"status": "completed", "processed": 0}

    monkeypatch.setattr(taxon_tasks, "_run_resolve_col_xr_batch", _fake)

    taxon_tasks.resolve_col_xr_batch.run(batch_size=200, force=True)

    assert seen == [(200, True)]
