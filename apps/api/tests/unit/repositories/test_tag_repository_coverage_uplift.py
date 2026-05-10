"""Coverage uplift unit tests for ``echoroo.repositories.tag``.

Phase 17 §C heavy-gap batch: targets ``get_by_id`` (line 35),
``get_by_id_in_project`` (line 53), ``list_by_project`` filter branches
(lines 93, 96, 105, 107), CRUD (lines 121, 134), ``find_by_name_and_category``
(line 159), ``get_or_create_species`` (lines 152, 185, 192-210) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.enums import TagCategory
from echoroo.repositories.tag import TagRepository


def _exec_returning(value: Any) -> AsyncMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id() returns the loaded Tag (line 35)."""
    tag = MagicMock()
    db = MagicMock()
    db.execute = _exec_returning(tag)
    repo = TagRepository(db)
    assert await repo.get_by_id(uuid4()) is tag


@pytest.mark.asyncio
async def test_get_by_id_in_project_returns_scalar() -> None:
    """get_by_id_in_project() returns the loaded Tag scoped to a project (line 53)."""
    tag = MagicMock()
    db = MagicMock()
    db.execute = _exec_returning(tag)
    repo = TagRepository(db)
    assert await repo.get_by_id_in_project(uuid4(), uuid4()) is tag


@pytest.mark.asyncio
async def test_list_by_project_with_category_and_search_paginates() -> None:
    """list_by_project() applies category + search filters and paginates (lines 93, 96, 105, 107)."""
    rows = [MagicMock(), MagicMock()]
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    page_result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = rows
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(side_effect=[count_result, page_result])

    repo = TagRepository(db)
    items, total = await repo.list_by_project(
        project_id=uuid4(),
        category=TagCategory.SPECIES,
        search="abc",
        page=1,
        page_size=10,
    )
    assert items == rows
    assert total == 2


@pytest.mark.asyncio
async def test_list_by_project_no_filters() -> None:
    """list_by_project() with no category/search still works."""
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    page_result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = []
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(side_effect=[count_result, page_result])
    repo = TagRepository(db)
    items, total = await repo.list_by_project(project_id=uuid4())
    assert items == []
    assert total == 0


@pytest.mark.asyncio
async def test_create_persists_and_refreshes() -> None:
    """create() adds, flushes, refreshes (line 121)."""
    tag = MagicMock()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = TagRepository(db)
    assert await repo.create(tag) is tag
    db.add.assert_called_once_with(tag)


@pytest.mark.asyncio
async def test_update_flushes_and_refreshes() -> None:
    """update() flushes and refreshes (line 134)."""
    tag = MagicMock()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = TagRepository(db)
    assert await repo.update(tag) is tag


@pytest.mark.asyncio
async def test_find_by_name_and_category_returns_scalar() -> None:
    """find_by_name_and_category() returns the matched Tag (line 159)."""
    tag = MagicMock()
    db = MagicMock()
    db.execute = _exec_returning(tag)
    repo = TagRepository(db)
    found = await repo.find_by_name_and_category(uuid4(), "x", TagCategory.SPECIES)
    assert found is tag


@pytest.mark.asyncio
async def test_get_or_create_species_returns_existing_when_present() -> None:
    """get_or_create_species() returns the existing Tag (lines 185, 192-197)."""
    existing = MagicMock()
    existing.taxon_id = None
    db = MagicMock()
    db.execute = _exec_returning(existing)
    db.flush = AsyncMock()
    repo = TagRepository(db)
    out = await repo.get_or_create_species(
        project_id=uuid4(),
        scientific_name="Turdus merula",
        common_name="Eurasian Blackbird",
        taxon_id=uuid4(),
    )
    assert out is existing
    db.flush.assert_awaited_once()  # taxon link update


@pytest.mark.asyncio
async def test_get_or_create_species_creates_when_absent() -> None:
    """get_or_create_species() creates a new Tag when no row matches (lines 199-210)."""
    db = MagicMock()
    db.execute = _exec_returning(None)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = TagRepository(db)
    out = await repo.get_or_create_species(
        project_id=uuid4(),
        scientific_name="Turdus merula",
        common_name="Eurasian Blackbird",
    )
    assert out is not None
    db.add.assert_called_once()
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()
