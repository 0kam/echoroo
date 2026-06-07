"""Coverage uplift unit tests for ``echoroo.api.v1.annotation_sets``.

Phase 17 §C medium-gap batch: targets ``get_annotation_set_service``
(line 43), and the route bodies on lines 85, 105, 118, 132, 145, 164,
185, 211, 225 so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.api.v1 import annotation_sets as mod


def _pagination(page: int = 1, page_size: int = 20) -> MagicMock:
    p = MagicMock()
    p.page = page
    p.page_size = page_size
    return p


def test_get_annotation_set_service_returns_service_instance() -> None:
    """get_annotation_set_service constructs an AnnotationSetService (line 43)."""
    db = MagicMock()
    svc = mod.get_annotation_set_service(db)
    assert svc is not None


@pytest.mark.asyncio
async def test_list_annotation_sets_delegates_to_service() -> None:
    """list_annotation_sets forwards filters + pagination (line 85)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.list = AsyncMock(return_value=sentinel)
    user = MagicMock()
    project_id = uuid4()

    result = await mod.list_annotation_sets(
        current_user=user,
        service=service,
        pagination=_pagination(),
        project_id=project_id,
        dataset_id=None,
        status_filter=None,
    )
    assert result is sentinel
    service.list.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_annotation_set_delegates_to_service() -> None:
    """create_annotation_set forwards user_id + request (line 105)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.create = AsyncMock(return_value=sentinel)
    user = MagicMock()
    user.id = uuid4()
    request = MagicMock()
    result = await mod.create_annotation_set(
        request=request, current_user=user, service=service
    )
    assert result is sentinel
    service.create.assert_awaited_once_with(user_id=user.id, request=request)


@pytest.mark.asyncio
async def test_get_annotation_set_delegates_to_service() -> None:
    """get_annotation_set forwards id (line 118)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.get_detail = AsyncMock(return_value=sentinel)
    user = MagicMock()
    set_id = uuid4()
    result = await mod.get_annotation_set(
        set_id=set_id, current_user=user, service=service, locale="en"
    )
    assert result is sentinel
    service.get_detail.assert_awaited_once_with(set_id, locale="en")


@pytest.mark.asyncio
async def test_update_annotation_set_delegates_to_service() -> None:
    """update_annotation_set forwards id + request (line 132)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.update = AsyncMock(return_value=sentinel)
    user = MagicMock()
    set_id = uuid4()
    request = MagicMock()
    result = await mod.update_annotation_set(
        set_id=set_id, request=request, current_user=user, service=service
    )
    assert result is sentinel
    service.update.assert_awaited_once_with(set_id, request)


@pytest.mark.asyncio
async def test_delete_annotation_set_delegates_to_service() -> None:
    """delete_annotation_set delegates to service.delete (line 145)."""
    service = MagicMock()
    service.delete = AsyncMock()
    user = MagicMock()
    set_id = uuid4()
    result = await mod.delete_annotation_set(
        set_id=set_id, current_user=user, service=service
    )
    assert result is None
    service.delete.assert_awaited_once_with(set_id)


@pytest.mark.asyncio
async def test_dispatch_sampling_delegates_to_service() -> None:
    """dispatch_sampling forwards id (line 164)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.dispatch_sample = AsyncMock(return_value=sentinel)
    user = MagicMock()
    set_id = uuid4()
    result = await mod.dispatch_sampling(
        set_id=set_id, current_user=user, service=service
    )
    assert result is sentinel
    service.dispatch_sample.assert_awaited_once_with(set_id)


@pytest.mark.asyncio
async def test_list_set_segments_delegates_to_service() -> None:
    """list_set_segments forwards filters + pagination (line 185)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.list_segments = AsyncMock(return_value=sentinel)
    user = MagicMock()
    set_id = uuid4()
    result = await mod.list_set_segments(
        set_id=set_id,
        current_user=user,
        service=service,
        pagination=_pagination(page=2, page_size=50),
        status_filter=None,
        is_empty=None,
    )
    assert result is sentinel
    service.list_segments.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_palette_species_delegates_to_service() -> None:
    """add_palette_species forwards id + request (line 211)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.add_palette = AsyncMock(return_value=sentinel)
    user = MagicMock()
    set_id = uuid4()
    request = MagicMock()
    result = await mod.add_palette_species(
        set_id=set_id, request=request, current_user=user, service=service
    )
    assert result is sentinel
    service.add_palette.assert_awaited_once_with(set_id, request)


@pytest.mark.asyncio
async def test_remove_palette_species_delegates_to_service() -> None:
    """remove_palette_species forwards both ids (line 225)."""
    service = MagicMock()
    service.remove_palette = AsyncMock()
    user = MagicMock()
    set_id = uuid4()
    species_id = uuid4()
    result = await mod.remove_palette_species(
        set_id=set_id,
        species_id=species_id,
        current_user=user,
        service=service,
    )
    assert result is None
    service.remove_palette.assert_awaited_once_with(set_id, species_id)
