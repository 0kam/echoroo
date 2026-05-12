"""Coverage uplift unit tests for ``echoroo.api.v1.search.annotations``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers create_search_annotation handler
including invalid source/status enum paths, duplicate check, and new annotation
creation path, so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1.search import annotations as mod
from echoroo.schemas.search import SearchAnnotationCreate


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    return user


def _make_db() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.execute = AsyncMock()
    return db


def _make_annotation_create(
    source: str = "similarity_search",
    review_status: str = "confirmed",
) -> SearchAnnotationCreate:
    return SearchAnnotationCreate(
        recording_id=uuid4(),
        tag_id=uuid4(),
        source=source,
        review_status=review_status,
        confidence=0.9,
        start_time=1.0,
        end_time=3.0,
        search_session_id=None,
    )


@pytest.mark.asyncio
async def test_create_search_annotation_raises_422_on_invalid_source() -> None:
    """create_search_annotation raises 422 when source is invalid (lines 71-74)."""
    user = _make_user()
    db = _make_db()
    request = _make_annotation_create(source="invalid_source_xyz")

    with (
        patch.object(mod, "check_project_access", AsyncMock()),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.create_search_annotation(
            project_id=uuid4(),
            request=request,
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Invalid source value" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_create_search_annotation_raises_422_on_invalid_review_status() -> None:
    """create_search_annotation raises 422 when review_status is invalid (lines 80-83)."""
    user = _make_user()
    db = _make_db()
    # Use valid source but invalid review_status
    request = _make_annotation_create(source="similarity_search", review_status="invalid_status_xyz")

    with (
        patch.object(mod, "check_project_access", AsyncMock()),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.create_search_annotation(
            project_id=uuid4(),
            request=request,
            current_user=user,
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "Invalid review_status value" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_create_search_annotation_returns_existing_when_duplicate() -> None:
    """create_search_annotation returns existing annotation when duplicate found (lines 110-112)."""
    user = _make_user()
    db = _make_db()
    request = _make_annotation_create()
    existing = MagicMock()

    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = existing
    db.execute = AsyncMock(return_value=duplicate_result)

    sentinel = MagicMock()

    with (
        patch.object(mod, "check_project_access", AsyncMock()),
        patch.object(mod, "_annotation_to_detection_response", return_value=sentinel),
    ):
        result = await mod.create_search_annotation(
            project_id=uuid4(),
            request=request,
            current_user=user,
            db=db,
        )

    assert result is sentinel


@pytest.mark.asyncio
async def test_create_search_annotation_creates_new_annotation() -> None:
    """create_search_annotation creates new annotation when no duplicate (lines 116-143)."""

    user = _make_user()
    db = _make_db()
    request = _make_annotation_create()

    # No duplicate found for the SELECT query
    duplicate_result = MagicMock()
    duplicate_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=duplicate_result)

    # We need to patch db.add, db.flush, db.refresh, db.commit
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    sentinel = MagicMock()

    with (
        patch.object(mod, "check_project_access", AsyncMock()),
        patch.object(mod, "_annotation_to_detection_response", return_value=sentinel),
    ):
        result = await mod.create_search_annotation(
            project_id=uuid4(),
            request=request,
            current_user=user,
            db=db,
        )

    assert result is sentinel
    db.add.assert_called_once()
    db.flush.assert_awaited()
    db.commit.assert_awaited_once()
