"""Coverage uplift unit tests for ``echoroo.repositories.clip_annotation``.

Phase 17 §C medium-gap batch: targets ``get_by_id`` / ``get_by_task_id``
/ ``create`` / ``add_tag`` / ``remove_tag`` / ``_expire_clip_annotation``
/ ``update_review`` (lines 44, 58, 72, 89, 91, 106, 108, 134) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.clip_annotation import ClipAnnotation
from echoroo.repositories.clip_annotation import ClipAnnotationRepository


def _make_clip_annotation() -> ClipAnnotation:
    obj = ClipAnnotation()
    obj.id = uuid4()  # type: ignore[assignment]
    return obj


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id returns the scalar from the SQL result (line 44)."""
    target = _make_clip_annotation()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = ClipAnnotationRepository(db)
    found = await repo.get_by_id(target.id)
    assert found is target


@pytest.mark.asyncio
async def test_get_by_task_id_returns_scalar() -> None:
    """get_by_task_id returns the scalar from the SQL result (line 58)."""
    target = _make_clip_annotation()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = target
    db.execute = AsyncMock(return_value=result)

    repo = ClipAnnotationRepository(db)
    found = await repo.get_by_task_id(uuid4())
    assert found is target


@pytest.mark.asyncio
async def test_create_persists_and_returns_instance() -> None:
    """create() flushes + refreshes + returns the instance (line 72)."""
    obj = _make_clip_annotation()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = ClipAnnotationRepository(db)
    created = await repo.create(obj)
    assert created is obj
    db.add.assert_called_once_with(obj)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(obj, ["tags", "sound_events", "notes"])


@pytest.mark.asyncio
async def test_add_tag_executes_insert_and_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    """add_tag executes insert and triggers expire (lines 89, 91)."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    # sync_session.identity_map needs to be iterable.
    db.sync_session = MagicMock()
    db.sync_session.identity_map = MagicMock()
    db.sync_session.identity_map.values = MagicMock(return_value=[])

    repo = ClipAnnotationRepository(db)
    await repo.add_tag(uuid4(), uuid4())
    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_tag_executes_delete_and_expires() -> None:
    """remove_tag executes delete and triggers expire (lines 106, 108)."""
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.sync_session = MagicMock()
    db.sync_session.identity_map = MagicMock()
    db.sync_session.identity_map.values = MagicMock(return_value=[])

    repo = ClipAnnotationRepository(db)
    await repo.remove_tag(uuid4(), uuid4())
    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_expire_clip_annotation_calls_expire_on_match() -> None:
    """_expire_clip_annotation expires the matching cached object."""
    target = _make_clip_annotation()
    other = _make_clip_annotation()  # different id

    db = MagicMock()
    db.expire = MagicMock()
    db.sync_session = MagicMock()
    db.sync_session.identity_map = MagicMock()
    db.sync_session.identity_map.values = MagicMock(return_value=[other, target])

    repo = ClipAnnotationRepository(db)
    repo._expire_clip_annotation(target.id)
    db.expire.assert_called_once_with(target)


@pytest.mark.asyncio
async def test_update_review_flushes_and_refreshes() -> None:
    """update_review flushes + refreshes + returns the instance (line 134)."""
    obj = _make_clip_annotation()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = ClipAnnotationRepository(db)
    updated = await repo.update_review(obj)
    assert updated is obj
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(obj, ["tags", "sound_events", "notes"])
