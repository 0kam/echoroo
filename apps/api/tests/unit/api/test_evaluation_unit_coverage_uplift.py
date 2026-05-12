"""Coverage uplift unit tests for ``echoroo.api.v1.evaluation``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the evaluation endpoint
handlers so the module clears the 85% threshold.

Missing lines: 42,77,84,85,89,90,112-113,115-116,137-138,140,143,165-166,168,171,
              189-190,193-194,209-210,213-214
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.v1.evaluation import (
    _annotation_set_project_id,
    create_evaluation_run,
    delete_evaluation_run,
    get_evaluation_run,
    list_evaluation_runs,
    list_evaluation_runs_for_set,
)


@pytest.mark.asyncio
async def test_annotation_set_project_id_raises_404_when_not_found() -> None:
    """_annotation_set_project_id raises 404 when annotation set is absent (line 77)."""
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = None
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc_info:
        await _annotation_set_project_id(db, uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_annotation_set_project_id_returns_project_id_when_found() -> None:
    """_annotation_set_project_id returns project_id when found (lines 84-85)."""
    project_id = uuid4()
    db = MagicMock()
    result = MagicMock()
    result.first.return_value = (project_id,)
    db.execute = AsyncMock(return_value=result)

    returned = await _annotation_set_project_id(db, uuid4())
    assert returned == project_id


@pytest.mark.asyncio
async def test_create_evaluation_run_delegates_to_service() -> None:
    """create_evaluation_run resolves project_id and calls service (lines 89-90,112-116)."""
    annotation_set_id = uuid4()
    project_id = uuid4()
    current_user = MagicMock()
    current_user.id = uuid4()
    db = MagicMock()

    run_response = MagicMock()
    service = MagicMock()
    service.evaluate_annotation_set = AsyncMock(return_value=run_response)

    payload = MagicMock()
    model_ref = MagicMock()
    model_ref.model_dump.return_value = {"name": "birdnet"}
    payload.model_refs = [model_ref]

    with (
        patch(
            "echoroo.api.v1.evaluation._annotation_set_project_id",
            new=AsyncMock(return_value=project_id),
        ),
        patch(
            "echoroo.api.v1.evaluation.gate_action",
            new=AsyncMock(return_value=MagicMock()),
            create=True,
        ),
    ):
        result = await create_evaluation_run(
            annotation_set_id=annotation_set_id,
            payload=payload,
            request=MagicMock(),
            current_user=current_user,
            service=service,
            db=db,
        )

    assert result is run_response


@pytest.mark.asyncio
async def test_list_evaluation_runs_for_set_delegates_to_service() -> None:
    """list_evaluation_runs_for_set returns list (lines 137-143)."""
    annotation_set_id = uuid4()
    project_id = uuid4()
    current_user = MagicMock()
    db = MagicMock()

    run1 = MagicMock()
    service = MagicMock()
    service.list_by_annotation_set = AsyncMock(return_value=([run1], 1))

    fake_list_response = MagicMock()
    fake_list_response.total = 1
    mock_list_class = MagicMock(return_value=fake_list_response)

    with (
        patch(
            "echoroo.api.v1.evaluation._annotation_set_project_id",
            new=AsyncMock(return_value=project_id),
        ),
        patch(
            "echoroo.api.v1.evaluation.gate_action",
            new=AsyncMock(return_value=MagicMock()),
            create=True,
        ),
        patch(
            "echoroo.api.v1.evaluation.EvaluationRunResponse",
            MagicMock(model_validate=MagicMock(return_value=MagicMock())),
        ),
        patch(
            "echoroo.api.v1.evaluation.EvaluationRunListResponse",
            mock_list_class,
        ),
    ):
        result = await list_evaluation_runs_for_set(
            annotation_set_id=annotation_set_id,
            request=MagicMock(),
            current_user=current_user,
            service=service,
            db=db,
            limit=50,
            offset=0,
        )

    assert result.total == 1


@pytest.mark.asyncio
async def test_list_evaluation_runs_delegates_to_service() -> None:
    """list_evaluation_runs returns paginated list (lines 165-166,168,171)."""
    annotation_set_id = uuid4()
    project_id = uuid4()
    current_user = MagicMock()
    db = MagicMock()

    run1 = MagicMock()
    service = MagicMock()
    service.list_by_annotation_set = AsyncMock(return_value=([run1], 1))

    fake_list_response = MagicMock()
    fake_list_response.total = 1
    mock_list_class = MagicMock(return_value=fake_list_response)

    with (
        patch(
            "echoroo.api.v1.evaluation._annotation_set_project_id",
            new=AsyncMock(return_value=project_id),
        ),
        patch(
            "echoroo.api.v1.evaluation.gate_action",
            new=AsyncMock(return_value=MagicMock()),
            create=True,
        ),
        patch(
            "echoroo.api.v1.evaluation.EvaluationRunResponse",
            MagicMock(model_validate=MagicMock(return_value=MagicMock())),
        ),
        patch(
            "echoroo.api.v1.evaluation.EvaluationRunListResponse",
            mock_list_class,
        ),
    ):
        result = await list_evaluation_runs(
            current_user=current_user,
            request=MagicMock(),
            service=service,
            db=db,
            annotation_set_id=annotation_set_id,
            limit=50,
            offset=0,
        )

    assert result.total == 1


@pytest.mark.asyncio
async def test_get_evaluation_run_returns_summary() -> None:
    """get_evaluation_run resolves project and returns summary (lines 189-190,193-194)."""
    run_id = uuid4()
    annotation_set_id = uuid4()
    project_id = uuid4()
    current_user = MagicMock()
    db = MagicMock()

    run = MagicMock()
    run.annotation_set_id = annotation_set_id
    summary = MagicMock()

    service = MagicMock()
    service.get_run = AsyncMock(return_value=run)
    service.get_summary = AsyncMock(return_value=summary)

    with (
        patch(
            "echoroo.api.v1.evaluation._annotation_set_project_id",
            new=AsyncMock(return_value=project_id),
        ),
        patch(
            "echoroo.api.v1.evaluation.gate_action",
            new=AsyncMock(return_value=MagicMock()),
            create=True,
        ),
    ):
        result = await get_evaluation_run(
            run_id=run_id,
            request=MagicMock(),
            current_user=current_user,
            service=service,
            db=db,
        )

    assert result is summary


@pytest.mark.asyncio
async def test_delete_evaluation_run_calls_service() -> None:
    """delete_evaluation_run resolves project and calls service.delete_run (lines 209-214)."""
    run_id = uuid4()
    annotation_set_id = uuid4()
    project_id = uuid4()
    current_user = MagicMock()
    db = MagicMock()

    run = MagicMock()
    run.annotation_set_id = annotation_set_id

    service = MagicMock()
    service.get_run = AsyncMock(return_value=run)
    service.delete_run = AsyncMock()

    with (
        patch(
            "echoroo.api.v1.evaluation._annotation_set_project_id",
            new=AsyncMock(return_value=project_id),
        ),
        patch(
            "echoroo.api.v1.evaluation.gate_action",
            new=AsyncMock(return_value=MagicMock()),
            create=True,
        ),
    ):
        result = await delete_evaluation_run(
            run_id=run_id,
            request=MagicMock(),
            current_user=current_user,
            service=service,
            db=db,
        )

    assert result is None
    service.delete_run.assert_called_once_with(run_id)
