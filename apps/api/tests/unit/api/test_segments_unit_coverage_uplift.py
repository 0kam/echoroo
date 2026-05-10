"""Coverage uplift unit tests for ``echoroo.api.v1.segments``.

Phase 17 §C medium-gap batch: targets ``get_segment_service``
(lines 35-39) and the four route bodies (lines 59, 73, 90, 107) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.api.v1 import segments as mod


def test_get_segment_service_returns_service_instance() -> None:
    """get_segment_service constructs an AnnotationSegmentService (lines 35-39)."""
    db = MagicMock()
    svc = mod.get_segment_service(db)
    assert svc is not None


@pytest.mark.asyncio
async def test_get_segment_delegates_to_service() -> None:
    """get_segment forwards segment_id to service.get_detail (line 59)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.get_detail = AsyncMock(return_value=sentinel)
    user = MagicMock()
    segment_id = uuid4()
    result = await mod.get_segment(segment_id=segment_id, current_user=user, service=service)
    assert result is sentinel
    service.get_detail.assert_awaited_once_with(segment_id)


@pytest.mark.asyncio
async def test_update_segment_delegates_to_service() -> None:
    """update_segment forwards args to service.update (line 73)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.update = AsyncMock(return_value=sentinel)
    user = MagicMock()
    user.id = uuid4()
    segment_id = uuid4()
    request = MagicMock()
    result = await mod.update_segment(
        segment_id=segment_id,
        request=request,
        current_user=user,
        service=service,
    )
    assert result is sentinel
    service.update.assert_awaited_once_with(segment_id, user_id=user.id, request=request)


@pytest.mark.asyncio
async def test_create_annotation_delegates_to_service() -> None:
    """create_annotation forwards args to service.create_annotation (line 90)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.create_annotation = AsyncMock(return_value=sentinel)
    user = MagicMock()
    user.id = uuid4()
    segment_id = uuid4()
    request = MagicMock()
    result = await mod.create_annotation(
        segment_id=segment_id,
        request=request,
        current_user=user,
        service=service,
    )
    assert result is sentinel
    service.create_annotation.assert_awaited_once_with(
        segment_id, user_id=user.id, request=request
    )


@pytest.mark.asyncio
async def test_create_segment_note_delegates_to_service() -> None:
    """create_segment_note forwards args to service.create_note (line 107)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.create_note = AsyncMock(return_value=sentinel)
    user = MagicMock()
    user.id = uuid4()
    segment_id = uuid4()
    request = MagicMock()
    result = await mod.create_segment_note(
        segment_id=segment_id,
        request=request,
        current_user=user,
        service=service,
    )
    assert result is sentinel
    service.create_note.assert_awaited_once_with(
        segment_id, user_id=user.id, request=request
    )
