"""Unit test for evaluation task failure-state propagation (SFR-12).

On failure the async worker must (a) mark the ``EvaluationRun`` FAILED and
(b) re-raise so the Celery task state becomes FAILURE. Previously it returned a
``{"status": "failed"}`` dict, which left the task in SUCCESS despite the run
being FAILED — a silent failure for anything inspecting task state.

The worker DB/engine plumbing is faked so this runs without a database.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.workers import evaluation_tasks


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_evaluation_task_reraises_and_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scoring failure marks the run FAILED and propagates (task -> FAILURE)."""
    run_id = uuid4()

    fake_session = _FakeSession()
    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    def _session_factory() -> _FakeSession:
        return fake_session

    monkeypatch.setattr(
        evaluation_tasks,
        "get_worker_engine_and_session_factory",
        lambda: (fake_engine, _session_factory),
    )

    run = MagicMock()
    run.annotation_set_id = uuid4()
    run.requested_model_refs = [{"kind": "birdnet"}]

    run_repo = MagicMock()
    run_repo.get_by_id = AsyncMock(return_value=run)
    run_repo.mark_running = AsyncMock()
    run_repo.mark_failed = AsyncMock()
    run_repo.mark_completed = AsyncMock()

    monkeypatch.setattr(
        evaluation_tasks, "EvaluationRunRepository", lambda _db: run_repo
    )
    monkeypatch.setattr(
        evaluation_tasks, "EvaluationResultRepository", lambda _db: MagicMock()
    )

    # Force the scoring path to blow up.
    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("segment load exploded")

    monkeypatch.setattr(evaluation_tasks, "_load_segments", _boom)

    with pytest.raises(RuntimeError, match="segment load exploded"):
        await evaluation_tasks._run_annotation_evaluation(run_id)

    # Run marked FAILED, never COMPLETED, and the engine was still disposed.
    run_repo.mark_failed.assert_awaited_once()
    run_repo.mark_completed.assert_not_awaited()
    fake_engine.dispose.assert_awaited_once()
