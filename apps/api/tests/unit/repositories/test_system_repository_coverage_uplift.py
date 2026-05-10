"""Coverage uplift unit tests for ``echoroo.repositories.system``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the missing branches
of SystemSettingRepository so the module clears the 85% threshold.

Missing lines: 55-57,85-86,105-106,108-110,123,135-138,143-148,153-156
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.repositories.system import SystemSettingRepository


def _make_session(scalar_value: object = None) -> MagicMock:
    """Return a mock session whose execute().scalar_one_or_none() returns scalar_value."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_value
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_get_setting_returns_none_when_not_found() -> None:
    """get_setting returns None when the key is absent (line 55-57)."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)
    result = await repo.get_setting("missing_key")
    assert result is None


@pytest.mark.asyncio
async def test_get_setting_returns_row_when_found() -> None:
    """get_setting returns the SystemSetting row when found."""
    fake_setting = MagicMock()
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)
    result = await repo.get_setting("some_key")
    assert result is fake_setting


@pytest.mark.asyncio
async def test_get_value_returns_default_when_setting_missing() -> None:
    """get_value returns default value when setting is absent (lines 85-86)."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)
    result = await repo.get_value("nonexistent", default="fallback")
    assert result == "fallback"


@pytest.mark.asyncio
async def test_get_value_returns_setting_value_when_present() -> None:
    """get_value returns the JSONB value when the setting exists."""
    fake_setting = MagicMock()
    fake_setting.value = 42
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)
    result = await repo.get_value("some_key")
    assert result == 42


@pytest.mark.asyncio
async def test_set_setting_creates_new_when_missing() -> None:
    """set_setting creates a new SystemSetting when key is absent (lines 105-106,108-110)."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)

    updated_by_id = uuid4()
    await repo.set_setting("new_key", "new_value", updated_by_id)

    session.add.assert_called_once()
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_set_setting_updates_existing_when_present() -> None:
    """set_setting updates the existing row when key already exists (line 105-106,123)."""
    fake_setting = MagicMock()
    fake_setting.value = "old_value"
    fake_setting.updated_by_id = uuid4()

    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)

    updated_by_id = uuid4()
    await repo.set_setting("existing_key", "updated_value", updated_by_id)

    assert fake_setting.value == "updated_value"
    assert fake_setting.updated_by_id == updated_by_id
    session.flush.assert_called_once()


@pytest.mark.asyncio
async def test_is_setup_completed_returns_true_for_bool_true() -> None:
    """is_setup_completed returns True for bool True value (lines 135-138)."""
    fake_setting = MagicMock()
    fake_setting.value = True
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)

    result = await repo.is_setup_completed()
    assert result is True


@pytest.mark.asyncio
async def test_is_setup_completed_returns_false_when_absent() -> None:
    """is_setup_completed returns False when setting is absent (line 135)."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)

    result = await repo.is_setup_completed()
    assert result is False


@pytest.mark.asyncio
async def test_is_setup_completed_handles_string_true() -> None:
    """is_setup_completed coerces string 'true' to True (lines 143-144)."""
    fake_setting = MagicMock()
    fake_setting.value = "true"
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)

    result = await repo.is_setup_completed()
    assert result is True


@pytest.mark.asyncio
async def test_is_setup_completed_handles_string_false() -> None:
    """is_setup_completed coerces string 'false' to False (lines 143-144)."""
    fake_setting = MagicMock()
    fake_setting.value = "false"
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)

    result = await repo.is_setup_completed()
    assert result is False


@pytest.mark.asyncio
async def test_is_setup_completed_handles_non_bool_truthy() -> None:
    """is_setup_completed coerces truthy int 1 to True (lines 146-148)."""
    fake_setting = MagicMock()
    fake_setting.value = 1
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)

    result = await repo.is_setup_completed()
    assert result is True


@pytest.mark.asyncio
async def test_get_embedding_model_returns_stored_value() -> None:
    """get_embedding_model returns stored string value (lines 153-154)."""
    fake_setting = MagicMock()
    fake_setting.value = "birdnet"
    session = _make_session(fake_setting)
    repo = SystemSettingRepository(session)

    result = await repo.get_embedding_model()
    assert result == "birdnet"


@pytest.mark.asyncio
async def test_get_embedding_model_returns_default_perch_when_absent() -> None:
    """get_embedding_model defaults to 'perch' when setting is absent (lines 155-156)."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)

    result = await repo.get_embedding_model()
    assert result == "perch"


@pytest.mark.asyncio
async def test_get_birdnet_settings_returns_defaults_when_absent() -> None:
    """get_birdnet_settings returns default species/min_conf when settings absent."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)

    result = await repo.get_birdnet_settings()
    assert result["species_filter"] == "none"
    assert result["min_conf"] == 0.25


@pytest.mark.asyncio
async def test_mark_setup_completed_calls_set_setting() -> None:
    """mark_setup_completed delegates to set_setting with True (lines 136-138)."""
    session = _make_session(None)
    repo = SystemSettingRepository(session)
    updated_by_id = uuid4()

    await repo.mark_setup_completed(updated_by_id)

    # set_setting was called by mark_setup_completed which calls flush
    session.flush.assert_called()
