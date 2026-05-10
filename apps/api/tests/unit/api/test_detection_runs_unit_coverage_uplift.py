"""Coverage uplift unit tests for ``echoroo.api.v1.detection_runs``.

Phase 17 §C medium-gap batch: targets ``get_detection_run_service``
(line 40), the route bodies on lines 160 (list), 198 (get), 234-237
(create), 273-276 (retry), 303-307 (cancel + available-models) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.api.v1 import detection_runs as mod


def test_get_detection_run_service_returns_service_instance() -> None:
    """get_detection_run_service constructs a DetectionRunService (line 40)."""
    db = MagicMock()
    svc = mod.get_detection_run_service(db)
    assert svc is not None


@pytest.mark.asyncio
async def test_list_detection_runs_delegates_to_service() -> None:
    """list_detection_runs gates + delegates to service.list_by_project."""
    sentinel = MagicMock()
    service = MagicMock()
    service.list_by_project = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = MagicMock()
    user.id = uuid4()

    project_id = uuid4()
    with patch.object(mod, "check_project_access", new=AsyncMock(return_value=None)):
        result = await mod.list_detection_runs(
            project_id=project_id,
            current_user=user,
            service=service,
            db=db,
            page=1,
            page_size=50,
            dataset_id=None,
        )
    assert result is sentinel
    service.list_by_project.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_detection_run_delegates_to_service() -> None:
    """get_detection_run gates + delegates to service.get."""
    sentinel = MagicMock()
    service = MagicMock()
    service.get = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = MagicMock()
    user.id = uuid4()

    project_id = uuid4()
    run_id = uuid4()
    with patch.object(mod, "check_project_access", new=AsyncMock(return_value=None)):
        result = await mod.get_detection_run(
            project_id=project_id,
            run_id=run_id,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is sentinel


@pytest.mark.asyncio
async def test_create_detection_run_delegates_to_service() -> None:
    """create_detection_run gates + delegates to service.create (lines 234-237)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.create = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = MagicMock()
    user.id = uuid4()
    project_id = uuid4()
    request = MagicMock()

    with patch.object(mod, "check_project_access", new=AsyncMock(return_value=None)):
        result = await mod.create_detection_run(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is sentinel
    service.create.assert_awaited_once_with(project_id=project_id, request=request)


@pytest.mark.asyncio
async def test_update_detection_run_commits_after_service() -> None:
    """update_detection_run gates + service.update + commits."""
    sentinel = MagicMock()
    service = MagicMock()
    service.update = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    user = MagicMock()
    user.id = uuid4()

    with patch.object(mod, "check_project_access", new=AsyncMock(return_value=None)):
        result = await mod.update_detection_run(
            project_id=uuid4(),
            run_id=uuid4(),
            request=MagicMock(),
            current_user=user,
            service=service,
            db=db,
        )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_detection_run_commits_after_service() -> None:
    """retry_detection_run gates + service.retry + commits (lines 273-276)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.retry = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    user = MagicMock()
    user.id = uuid4()

    with patch.object(mod, "check_project_access", new=AsyncMock(return_value=None)):
        result = await mod.retry_detection_run(
            project_id=uuid4(),
            run_id=uuid4(),
            current_user=user,
            service=service,
            db=db,
        )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_detection_run_commits_after_service() -> None:
    """cancel_detection_run gates + service.cancel + commits (lines 303-305)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.cancel = AsyncMock(return_value=sentinel)
    db = MagicMock()
    db.commit = AsyncMock()
    user = MagicMock()
    user.id = uuid4()

    with patch.object(mod, "check_project_access", new=AsyncMock(return_value=None)):
        result = await mod.cancel_detection_run(
            project_id=uuid4(),
            run_id=uuid4(),
            current_user=user,
            service=service,
            db=db,
        )
    assert result is sentinel
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_available_models_returns_response() -> None:
    """list_available_models returns AvailableModelsResponse (line 307)."""
    user = MagicMock()
    result = await mod.list_available_models(current_user=user)
    assert result is not None
    assert hasattr(result, "models")
