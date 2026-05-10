"""Coverage uplift unit tests for ``echoroo.repositories.site``.

Phase 17 §C medium-gap batch: targets every public method body so the
module clears the 85% threshold without touching production code.
Missing lines per coverage.json: [27, 45, 60, 81, 100, 103, 111, 113,
127, 140].
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.site import Site
from echoroo.repositories.site import SiteRepository


def _make_site() -> Site:
    obj = Site()
    obj.id = uuid4()  # type: ignore[assignment]
    return obj


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id returns the SQL scalar (line 27)."""
    target = _make_site()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = SiteRepository(db)
    found = await repo.get_by_id(target.id)
    assert found is target


@pytest.mark.asyncio
async def test_get_by_id_with_stats_returns_scalar() -> None:
    """get_by_id_with_stats returns the SQL scalar (line 45)."""
    target = _make_site()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = SiteRepository(db)
    found = await repo.get_by_id_with_stats(target.id)
    assert found is target


@pytest.mark.asyncio
async def test_get_by_project_and_name_returns_scalar() -> None:
    """get_by_project_and_name returns the scalar (line 60)."""
    target = _make_site()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = SiteRepository(db)
    found = await repo.get_by_project_and_name(uuid4(), "site-1")
    assert found is target


@pytest.mark.asyncio
async def test_get_by_project_and_h3_returns_scalar() -> None:
    """get_by_project_and_h3 returns the scalar (line 81)."""
    target = _make_site()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = SiteRepository(db)
    found = await repo.get_by_project_and_h3(uuid4(), "8a283082aaaffff")
    assert found is target


@pytest.mark.asyncio
async def test_list_by_project_returns_paginated_tuple() -> None:
    """list_by_project returns rows + count (lines 100, 103, 111, 113)."""
    target = _make_site()

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    list_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [target]
    list_result.scalars.return_value = scalars

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[count_result, list_result])

    repo = SiteRepository(db)
    rows, total = await repo.list_by_project(uuid4(), page=1, page_size=20)
    assert rows == [target]
    assert total == 1


@pytest.mark.asyncio
async def test_create_persists_and_returns() -> None:
    """create() persists + refreshes + returns (line 127)."""
    obj = _make_site()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = SiteRepository(db)
    created = await repo.create(obj)
    assert created is obj
    db.add.assert_called_once_with(obj)
    db.refresh.assert_awaited_once_with(obj)


@pytest.mark.asyncio
async def test_update_flushes_and_refreshes() -> None:
    """update() flushes + refreshes + returns (line 140)."""
    obj = _make_site()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = SiteRepository(db)
    updated = await repo.update(obj)
    assert updated is obj
    db.refresh.assert_awaited_once_with(obj)
