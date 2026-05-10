"""Coverage uplift unit tests for ``echoroo.repositories.annotation_project``.

Phase 17 §C heavy-gap batch: targets ``get_by_id`` (line 36),
``list_by_project`` (lines 60, 63, 75, 77), ``create`` (line 91),
``update`` (line 104), and ``get_progress`` (lines 119, 146-148) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.repositories.annotation_project import AnnotationProjectRepository


def _make_db(*, scalar_value: Any = None, scalars_list: list[Any] | None = None) -> MagicMock:
    """Build an AsyncSession stub that supports execute / add / flush / refresh."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    result.scalar_one.return_value = scalar_value
    scalars_list = scalars_list or []
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = scalars_list
    result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar(
) -> None:
    """get_by_id() returns the SQL scalar result (line 36)."""
    expected = MagicMock()
    db = _make_db(scalar_value=expected)
    repo = AnnotationProjectRepository(db)
    found = await repo.get_by_id(uuid4())
    assert found is expected


@pytest.mark.asyncio
async def test_get_by_id_returns_none_when_missing() -> None:
    """get_by_id() returns None when no row matches."""
    db = _make_db(scalar_value=None)
    repo = AnnotationProjectRepository(db)
    assert await repo.get_by_id(uuid4()) is None


@pytest.mark.asyncio
async def test_list_by_project_returns_paginated_tuple() -> None:
    """list_by_project() returns (rows, total) (lines 60, 63, 75, 77)."""
    rows = [MagicMock(), MagicMock()]
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    page_result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = rows
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(side_effect=[count_result, page_result])

    repo = AnnotationProjectRepository(db)
    items, total = await repo.list_by_project(uuid4(), page=2, page_size=5)
    assert items == rows
    assert total == 2
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_create_persists_and_refreshes() -> None:
    """create() adds, flushes, and refreshes the row (line 91)."""
    project = MagicMock()
    db = _make_db()
    repo = AnnotationProjectRepository(db)
    out = await repo.create(project)
    assert out is project
    db.add.assert_called_once_with(project)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_flushes_and_refreshes() -> None:
    """update() flushes and refreshes the existing row (line 104)."""
    project = MagicMock()
    db = _make_db()
    repo = AnnotationProjectRepository(db)
    out = await repo.update(project)
    assert out is project
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_progress_returns_status_buckets() -> None:
    """get_progress() returns the five-bucket status histogram (lines 119, 146-148)."""
    db = MagicMock()
    row = MagicMock()
    row.total_tasks = 10
    row.completed_tasks = 4
    row.in_progress_tasks = 2
    row.pending_tasks = 3
    row.review_pending_tasks = 1
    result = MagicMock()
    result.one.return_value = row
    db.execute = AsyncMock(return_value=result)

    repo = AnnotationProjectRepository(db)
    progress = await repo.get_progress(uuid4())
    assert progress == {
        "total_tasks": 10,
        "completed_tasks": 4,
        "in_progress_tasks": 2,
        "pending_tasks": 3,
        "review_pending_tasks": 1,
    }
