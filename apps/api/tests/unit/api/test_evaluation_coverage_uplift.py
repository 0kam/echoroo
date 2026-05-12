"""Coverage uplift unit tests for ``echoroo.api.v1.evaluation``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers evaluation route handlers
(create_evaluation_run, list_evaluation_runs_for_set, list_evaluation_runs,
get_evaluation_run, delete_evaluation_run) plus _annotation_set_project_id
404 path so the module clears the 85% threshold without touching production
code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1 import evaluation as mod


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    return user


def _make_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    return db


def _make_service() -> MagicMock:
    svc = MagicMock()
    svc.evaluate_annotation_set = AsyncMock()
    svc.list_by_annotation_set = AsyncMock()
    svc.get_run = AsyncMock()
    svc.get_summary = AsyncMock()
    svc.delete_run = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_annotation_set_project_id_raises_404_when_not_found() -> None:
    """_annotation_set_project_id raises 404 when annotation set missing (line 77-81)."""
    db = _make_db()
    result_mock = MagicMock()
    result_mock.first.return_value = None
    db.execute = AsyncMock(return_value=result_mock)

    with pytest.raises(HTTPException) as exc_info:
        await mod._annotation_set_project_id(db, uuid4())

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_annotation_set_project_id_returns_project_id() -> None:
    """_annotation_set_project_id returns project_id when found (line 84-85)."""
    db = _make_db()
    project_id = uuid4()
    result_mock = MagicMock()
    result_mock.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result_mock)

    result = await mod._annotation_set_project_id(db, uuid4())
    assert result == project_id


@pytest.mark.asyncio
async def test_create_evaluation_run_delegates_to_service() -> None:
    """create_evaluation_run delegates to service (lines 112-116)."""
    user = _make_user()
    service = _make_service()
    db = _make_db()
    project_id = uuid4()
    annotation_set_id = uuid4()

    from echoroo.schemas.evaluation import BirdNETModelRef, EvaluationRunCreate

    payload = EvaluationRunCreate(model_refs=[BirdNETModelRef()])
    sentinel = MagicMock()
    service.evaluate_annotation_set = AsyncMock(return_value=sentinel)

    result_mock = MagicMock()
    result_mock.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result_mock)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock()), create=True):
        result = await mod.create_evaluation_run(
            annotation_set_id=annotation_set_id,
            payload=payload,
            request=MagicMock(),
            current_user=user,
            service=service,
            db=db,
        )

    assert result is sentinel


@pytest.mark.asyncio
async def test_list_evaluation_runs_for_set_delegates_to_service() -> None:
    """list_evaluation_runs_for_set delegates to service (lines 137-140)."""
    user = _make_user()
    service = _make_service()
    db = _make_db()
    project_id = uuid4()
    annotation_set_id = uuid4()

    service.list_by_annotation_set = AsyncMock(return_value=([], 1))

    result_mock = MagicMock()
    result_mock.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result_mock)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock()), create=True):
        result = await mod.list_evaluation_runs_for_set(
            annotation_set_id=annotation_set_id,
            request=MagicMock(),
            current_user=user,
            service=service,
            db=db,
            limit=50,
            offset=0,
        )

    assert result.total == 1


@pytest.mark.asyncio
async def test_list_evaluation_runs_delegates_to_service() -> None:
    """list_evaluation_runs delegates to service (lines 165-166)."""
    user = _make_user()
    service = _make_service()
    db = _make_db()
    project_id = uuid4()
    annotation_set_id = uuid4()

    service.list_by_annotation_set = AsyncMock(return_value=([], 2))

    result_mock = MagicMock()
    result_mock.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result_mock)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock()), create=True):
        result = await mod.list_evaluation_runs(
            current_user=user,
            request=MagicMock(),
            service=service,
            db=db,
            annotation_set_id=annotation_set_id,
            limit=50,
            offset=0,
        )

    assert result.total == 2


@pytest.mark.asyncio
async def test_get_evaluation_run_returns_summary() -> None:
    """get_evaluation_run returns EvaluationSummary (lines 189-194)."""
    user = _make_user()
    service = _make_service()
    db = _make_db()
    project_id = uuid4()
    annotation_set_id = uuid4()
    run_id = uuid4()

    run = MagicMock()
    run.annotation_set_id = annotation_set_id
    service.get_run = AsyncMock(return_value=run)

    summary = MagicMock()
    service.get_summary = AsyncMock(return_value=summary)

    result_mock = MagicMock()
    result_mock.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result_mock)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock()), create=True):
        result = await mod.get_evaluation_run(
            run_id=run_id,
            request=MagicMock(),
            current_user=user,
            service=service,
            db=db,
        )

    assert result is summary


@pytest.mark.asyncio
async def test_delete_evaluation_run_calls_service_delete() -> None:
    """delete_evaluation_run calls service.delete_run (lines 209-214)."""
    user = _make_user()
    service = _make_service()
    db = _make_db()
    project_id = uuid4()
    annotation_set_id = uuid4()
    run_id = uuid4()

    run = MagicMock()
    run.annotation_set_id = annotation_set_id
    service.get_run = AsyncMock(return_value=run)

    result_mock = MagicMock()
    result_mock.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result_mock)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock()), create=True):
        await mod.delete_evaluation_run(
            run_id=run_id,
            request=MagicMock(),
            current_user=user,
            service=service,
            db=db,
        )

    service.delete_run.assert_awaited_once_with(run_id)
