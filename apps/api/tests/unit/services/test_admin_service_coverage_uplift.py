"""Coverage uplift unit tests for ``echoroo.services.admin``.

Phase 17 §C heavy-gap batch: targets ``_derive_value_type`` (lines 35-37,
46), the Phase 4 stubs (lines 83-84, 105-106), and ``update_system_settings``
including the ``_update_setting`` create/update branch (lines 117, 156-187)
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.schemas.admin import (
    AdminUserUpdateRequest,
    SystemSettingsUpdateRequest,
)
from echoroo.services.admin import (
    AdminService,
    _derive_value_type,
    _raise_phase4_stub,
)


def test_derive_value_type_covers_all_branches() -> None:
    """_derive_value_type returns the right label for each JSONB type (lines 29-37)."""
    assert _derive_value_type(True) == "boolean"
    assert _derive_value_type(False) == "boolean"
    assert _derive_value_type(42) == "number"
    assert _derive_value_type(3.14) == "number"
    assert _derive_value_type("hello") == "string"
    assert _derive_value_type(None) == "null"
    assert _derive_value_type({"k": "v"}) == "json"
    assert _derive_value_type([1, 2, 3]) == "json"


def test_raise_phase4_stub_raises_501() -> None:
    """_raise_phase4_stub() always raises 501 (lines 45-49)."""
    with pytest.raises(HTTPException) as exc_info:
        _raise_phase4_stub()
    assert exc_info.value.status_code == 501
    assert "Phase 4" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_list_users_raises_phase4_stub() -> None:
    """list_users() raises the Phase 4 stub (lines 83-84)."""
    db = MagicMock()
    service = AdminService(db)
    with pytest.raises(HTTPException) as exc_info:
        await service.list_users(page=1, limit=20)
    assert exc_info.value.status_code == 501


@pytest.mark.asyncio
async def test_update_user_raises_phase4_stub() -> None:
    """update_user() raises the Phase 4 stub (lines 105-106)."""
    db = MagicMock()
    service = AdminService(db)
    request = AdminUserUpdateRequest(is_active=False)
    with pytest.raises(HTTPException) as exc_info:
        await service.update_user(uuid4(), request, uuid4())
    assert exc_info.value.status_code == 501


@pytest.mark.asyncio
async def test_get_system_settings_returns_keyed_responses() -> None:
    """get_system_settings() builds a dict of SystemSettingResponse (line 117)."""

    class _StubSetting:
        key = "theme"
        value = "dark"
        updated_at = datetime.now(UTC)

    db = MagicMock()
    result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = [_StubSetting()]
    result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(return_value=result)

    service = AdminService(db)
    settings = await service.get_system_settings()
    assert "theme" in settings
    assert settings["theme"].value == "dark"
    assert settings["theme"].value_type == "string"


@pytest.mark.asyncio
async def test_get_system_settings_value_type_branches() -> None:
    """get_system_settings() derives value_type for diverse JSONB types (line 35-37, 46)."""

    class _Stub:
        def __init__(self, key: str, value: object) -> None:
            self.key = key
            self.value = value
            self.updated_at = datetime.now(UTC)

    rows = [
        _Stub("flag", True),
        _Stub("nullable", None),
        _Stub("blob", {"a": 1}),
    ]
    db = MagicMock()
    result = MagicMock()
    scalars_obj = MagicMock()
    scalars_obj.all.return_value = rows
    result.scalars.return_value = scalars_obj
    db.execute = AsyncMock(return_value=result)

    service = AdminService(db)
    out = await service.get_system_settings()
    assert out["flag"].value_type == "boolean"
    assert out["nullable"].value_type == "null"
    assert out["blob"].value_type == "json"


@pytest.mark.asyncio
async def test_update_system_settings_creates_new_setting() -> None:
    """_update_setting() creates a new SystemSetting when none exists (lines 156-188)."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    service = AdminService(db)
    service.setting_repo.get_setting = AsyncMock(return_value=None)  # type: ignore[method-assign]

    request = SystemSettingsUpdateRequest(
        registration_mode="open",
        allow_registration=True,
        session_timeout_minutes=30,
        birdnet_species_filter="none",
        birdnet_min_conf=0.5,
    )
    await service.update_system_settings(request, uuid4())

    # Each provided field should result in a SystemSetting being added.
    assert db.add.call_count == 5
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_system_settings_updates_existing_setting() -> None:
    """_update_setting() updates an existing SystemSetting (lines 178-180)."""
    existing = MagicMock()
    existing.value = "old"
    existing.updated_by_id = None

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    service = AdminService(db)
    service.setting_repo.get_setting = AsyncMock(return_value=existing)  # type: ignore[method-assign]

    admin_id = uuid4()
    request = SystemSettingsUpdateRequest(registration_mode="invitation")
    await service.update_system_settings(request, admin_id)
    assert existing.value == "invitation"
    assert existing.updated_by_id == admin_id
    # No INSERT — the update branch was taken.
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_update_system_settings_skips_none_fields() -> None:
    """update_system_settings() skips fields left as None."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    service = AdminService(db)
    service.setting_repo.get_setting = AsyncMock(return_value=None)  # type: ignore[method-assign]

    request = SystemSettingsUpdateRequest()  # all None
    await service.update_system_settings(request, uuid4())

    # No setting touched — but the commit still fires.
    db.add.assert_not_called()
    db.commit.assert_awaited_once()
