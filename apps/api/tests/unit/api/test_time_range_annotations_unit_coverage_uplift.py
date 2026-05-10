"""Coverage uplift unit tests for ``echoroo.api.v1.time_range_annotations``.

Phase 17 §C medium-gap batch: targets ``get_annotation_service``
(lines 34-38) and the three route bodies (lines 61, 74, 89) so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.api.v1 import time_range_annotations as mod


def test_get_annotation_service_returns_service_instance() -> None:
    """get_annotation_service constructs the TimeRangeAnnotationService (lines 34-38)."""
    db = MagicMock()
    svc = mod.get_annotation_service(db)
    assert svc is not None


@pytest.mark.asyncio
async def test_update_annotation_delegates_to_service() -> None:
    """update_annotation forwards args to service.update (line 61)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.update = AsyncMock(return_value=sentinel)
    user = MagicMock()
    annotation_id = uuid4()
    request = MagicMock()
    result = await mod.update_annotation(
        annotation_id=annotation_id,
        request=request,
        current_user=user,
        service=service,
    )
    assert result is sentinel
    service.update.assert_awaited_once_with(annotation_id, request)


@pytest.mark.asyncio
async def test_delete_annotation_delegates_to_service() -> None:
    """delete_annotation forwards id to service.delete (line 74)."""
    service = MagicMock()
    service.delete = AsyncMock()
    user = MagicMock()
    annotation_id = uuid4()
    result = await mod.delete_annotation(
        annotation_id=annotation_id,
        current_user=user,
        service=service,
    )
    assert result is None
    service.delete.assert_awaited_once_with(annotation_id)


@pytest.mark.asyncio
async def test_create_annotation_note_delegates_to_service() -> None:
    """create_annotation_note forwards args to service.create_note (line 89)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.create_note = AsyncMock(return_value=sentinel)
    user = MagicMock()
    user.id = uuid4()
    annotation_id = uuid4()
    request = MagicMock()
    result = await mod.create_annotation_note(
        annotation_id=annotation_id,
        request=request,
        current_user=user,
        service=service,
    )
    assert result is sentinel
    service.create_note.assert_awaited_once_with(
        annotation_id, user_id=user.id, request=request
    )
