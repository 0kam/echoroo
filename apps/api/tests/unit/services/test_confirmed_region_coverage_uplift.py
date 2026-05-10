"""Coverage uplift unit tests for ``echoroo.services.confirmed_region``.

Phase 17 §C easy-win batch 1: covers the ``create`` and ``delete`` happy
paths plus the not-found branch (lines 84, 96) using mocked repositories
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.services.confirmed_region import ConfirmedRegionService


def _make_region(**overrides: object) -> ConfirmedRegion:
    """Build a ConfirmedRegion ORM instance with sane defaults."""
    region_id = overrides.pop("id", uuid4())
    recording_id = overrides.pop("recording_id", uuid4())
    reviewed_by_id = overrides.pop("reviewed_by_id", uuid4())
    region = ConfirmedRegion(
        recording_id=recording_id,
        start_time=0.0,
        end_time=3.0,
        reviewed_by_id=reviewed_by_id,
    )
    # Patch ID + audit fields so model_validate doesn't fail.
    region.id = region_id  # type: ignore[assignment]
    now = datetime.now(UTC)
    region.created_at = now  # type: ignore[assignment]
    region.updated_at = now  # type: ignore[assignment]
    return region


@pytest.mark.asyncio
async def test_delete_raises_404_when_region_not_found() -> None:
    """delete() raises HTTPException(404) when repo returns None."""
    repo = AsyncMock()
    repo.get_by_id.return_value = None
    service = ConfirmedRegionService(repo)
    region_id = uuid4()

    with pytest.raises(HTTPException) as excinfo:
        await service.delete(region_id)
    assert excinfo.value.status_code == 404
    repo.get_by_id.assert_awaited_once_with(region_id)
    repo.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_invokes_repo_when_region_exists() -> None:
    """delete() forwards to the repo when the region exists (line 96 unreachable)."""
    region = _make_region()
    repo = AsyncMock()
    repo.get_by_id.return_value = region
    service = ConfirmedRegionService(repo)

    await service.delete(region.id)

    repo.delete.assert_awaited_once_with(region.id)


@pytest.mark.asyncio
async def test_create_returns_response_for_valid_request() -> None:
    """create() returns a ConfirmedRegionResponse from the new region (line 84)."""
    from echoroo.schemas.confirmed_region import ConfirmedRegionCreate

    user_id = uuid4()
    recording_id = uuid4()
    request = ConfirmedRegionCreate(
        recording_id=recording_id,
        start_time=1.0,
        end_time=2.0,
    )
    created = _make_region(recording_id=recording_id, reviewed_by_id=user_id)
    repo = AsyncMock()
    repo.create.return_value = created

    service = ConfirmedRegionService(repo)
    response = await service.create(request, user_id=user_id)

    assert response.id == created.id
    repo.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_by_recording_returns_paginated_response() -> None:
    """list_by_recording() returns a paginated ConfirmedRegionListResponse."""
    recording_id = uuid4()
    region = _make_region(recording_id=recording_id)
    repo = AsyncMock()
    repo.list_by_recording.return_value = ([region], 1)

    service = ConfirmedRegionService(repo)
    response = await service.list_by_recording(recording_id)

    assert response.total == 1
    assert len(response.items) == 1
    assert response.items[0].id == region.id
