"""Coverage uplift unit tests for ``echoroo.api.v1.admin``.

Phase 17 §C heavy-gap batch: covers the route handler bodies (lines
70-72, 109-111, 180, 209-210, 241-242, 271-272, 304-305, 332-333,
368-370, 403-404, 433-434, 466-467, 493-494) by calling the handlers
directly with mocked services so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.v1 import admin as mod
from echoroo.schemas.admin import (
    AdminUserUpdateRequest,
    SystemSettingsUpdateRequest,
)
from echoroo.schemas.license import LicenseCreate, LicenseUpdate
from echoroo.schemas.recorder import RecorderCreate, RecorderUpdate


def _superuser_stub() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user._superuser_id = uuid4()
    user.email = "admin@example.com"
    user.display_name = "Admin"
    user.is_superuser = True
    user.is_active = True
    user.is_verified = True
    return user


@pytest.mark.asyncio
async def test_list_users_calls_admin_service_with_pagination() -> None:
    """list_users handler delegates to AdminService.list_users (lines 70-72)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.list_users = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "AdminService", return_value=service_instance):
        out = await mod.list_users(
            db=db, current_user=user, page=2, limit=10,
            search=None, is_active=True,
        )
    assert out is sentinel
    service_instance.list_users.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_user_validates_response_model() -> None:
    """update_user delegates to AdminService.update_user (lines 109-111)."""
    user_row = _superuser_stub()
    service_instance = MagicMock()
    service_instance.update_user = AsyncMock(return_value=user_row)
    db = MagicMock()
    user = _superuser_stub()
    request = AdminUserUpdateRequest(is_active=False)

    with patch.object(mod, "AdminService", return_value=service_instance), \
            patch.object(mod.UserResponse, "model_validate", return_value="OK"):
        out = await mod.update_user(
            user_id=uuid4(), request=request, db=db, current_user=user,
        )
    assert out == "OK"
    service_instance.update_user.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_system_settings_passes_through() -> None:
    """get_system_settings handler returns the service dict (line 138)."""
    sentinel = {"theme": MagicMock()}
    service_instance = MagicMock()
    service_instance.get_system_settings = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "AdminService", return_value=service_instance):
        out = await mod.get_system_settings(db=db, current_user=user)
    assert out is sentinel


@pytest.mark.asyncio
async def test_update_system_settings_uses_superuser_id() -> None:
    """update_system_settings reads ``_superuser_id`` from the user (line 180)."""
    service_instance = MagicMock()
    service_instance.update_system_settings = AsyncMock(return_value=None)
    db = MagicMock()
    user = _superuser_stub()
    request = SystemSettingsUpdateRequest(allow_registration=True)
    with patch.object(mod, "AdminService", return_value=service_instance):
        out = await mod.update_system_settings(
            request=request, db=db, current_user=user,
        )
    assert out == {"message": "Settings updated successfully"}
    service_instance.update_system_settings.assert_awaited_once_with(
        request, user._superuser_id
    )


@pytest.mark.asyncio
async def test_update_system_settings_rejects_when_superuser_id_missing() -> None:
    """update_system_settings raises 403 when ``_superuser_id`` is None."""
    service_instance = MagicMock()
    service_instance.update_system_settings = AsyncMock(return_value=None)
    db = MagicMock()
    user = _superuser_stub()
    user._superuser_id = None
    request = SystemSettingsUpdateRequest(allow_registration=True)
    with patch.object(mod, "AdminService", return_value=service_instance), \
            pytest.raises(HTTPException) as exc_info:
        await mod.update_system_settings(
            request=request, db=db, current_user=user,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_list_licenses_passes_through() -> None:
    """list_licenses delegates to LicenseService (lines 209-210)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.list_licenses = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "LicenseService", return_value=service_instance):
        out = await mod.list_licenses(db=db, current_user=user)
    assert out is sentinel


@pytest.mark.asyncio
async def test_create_license_passes_through() -> None:
    """create_license delegates to LicenseService.create_license (lines 241-242)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.create_license = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    request = LicenseCreate(id="cc-by-4.0", name="CC BY 4.0", short_name="CC-BY")
    with patch.object(mod, "LicenseService", return_value=service_instance):
        out = await mod.create_license(request=request, db=db, current_user=user)
    assert out is sentinel


@pytest.mark.asyncio
async def test_get_license_passes_through() -> None:
    """get_license delegates to LicenseService.get_license (lines 271-272)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.get_license = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "LicenseService", return_value=service_instance):
        out = await mod.get_license(license_id="cc-by", db=db, current_user=user)
    assert out is sentinel


@pytest.mark.asyncio
async def test_update_license_passes_through() -> None:
    """update_license delegates to LicenseService.update_license (lines 304-305)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.update_license = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    request = LicenseUpdate(name="renamed")
    with patch.object(mod, "LicenseService", return_value=service_instance):
        out = await mod.update_license(
            license_id="cc-by", request=request, db=db, current_user=user,
        )
    assert out is sentinel


@pytest.mark.asyncio
async def test_delete_license_passes_through() -> None:
    """delete_license delegates to LicenseService.delete_license (lines 332-333)."""
    service_instance = MagicMock()
    service_instance.delete_license = AsyncMock(return_value=None)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "LicenseService", return_value=service_instance):
        await mod.delete_license(license_id="cc-by", db=db, current_user=user)
    service_instance.delete_license.assert_awaited_once_with("cc-by")


@pytest.mark.asyncio
async def test_list_recorders_passes_through() -> None:
    """list_recorders delegates to RecorderService.list_recorders (lines 368-370)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.list_recorders = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "RecorderService", return_value=service_instance):
        out = await mod.list_recorders(db=db, current_user=user, page=1, limit=20)
    assert out is sentinel


@pytest.mark.asyncio
async def test_create_recorder_passes_through() -> None:
    """create_recorder delegates to RecorderService.create_recorder (lines 403-404)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.create_recorder = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    request = RecorderCreate(
        id="audiomoth-v1",
        manufacturer="OpenAcoustic",
        recorder_name="AudioMoth",
    )
    with patch.object(mod, "RecorderService", return_value=service_instance):
        out = await mod.create_recorder(request=request, db=db, current_user=user)
    assert out is sentinel


@pytest.mark.asyncio
async def test_get_recorder_passes_through() -> None:
    """get_recorder delegates to RecorderService.get_recorder (lines 433-434)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.get_recorder = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "RecorderService", return_value=service_instance):
        out = await mod.get_recorder(recorder_id="x", db=db, current_user=user)
    assert out is sentinel


@pytest.mark.asyncio
async def test_update_recorder_passes_through() -> None:
    """update_recorder delegates to RecorderService.update_recorder (lines 466-467)."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.update_recorder = AsyncMock(return_value=sentinel)
    db = MagicMock()
    user = _superuser_stub()
    request = RecorderUpdate(recorder_name="rebrand")
    with patch.object(mod, "RecorderService", return_value=service_instance):
        out = await mod.update_recorder(
            recorder_id="x", request=request, db=db, current_user=user,
        )
    assert out is sentinel


@pytest.mark.asyncio
async def test_delete_recorder_passes_through() -> None:
    """delete_recorder delegates to RecorderService.delete_recorder (lines 493-494)."""
    service_instance = MagicMock()
    service_instance.delete_recorder = AsyncMock(return_value=None)
    db = MagicMock()
    user = _superuser_stub()
    with patch.object(mod, "RecorderService", return_value=service_instance):
        await mod.delete_recorder(recorder_id="x", db=db, current_user=user)
    service_instance.delete_recorder.assert_awaited_once_with("x")
