"""Coverage uplift unit tests for ``echoroo.services.recording``.

Phase 17 §C heavy-gap batch: targets the ``__init__`` audio_service path
(line 40 already covered indirectly), the ``update`` partial-update
branches (lines 136-142), and the ``delete`` not-found path (lines 156-160)
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.recording import Recording
from echoroo.services.recording import RecordingService


def _make_recording(*, time_expansion: float = 1.0, note: str | None = None) -> Recording:
    """Build a minimal Recording suitable for unit-level service tests."""
    rec = Recording(
        dataset_id=uuid4(),
        path="recordings/test.wav",
        filename="test.wav",
        duration=30.0,
        samplerate=48_000,
        time_expansion=time_expansion,
        note=note,
    )
    rec.id = uuid4()  # type: ignore[assignment]
    return rec


@pytest.mark.asyncio
async def test_update_returns_none_when_recording_missing() -> None:
    """update() short-circuits to None when the row does not exist (line 136)."""
    service = RecordingService(MagicMock())
    service.repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    result = await service.update(uuid4(), time_expansion=2.0, note="changed")
    assert result is None


@pytest.mark.asyncio
async def test_update_assigns_time_expansion_and_note_when_provided() -> None:
    """Both time_expansion and note are persisted when supplied (lines 137-142)."""
    rec = _make_recording(time_expansion=1.0, note="old")
    service = RecordingService(MagicMock())
    service.repo.get_by_id = AsyncMock(return_value=rec)  # type: ignore[method-assign]
    service.repo.update = AsyncMock(return_value=rec)  # type: ignore[method-assign]

    result = await service.update(rec.id, time_expansion=2.5, note="new note")
    assert result is rec
    assert rec.time_expansion == 2.5
    assert rec.note == "new note"


@pytest.mark.asyncio
async def test_update_leaves_fields_unchanged_when_kwargs_none() -> None:
    """Fields that are None in the kwargs are preserved (negative branch)."""
    rec = _make_recording(time_expansion=1.5, note="kept")
    service = RecordingService(MagicMock())
    service.repo.get_by_id = AsyncMock(return_value=rec)  # type: ignore[method-assign]
    service.repo.update = AsyncMock(return_value=rec)  # type: ignore[method-assign]

    await service.update(rec.id, time_expansion=None, note=None)
    assert rec.time_expansion == 1.5
    assert rec.note == "kept"


@pytest.mark.asyncio
async def test_delete_returns_false_when_recording_missing() -> None:
    """delete() returns False when no row exists (lines 156-157)."""
    service = RecordingService(MagicMock())
    service.repo.get_by_id = AsyncMock(return_value=None)  # type: ignore[method-assign]
    deleted = await service.delete(uuid4())
    assert deleted is False


@pytest.mark.asyncio
async def test_delete_returns_true_when_recording_present() -> None:
    """delete() invokes repo.delete and returns True (lines 159-160)."""
    rec = _make_recording()
    service = RecordingService(MagicMock())
    service.repo.get_by_id = AsyncMock(return_value=rec)  # type: ignore[method-assign]
    service.repo.delete = AsyncMock(return_value=None)  # type: ignore[method-assign]

    deleted = await service.delete(rec.id)
    assert deleted is True
    service.repo.delete.assert_awaited_once_with(rec.id)


def test_get_effective_duration_applies_time_expansion() -> None:
    """get_effective_duration multiplies duration by time_expansion."""
    rec = _make_recording(time_expansion=2.0)
    rec.duration = 15.0
    service = RecordingService(MagicMock())
    assert service.get_effective_duration(rec) == 30.0


def test_is_ultrasonic_threshold_at_96khz() -> None:
    """is_ultrasonic returns True iff samplerate strictly exceeds 96000."""
    rec = _make_recording()
    service = RecordingService(MagicMock())
    rec.samplerate = 96_000
    assert service.is_ultrasonic(rec) is False
    rec.samplerate = 192_000
    assert service.is_ultrasonic(rec) is True


def test_init_with_audio_service_argument() -> None:
    """Constructor preserves the optional audio_service kwarg (line 40 setter)."""
    audio_stub = MagicMock()
    service = RecordingService(MagicMock(), audio_service=audio_stub)
    assert service.audio_service is audio_stub
