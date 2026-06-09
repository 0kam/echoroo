"""Coverage uplift unit tests for ``echoroo.repositories.note``."""

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
