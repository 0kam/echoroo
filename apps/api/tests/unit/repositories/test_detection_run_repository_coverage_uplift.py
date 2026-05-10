"""Coverage uplift unit tests for ``echoroo.repositories.detection_run``.

Phase 17 §C heavy-gap batch: targets ``get_by_id`` (line 36),
``exists_in_project`` (lines 40, 46), ``list_by_project`` (lines 68, 73,
75, 87, 89), ``create`` (line 103), and ``update`` (line 116) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.repositories.detection_run import DetectionRunRepository


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id() returns the loaded DetectionRun (line 36)."""
    expected = MagicMock()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = expected
    db.execute = AsyncMock(return_value=result)

    repo = DetectionRunRepository(db)
    assert await repo.get_by_id(uuid4()) is expected


@pytest.mark.asyncio
async def test_exists_in_project_true_when_row_present() -> None:
    """exists_in_project() returns True when the SELECT returns an id (lines 40, 46)."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid4()
    db.execute = AsyncMock(return_value=result)

    repo = DetectionRunRepository(db)
    assert await repo.exists_in_project(uuid4(), uuid4()) is True


@pytest.mark.asyncio
async def test_exists_in_project_false_when_absent() -> None:
    """exists_in_project() returns False when no row matches."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    repo = DetectionRunRepository(db)
    assert await repo.exists_in_project(uuid4(), uuid4()) is False


@pytest.mark.asyncio
async def test_list_by_project_paginates_and_filters_by_dataset() -> None:
    """list_by_project() filters by dataset_id and returns (rows, total) (lines 68, 73, 75, 87, 89)."""
    rows = [MagicMock(), MagicMock(), MagicMock()]
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 3
    page_result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = rows
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(side_effect=[count_result, page_result])

    repo = DetectionRunRepository(db)
    items, total = await repo.list_by_project(
        project_id=uuid4(),
        page=1,
        page_size=10,
        dataset_id=uuid4(),
    )
    assert items == rows
    assert total == 3
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_by_project_no_dataset_filter() -> None:
    """list_by_project() works with dataset_id=None (no extra WHERE)."""
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    page_result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = []
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(side_effect=[count_result, page_result])

    repo = DetectionRunRepository(db)
    items, total = await repo.list_by_project(project_id=uuid4())
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_create_persists_and_refreshes() -> None:
    """create() adds, flushes, refreshes the row (line 103)."""
    run = MagicMock()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = DetectionRunRepository(db)
    out = await repo.create(run)
    assert out is run
    db.add.assert_called_once_with(run)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_flushes_and_refreshes() -> None:
    """update() flushes and refreshes the row (line 116)."""
    run = MagicMock()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = DetectionRunRepository(db)
    out = await repo.update(run)
    assert out is run
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()
