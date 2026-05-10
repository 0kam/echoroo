"""Coverage uplift unit tests for ``echoroo.api.v1.setup``.

Phase 17 §C easy-win batch 1: covers the ``initialize_setup`` body
(lines 75-77) using a mocked service / DB so the module clears the 85%
threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.api.v1 import setup as mod
from echoroo.schemas.setup import SetupInitializeRequest


def _user_stub() -> MagicMock:
    """Return a MagicMock that quacks enough like a User row for model_validate."""
    user = MagicMock()
    user.id = uuid4()
    user.email = "admin@example.com"
    user.display_name = "Admin"
    user.is_superuser = True
    user.is_active = True
    return user


@pytest.mark.asyncio
async def test_initialize_setup_invokes_service_and_returns_user_response() -> None:
    """initialize_setup() builds SetupService, calls initialize_setup, and validates
    the return into UserResponse (lines 75-77).
    """
    fake_user = _user_stub()
    service_instance = MagicMock()
    service_instance.initialize_setup = AsyncMock(return_value=fake_user)

    db = MagicMock()
    request = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!",
        display_name="Admin",
    )

    with patch.object(mod, "SetupService", return_value=service_instance) as svc_cls, \
            patch.object(mod.UserResponse, "model_validate", return_value="VALIDATED"):
        result = await mod.initialize_setup(request=request, db=db)

    svc_cls.assert_called_once_with(db)
    service_instance.initialize_setup.assert_awaited_once_with(request)
    assert result == "VALIDATED"


@pytest.mark.asyncio
async def test_get_setup_status_invokes_service() -> None:
    """get_setup_status() builds SetupService and returns its status."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.get_setup_status = AsyncMock(return_value=sentinel)
    db = MagicMock()
    with patch.object(mod, "SetupService", return_value=service_instance):
        result = await mod.get_setup_status(db=db)
    assert result is sentinel
