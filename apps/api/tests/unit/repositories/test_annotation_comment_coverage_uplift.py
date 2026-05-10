"""Coverage uplift unit tests for ``echoroo.repositories.annotation_comment``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers list_by_annotation, create,
and get_by_id_in_project methods so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.enums import AnnotationVoteSource
from echoroo.repositories.annotation_comment import AnnotationCommentRepository


def _make_db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_by_annotation_returns_comments() -> None:
    """list_by_annotation() queries and returns ordered comments (lines 25, 33)."""
    db = _make_db()
    comment = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [comment]
    db.execute = AsyncMock(return_value=result)

    repo = AnnotationCommentRepository(db)
    comments = await repo.list_by_annotation(uuid4(), uuid4())
    assert comments == [comment]
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_by_annotation_empty_returns_empty_list() -> None:
    """list_by_annotation() returns empty list when no comments found."""
    db = _make_db()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    repo = AnnotationCommentRepository(db)
    comments = await repo.list_by_annotation(uuid4(), uuid4())
    assert comments == []


@pytest.mark.asyncio
async def test_create_adds_and_returns_comment() -> None:
    """create() creates and returns an AnnotationComment (lines 44-54)."""
    db = _make_db()
    annotation_id = uuid4()
    project_id = uuid4()
    user_id = uuid4()
    body = "Test comment"
    source = AnnotationVoteSource.MEMBER

    # We need to capture what was passed to db.add
    added_objects: list[object] = []
    db.add = MagicMock(side_effect=added_objects.append)

    repo = AnnotationCommentRepository(db)
    await repo.create(
        annotation_id=annotation_id,
        project_id=project_id,
        commenter_user_id=user_id,
        body=body,
        source=source,
    )

    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once()
    assert len(added_objects) == 1


@pytest.mark.asyncio
async def test_get_by_id_in_project_returns_comment_when_found() -> None:
    """get_by_id_in_project() returns comment when it exists (lines 62-68)."""
    db = _make_db()
    comment = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = comment
    db.execute = AsyncMock(return_value=result)

    repo = AnnotationCommentRepository(db)
    found = await repo.get_by_id_in_project(uuid4(), uuid4())
    assert found is comment


@pytest.mark.asyncio
async def test_get_by_id_in_project_returns_none_when_not_found() -> None:
    """get_by_id_in_project() returns None when comment not found (line 68)."""
    db = _make_db()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    repo = AnnotationCommentRepository(db)
    found = await repo.get_by_id_in_project(uuid4(), uuid4())
    assert found is None
