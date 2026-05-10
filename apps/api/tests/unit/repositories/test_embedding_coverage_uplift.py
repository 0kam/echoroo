"""Coverage uplift unit tests for ``echoroo.repositories.embedding``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers EmbeddingRepository methods
(create_batch, delete_by_run, get_by_recording) so the module clears the
85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.repositories.embedding import EmbeddingRepository


def _make_session() -> MagicMock:
    db = MagicMock()
    db.add_all = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_embedding(recording_id: object = None, detection_run_id: object = None) -> MagicMock:
    emb = MagicMock()
    emb.recording_id = recording_id or uuid4()
    emb.detection_run_id = detection_run_id or uuid4()
    emb.start_time = 0.0
    return emb


@pytest.mark.asyncio
async def test_create_batch_adds_all_and_flushes() -> None:
    """create_batch() calls session.add_all and flush (lines 31-33)."""
    db = _make_session()
    repo = EmbeddingRepository(db)
    e1 = _make_embedding()
    e2 = _make_embedding()
    result = await repo.create_batch([e1, e2])
    db.add_all.assert_called_once_with([e1, e2])
    db.flush.assert_awaited_once()
    assert result == [e1, e2]


@pytest.mark.asyncio
async def test_create_batch_empty_list_returns_empty() -> None:
    """create_batch() with empty list returns empty list (line 20)."""
    db = _make_session()
    repo = EmbeddingRepository(db)
    result = await repo.create_batch([])
    assert result == []


@pytest.mark.asyncio
async def test_delete_by_run_returns_rowcount() -> None:
    """delete_by_run() executes DELETE and returns rowcount (lines 44-47)."""
    db = _make_session()
    cursor = MagicMock()
    cursor.rowcount = 5
    db.execute = AsyncMock(return_value=cursor)

    repo = EmbeddingRepository(db)
    count = await repo.delete_by_run(uuid4())
    assert count == 5
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_by_run_returns_zero_when_none_deleted() -> None:
    """delete_by_run() returns 0 when no rows are deleted."""
    db = _make_session()
    cursor = MagicMock()
    cursor.rowcount = 0
    db.execute = AsyncMock(return_value=cursor)

    repo = EmbeddingRepository(db)
    count = await repo.delete_by_run(uuid4())
    assert count == 0


@pytest.mark.asyncio
async def test_get_by_recording_returns_list() -> None:
    """get_by_recording() returns list of embeddings (lines 58-63)."""
    db = _make_session()
    e1 = _make_embedding()
    e2 = _make_embedding()

    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [e1, e2]
    db.execute = AsyncMock(return_value=result_mock)

    repo = EmbeddingRepository(db)
    results = await repo.get_by_recording(uuid4())
    assert results == [e1, e2]
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_recording_empty_returns_empty_list() -> None:
    """get_by_recording() returns empty list when no embeddings exist."""
    db = _make_session()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result_mock)

    repo = EmbeddingRepository(db)
    results = await repo.get_by_recording(uuid4())
    assert results == []
