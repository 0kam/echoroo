"""Coverage uplift unit tests for ``echoroo.repositories.sound_event_annotation``.

Phase 17 §C medium-gap batch: targets ``get_by_id`` (line 31),
``list_by_clip_annotation`` (lines 44, 50), ``create`` (line 64),
``update`` (line 77), ``add_tag`` (line 93), and ``remove_tag``
(line 108) so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.sound_event_annotation import SoundEventAnnotation
from echoroo.repositories.sound_event_annotation import SoundEventAnnotationRepository


def _make_event() -> SoundEventAnnotation:
    obj = SoundEventAnnotation()
    obj.id = uuid4()  # type: ignore[assignment]
    return obj


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id returns the SQL scalar (line 31)."""
    target = _make_event()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = SoundEventAnnotationRepository(db)
    found = await repo.get_by_id(target.id)
    assert found is target


@pytest.mark.asyncio
async def test_list_by_clip_annotation_returns_rows() -> None:
    """list_by_clip_annotation returns scalar list (lines 44, 50)."""
    target = _make_event()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [target]
    result.scalars.return_value = scalars

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    repo = SoundEventAnnotationRepository(db)
    rows = await repo.list_by_clip_annotation(uuid4())
    assert rows == [target]


@pytest.mark.asyncio
async def test_create_persists_and_returns() -> None:
    """create() persists + refreshes + returns (line 64)."""
    obj = _make_event()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = SoundEventAnnotationRepository(db)
    created = await repo.create(obj)
    assert created is obj
    db.add.assert_called_once_with(obj)
    db.refresh.assert_awaited_once_with(obj, ["tags"])


@pytest.mark.asyncio
async def test_update_flushes_and_refreshes() -> None:
    """update() flushes + refreshes + returns (line 77)."""
    obj = _make_event()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = SoundEventAnnotationRepository(db)
    updated = await repo.update(obj)
    assert updated is obj
    db.refresh.assert_awaited_once_with(obj, ["tags"])


@pytest.mark.asyncio
async def test_add_tag_executes_insert() -> None:
    """add_tag executes insert + flush (line 93)."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    repo = SoundEventAnnotationRepository(db)
    await repo.add_tag(uuid4(), uuid4())
    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_tag_executes_delete() -> None:
    """remove_tag executes delete + flush (line 108)."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()

    repo = SoundEventAnnotationRepository(db)
    await repo.remove_tag(uuid4(), uuid4())
    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()
