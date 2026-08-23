"""Unit tests for the bound ``resolve_gbif_batch`` Celery task (WS-A v2 slice 5).

Mirrors ``test_taxon_col_xr_task.py``: the task is bound so its own dispatch
id becomes the actor of every identity-history row the GBIF resolver writes.
"""

from __future__ import annotations

import pytest

from echoroo.workers import taxon_tasks


def test_gbif_task_is_bound_and_threads_its_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dispatch id reaches the async implementation as ``task_id``."""
    seen: list[tuple[int, str | None]] = []

    async def _fake(batch_size: int, task_id: str | None = None) -> dict[str, object]:
        seen.append((batch_size, task_id))
        return {"status": "completed", "resolved": 0, "taxa_errored": 0}

    monkeypatch.setattr(taxon_tasks, "_run_resolve_gbif_batch", _fake)

    task = taxon_tasks.resolve_gbif_batch
    task.push_request(id="celery-gbif-42")
    try:
        task.run(batch_size=7)
    finally:
        task.pop_request()

    assert seen == [(7, "celery-gbif-42")]


def test_gbif_task_direct_call_is_unattributed(monkeypatch: pytest.MonkeyPatch) -> None:
    """An in-process call has no dispatch id; the service records ``system``."""
    seen: list[str | None] = []

    async def _fake(_batch_size: int, task_id: str | None = None) -> dict[str, object]:
        seen.append(task_id)
        return {"status": "completed", "resolved": 0, "taxa_errored": 0}

    monkeypatch.setattr(taxon_tasks, "_run_resolve_gbif_batch", _fake)

    taxon_tasks.resolve_gbif_batch.run(batch_size=3)

    assert seen == [None]


@pytest.mark.asyncio
async def test_gbif_async_impl_forwards_task_id_to_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_run_resolve_gbif_batch`` passes ``task_id`` through to the service."""
    captured: dict[str, object] = {}

    class _Result:
        resolved = 2
        errored = 0

    class _Service:
        def __init__(self, *, taxon_repo: object) -> None:
            captured["repo"] = taxon_repo

        async def resolve_gbif_batch(self, *, limit: int, task_id: str | None = None) -> _Result:
            captured["limit"] = limit
            captured["task_id"] = task_id
            return _Result()

    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def commit(self) -> None:
            captured["committed"] = True

    class _Engine:
        async def dispose(self) -> None:
            captured["disposed"] = True

    monkeypatch.setattr(
        taxon_tasks,
        "get_worker_engine_and_session_factory",
        lambda: (_Engine(), lambda: _Session()),
    )
    import echoroo.services.taxon as taxon_service_module

    monkeypatch.setattr(taxon_service_module, "TaxonService", _Service)

    result = await taxon_tasks._run_resolve_gbif_batch(5, "celery-gbif-99")

    assert captured["limit"] == 5
    assert captured["task_id"] == "celery-gbif-99"
    assert captured["committed"] is True and captured["disposed"] is True
    assert result == {"status": "completed", "resolved": 2, "taxa_errored": 0}
