"""Coverage uplift unit tests for ``echoroo.api.v1.annotations``.

Phase 17 §C easy-win batch 1: covers the ``remove_clip_tag`` 404 + happy
branches (lines 142-149), ``list_sound_events`` (lines 178-179), and the
``add_sound_event_tag`` / ``remove_sound_event_tag`` empty-dict returns
(lines 304, 337) using mocked services so the module clears the 85%
threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.v1 import annotations as mod
from echoroo.schemas.annotation import AddTagRequest


def _build_service_with_clip_annotation(updated: object | None) -> MagicMock:
    service = MagicMock()
    service.remove_clip_tag = AsyncMock()
    service.clip_annotation_repo = MagicMock()
    service.clip_annotation_repo.get_by_id = AsyncMock(return_value=updated)
    return service


@pytest.mark.asyncio
async def test_remove_clip_tag_returns_404_when_missing() -> None:
    """remove_clip_tag() raises 404 when the post-delete fetch yields None
    (lines 142-148).
    """
    service = _build_service_with_clip_annotation(None)
    current_user = MagicMock()

    with pytest.raises(HTTPException) as excinfo:
        await mod.remove_clip_tag(
            project_id=uuid4(),
            clip_annotation_id=uuid4(),
            tag_id=uuid4(),
            current_user=current_user,
            service=service,
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_remove_clip_tag_returns_validated_response_when_present() -> None:
    """remove_clip_tag() validates the updated clip annotation (line 149)."""
    fake_annotation = MagicMock()
    service = _build_service_with_clip_annotation(fake_annotation)
    current_user = MagicMock()

    with patch.object(
        mod.ClipAnnotationDetailResponse, "model_validate", return_value="VALIDATED"
    ):
        result = await mod.remove_clip_tag(
            project_id=uuid4(),
            clip_annotation_id=uuid4(),
            tag_id=uuid4(),
            current_user=current_user,
            service=service,
        )
    assert result == "VALIDATED"


@pytest.mark.asyncio
async def test_list_sound_events_returns_validated_responses() -> None:
    """list_sound_events() returns the validated SoundEventAnnotationResponse list
    (lines 178-179).
    """
    fake_se = MagicMock()
    service = MagicMock()
    service.sound_event_repo = MagicMock()
    service.sound_event_repo.list_by_clip_annotation = AsyncMock(
        return_value=[fake_se, fake_se]
    )
    current_user = MagicMock()

    with patch.object(
        mod.SoundEventAnnotationResponse, "model_validate", return_value="SE"
    ):
        result = await mod.list_sound_events(
            project_id=uuid4(),
            clip_annotation_id=uuid4(),
            current_user=current_user,
            service=service,
        )
    assert result == ["SE", "SE"]


@pytest.mark.asyncio
async def test_add_sound_event_tag_returns_empty_dict() -> None:
    """add_sound_event_tag() returns {} after delegating to the service (line 304)."""
    service = MagicMock()
    service.add_sound_event_tag = AsyncMock()
    current_user = MagicMock()
    request = AddTagRequest(tag_id=uuid4())

    result = await mod.add_sound_event_tag(
        project_id=uuid4(),
        sound_event_id=uuid4(),
        request=request,
        current_user=current_user,
        service=service,
    )
    assert result == {}
    service.add_sound_event_tag.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_sound_event_tag_returns_empty_dict() -> None:
    """remove_sound_event_tag() returns {} after delegating to the service
    (line 337).
    """
    service = MagicMock()
    service.remove_sound_event_tag = AsyncMock()
    current_user = MagicMock()

    result = await mod.remove_sound_event_tag(
        project_id=uuid4(),
        sound_event_id=uuid4(),
        tag_id=uuid4(),
        current_user=current_user,
        service=service,
    )
    assert result == {}
    service.remove_sound_event_tag.assert_awaited_once()
