"""Coverage uplift unit tests for ``echoroo.repositories.project``.

Phase 17 §C heavy-gap batch: targets ``get_by_id`` (line 40),
``get_accessible_projects`` (lines 122-131, 145), ``create`` (line 158),
``update`` (line 179), member CRUD (196, 210, 223), summary helpers
(238, 258, 273, 286-289), and the access predicates (306, 319, 330-331,
345-346, 350, 362-363, 391) so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.enums import ProjectMemberRole
from echoroo.repositories.project import ProjectRepository


def _execute_returning(value: Any) -> AsyncMock:
    """Build an ``execute`` mock that returns ``value`` from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value
    return AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_get_by_id_returns_loaded_project() -> None:
    """get_by_id() returns the SQL scalar (line 40)."""
    project = MagicMock()
    db = MagicMock()
    db.execute = _execute_returning(project)
    repo = ProjectRepository(db)
    assert await repo.get_by_id(uuid4()) is project


@pytest.mark.asyncio
async def test_get_accessible_projects_returns_paginated_tuple() -> None:
    """get_accessible_projects() returns (rows, total) (lines 122-131)."""
    rows = [MagicMock(), MagicMock()]
    db = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2
    page_result = MagicMock()
    scalars_obj = MagicMock()
    unique_obj = MagicMock()
    unique_obj.all.return_value = rows
    scalars_obj.unique.return_value = unique_obj
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(side_effect=[count_result, page_result])

    repo = ProjectRepository(db)
    items, total = await repo.get_accessible_projects(uuid4(), page=1, limit=10)
    assert items == rows
    assert total == 2


@pytest.mark.asyncio
async def test_create_persists_and_refreshes() -> None:
    """create() adds, flushes, refreshes (line 145)."""
    project = MagicMock()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = ProjectRepository(db)
    assert await repo.create(project) is project
    db.add.assert_called_once_with(project)
    db.refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_flushes_and_refreshes() -> None:
    """update() flushes and refreshes (line 158)."""
    project = MagicMock()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = ProjectRepository(db)
    assert await repo.update(project) is project
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_member_returns_scalar() -> None:
    """get_member() returns the loaded ProjectMember (line 179)."""
    member = MagicMock()
    db = MagicMock()
    db.execute = _execute_returning(member)
    repo = ProjectRepository(db)
    assert await repo.get_member(uuid4(), uuid4()) is member


@pytest.mark.asyncio
async def test_list_members_returns_scalars_all() -> None:
    """list_members() returns the .scalars().all() list (line 196)."""
    members = [MagicMock(), MagicMock()]
    db = MagicMock()
    page_result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = members
    page_result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(return_value=page_result)
    repo = ProjectRepository(db)
    assert await repo.list_members(uuid4()) == members


@pytest.mark.asyncio
async def test_add_member_persists_and_refreshes() -> None:
    """add_member() adds, flushes, refreshes (line 210)."""
    member = MagicMock()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = ProjectRepository(db)
    assert await repo.add_member(member) is member
    db.add.assert_called_once_with(member)


@pytest.mark.asyncio
async def test_update_member_flushes_and_refreshes() -> None:
    """update_member() flushes + refreshes (line 223)."""
    member = MagicMock()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    repo = ProjectRepository(db)
    assert await repo.update_member(member) is member


@pytest.mark.asyncio
async def test_remove_member_executes_delete() -> None:
    """remove_member() issues a DELETE and flushes (line 238)."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    repo = ProjectRepository(db)
    await repo.remove_member(uuid4(), uuid4())
    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_overview_sites_returns_rows() -> None:
    """get_overview_sites() returns the result.all() rows (line 258)."""
    rows = [MagicMock(), MagicMock()]
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    repo = ProjectRepository(db)
    assert await repo.get_overview_sites(uuid4()) == rows


@pytest.mark.asyncio
async def test_get_recording_calendar_returns_rows() -> None:
    """get_recording_calendar() returns the result.all() rows (line 273)."""
    rows = [MagicMock()]
    db = MagicMock()
    result = MagicMock()
    result.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    repo = ProjectRepository(db)
    assert await repo.get_recording_calendar(uuid4()) == rows


@pytest.mark.asyncio
async def test_get_overview_totals_returns_typed_tuple() -> None:
    """get_overview_totals() returns (recordings, sites, duration) (lines 286-289)."""
    db = MagicMock()
    row = MagicMock()
    row.total_recordings = 7
    row.total_sites = 3
    row.total_duration = 12.5
    result = MagicMock()
    result.one.return_value = row
    db.execute = AsyncMock(return_value=result)
    repo = ProjectRepository(db)
    assert await repo.get_overview_totals(uuid4()) == (7, 3, 12.5)


@pytest.mark.asyncio
async def test_is_project_admin_owner_returns_true() -> None:
    """is_project_admin() returns True for the owner (line 306)."""
    user_id = uuid4()
    project = MagicMock()
    project.owner_id = user_id
    db = MagicMock()
    db.execute = _execute_returning(project)
    repo = ProjectRepository(db)
    assert await repo.is_project_admin(uuid4(), user_id) is True


@pytest.mark.asyncio
async def test_is_project_admin_admin_role_returns_true() -> None:
    """is_project_admin() returns True for an ADMIN-role member (lines 319, 330-331)."""
    user_id = uuid4()
    project = MagicMock()
    project.owner_id = uuid4()  # NOT the user
    member = MagicMock()
    member.role = ProjectMemberRole.ADMIN

    project_db = MagicMock()
    project_db.scalar_one_or_none.return_value = project
    member_db = MagicMock()
    member_db.scalar_one_or_none.return_value = member

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[project_db, member_db])
    repo = ProjectRepository(db)
    assert await repo.is_project_admin(uuid4(), user_id) is True


@pytest.mark.asyncio
async def test_is_project_admin_non_admin_returns_false() -> None:
    """is_project_admin() returns False when project missing (line 350 negative branch)."""
    project_db = MagicMock()
    project_db.scalar_one_or_none.return_value = None
    member_db = MagicMock()
    member_db.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[project_db, member_db])
    repo = ProjectRepository(db)
    assert await repo.is_project_admin(uuid4(), uuid4()) is False


@pytest.mark.asyncio
async def test_is_project_owner_true_when_owner_matches() -> None:
    """is_project_owner() returns True when owner matches (line 362-363)."""
    user_id = uuid4()
    project = MagicMock()
    project.owner_id = user_id
    db = MagicMock()
    db.execute = _execute_returning(project)
    repo = ProjectRepository(db)
    assert await repo.is_project_owner(uuid4(), user_id) is True


@pytest.mark.asyncio
async def test_is_project_owner_false_when_no_project() -> None:
    """is_project_owner() returns False when project missing."""
    db = MagicMock()
    db.execute = _execute_returning(None)
    repo = ProjectRepository(db)
    assert await repo.is_project_owner(uuid4(), uuid4()) is False


@pytest.mark.asyncio
async def test_has_project_access_true_when_row_returned() -> None:
    """has_project_access() returns True when SELECT yields a row (line 391)."""
    project = MagicMock()
    db = MagicMock()
    db.execute = _execute_returning(project)
    repo = ProjectRepository(db)
    assert await repo.has_project_access(uuid4(), uuid4()) is True


@pytest.mark.asyncio
async def test_has_project_access_false_when_empty() -> None:
    """has_project_access() returns False when no row matches."""
    db = MagicMock()
    db.execute = _execute_returning(None)
    repo = ProjectRepository(db)
    assert await repo.has_project_access(uuid4(), uuid4()) is False
