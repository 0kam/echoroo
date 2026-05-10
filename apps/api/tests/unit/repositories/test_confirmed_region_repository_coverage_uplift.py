"""Coverage uplift unit tests for ``echoroo.repositories.confirmed_region``.

Phase 17 §C medium-gap batch: targets ``get_by_id`` (line 36),
``list_by_recording`` (lines 59, 61, 73, 75), and ``create`` (line 89)
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository


def _make_region() -> ConfirmedRegion:
    obj = ConfirmedRegion()
    obj.id = uuid4()  # type: ignore[assignment]
    return obj


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id returns the SQL scalar (line 36)."""
    target = _make_region()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = ConfirmedRegionRepository(db)
    found = await repo.get_by_id(target.id)
    assert found is target


@pytest.mark.asyncio
async def test_list_by_recording_returns_paginated_tuple() -> None:
    """list_by_recording returns rows + count (lines 59, 61, 73, 75)."""
    target = _make_region()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1

    list_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [target]
    list_result.scalars.return_value = scalars

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    repo = ConfirmedRegionRepository(db)
    rows, total = await repo.list_by_recording(uuid4(), page=2, page_size=10)
    assert rows == [target]
    assert total == 1
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_create_persists_and_returns() -> None:
    """create() persists + refreshes + returns (line 89)."""
    obj = _make_region()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = ConfirmedRegionRepository(db)
    created = await repo.create(obj)
    assert created is obj
    db.add.assert_called_once_with(obj)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(obj, ["recording", "reviewed_by"])
