"""Unit tests for SiteService H3 resolution handling."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import h3
import pytest

from echoroo.schemas.site import SiteCreate, SiteUpdate
from echoroo.services.site import SiteService


def _site_namespace(
    *,
    project_id: object,
    name: str,
    h3_index_member: str,
    h3_index_member_resolution: int,
) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid4(),
        project_id=project_id,
        name=name,
        h3_index_member=h3_index_member,
        h3_index_member_resolution=h3_index_member_resolution,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_create_site_accepts_h3_resolution_5() -> None:
    project_id = uuid4()
    user_id = uuid4()
    h3_cell = h3.latlng_to_cell(35.681236, 139.767125, 5)

    site_repo = MagicMock()
    site_repo.get_by_project_and_name = AsyncMock(return_value=None)
    site_repo.get_by_project_and_h3 = AsyncMock(return_value=None)
    site_repo.create = AsyncMock(
        return_value=_site_namespace(
            project_id=project_id,
            name="Resolution 5 Site",
            h3_index_member=h3_cell,
            h3_index_member_resolution=5,
        )
    )
    project_repo = MagicMock()
    project_repo.is_project_admin = AsyncMock(return_value=True)

    response = await SiteService(site_repo, project_repo).create_site(
        user_id,
        project_id,
        SiteCreate(name="Resolution 5 Site", h3_index_member=h3_cell),
    )

    assert response.h3_index_member == h3_cell
    assert response.h3_index_member_resolution == 5
    created_arg = site_repo.create.await_args.args[0]
    assert created_arg.h3_index_member_resolution == 5


@pytest.mark.asyncio
async def test_update_site_accepts_h3_resolution_10() -> None:
    project_id = uuid4()
    user_id = uuid4()
    site_id = uuid4()
    original_cell = h3.latlng_to_cell(35.681236, 139.767125, 15)
    updated_cell = h3.latlng_to_cell(35.681236, 139.767125, 10)
    existing_site = _site_namespace(
        project_id=project_id,
        name="Resolution Update Site",
        h3_index_member=original_cell,
        h3_index_member_resolution=15,
    )
    existing_site.id = site_id

    site_repo = MagicMock()
    site_repo.get_by_id = AsyncMock(return_value=existing_site)
    site_repo.get_by_project_and_h3 = AsyncMock(return_value=None)
    site_repo.update = AsyncMock(return_value=existing_site)
    project_repo = MagicMock()
    project_repo.is_project_admin = AsyncMock(return_value=True)

    response = await SiteService(site_repo, project_repo).update_site(
        user_id,
        project_id,
        site_id,
        SiteUpdate(h3_index_member=updated_cell),
    )

    assert response.h3_index_member == updated_cell
    assert response.h3_index_member_resolution == 10
    site_repo.update.assert_awaited_once_with(existing_site)
