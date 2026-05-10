"""Coverage uplift unit tests for ``echoroo.api.v1.users``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers route handler bodies
(get_current_user, update_current_user, change_password, list_api_tokens,
create_api_token, revoke_api_token) so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1 import users as mod
from echoroo.schemas.user import (
    PasswordChangeRequest,
    UserUpdateRequest,
)


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.email = "user@example.com"
    user.display_name = "Test User"
    user.is_active = True
    user.is_verified = True
    user.is_superuser = False
    return user


@pytest.mark.asyncio
async def test_get_current_user_returns_validated_response() -> None:
    """get_current_user handler returns UserResponse (line 46)."""
    user = _make_user()
    # Patch UserResponse.model_validate to return a sentinel
    sentinel = MagicMock()
    with patch("echoroo.api.v1.users.UserResponse") as mock_resp:
        mock_resp.model_validate.return_value = sentinel
        result = await mod.get_current_user(current_user=user)
    assert result is sentinel
    mock_resp.model_validate.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_update_current_user_delegates_to_service() -> None:
    """update_current_user delegates to UserService.update_user (lines 74-76)."""
    user = _make_user()
    db = MagicMock()
    request = UserUpdateRequest(display_name="New Name")
    updated = MagicMock()

    service_mock = MagicMock()
    service_mock.update_user = AsyncMock(return_value=updated)
    sentinel = MagicMock()

    with (
        patch.object(mod, "UserService", return_value=service_mock),
        patch("echoroo.api.v1.users.UserResponse") as mock_resp,
    ):
        mock_resp.model_validate.return_value = sentinel
        result = await mod.update_current_user(
            request=request, current_user=user, db=db
        )

    service_mock.update_user.assert_awaited_once_with(user.id, request)
    assert result is sentinel


@pytest.mark.asyncio
async def test_change_password_delegates_to_service() -> None:
    """change_password delegates to UserService.change_password (lines 105-107)."""
    user = _make_user()
    db = MagicMock()
    request = PasswordChangeRequest(
        current_password="OldPass123!",
        new_password="NewPass456!",
    )

    service_mock = MagicMock()
    service_mock.change_password = AsyncMock()

    with (
        patch.object(mod, "UserService", return_value=service_mock),
        patch("echoroo.api.v1.users.PasswordChangeResponse") as mock_resp,
    ):
        sentinel = MagicMock()
        mock_resp.return_value = sentinel
        result = await mod.change_password(
            request=request, current_user=user, db=db
        )

    service_mock.change_password.assert_awaited_once_with(user.id, request)
    assert result is sentinel


@pytest.mark.asyncio
async def test_list_api_tokens_raises_501_via_token_service() -> None:
    """list_api_tokens propagates 501 from TokenService (lines 137-139)."""
    user = _make_user()
    db = MagicMock()

    service_mock = MagicMock()
    service_mock.list_tokens = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="stub")
    )

    with (
        patch.object(mod, "TokenService", return_value=service_mock),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.list_api_tokens(db=db, current_user=user)

    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_create_api_token_raises_501_via_token_service() -> None:
    """create_api_token propagates 501 from TokenService (lines 171-175)."""
    from echoroo.schemas.token import APITokenCreateRequest

    user = _make_user()
    db = MagicMock()
    request = APITokenCreateRequest(name="my-token")

    service_mock = MagicMock()
    service_mock.create_token = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="stub")
    )

    with (
        patch.object(mod, "TokenService", return_value=service_mock),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.create_api_token(db=db, current_user=user, request=request)

    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_revoke_api_token_raises_501_via_token_service() -> None:
    """revoke_api_token propagates 501 from TokenService (lines 205-207)."""
    user = _make_user()
    db = MagicMock()
    token_id = uuid4()

    service_mock = MagicMock()
    service_mock.revoke_token = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="stub")
    )

    with (
        patch.object(mod, "TokenService", return_value=service_mock),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.revoke_api_token(db=db, current_user=user, token_id=token_id)

    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED
