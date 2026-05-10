"""Coverage uplift unit tests for ``echoroo.repositories.note``.

Phase 17 §C medium-gap batch: targets ``create`` (lines 28),
``list_by_clip_annotation`` (lines 39, 44), and ``list_by_sound_event``
(lines 55, 60) so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.note import Note
from echoroo.repositories.note import NoteRepository


def _make_note() -> Note:
    obj = Note()
    obj.id = uuid4()  # type: ignore[assignment]
    return obj


@pytest.mark.asyncio
async def test_create_persists_and_returns() -> None:
    """create() persists + refreshes + returns (line 28)."""
    obj = _make_note()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = NoteRepository(db)
    created = await repo.create(obj)
    assert created is obj
    db.add.assert_called_once_with(obj)
    db.refresh.assert_awaited_once_with(obj, ["created_by"])


@pytest.mark.asyncio
async def test_list_by_clip_annotation_returns_rows() -> None:
    """list_by_clip_annotation returns scalar list (lines 39, 44)."""
    target = _make_note()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [target]
    result.scalars.return_value = scalars

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    repo = NoteRepository(db)
    rows = await repo.list_by_clip_annotation(uuid4())
    assert rows == [target]


@pytest.mark.asyncio
async def test_list_by_sound_event_returns_rows() -> None:
    """list_by_sound_event returns scalar list (lines 55, 60)."""
    target = _make_note()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = [target]
    result.scalars.return_value = scalars

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    repo = NoteRepository(db)
    rows = await repo.list_by_sound_event(uuid4())
    assert rows == [target]
