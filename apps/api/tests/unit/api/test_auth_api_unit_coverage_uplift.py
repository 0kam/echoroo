"""Coverage uplift unit tests for ``echoroo.api.v1.auth``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the API route handlers
so the module clears the 85% threshold.

Missing lines: 59-60,62,64,107-109,111,114,124,159-160,163,171,204,206-207,
              212-213,216,226,259-260,262,294-295,297,322-323,325
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1.auth import (
    login,
    logout,
    refresh,
    register,
)


@pytest.mark.asyncio
async def test_register_delegates_to_auth_service() -> None:
    """register() calls auth_service.register and validates user (lines 59-64)."""
    fake_user = MagicMock()
    auth_service = MagicMock()
    auth_service.register = AsyncMock(return_value=fake_user)

    http_request = MagicMock()
    http_request.client = MagicMock()
    http_request.client.host = "127.0.0.1"
    db = MagicMock()
    request = MagicMock()

    with (
        patch("echoroo.api.v1.auth.AuthService", return_value=auth_service),
        patch("echoroo.api.v1.auth.UserResponse.model_validate", return_value=MagicMock()),
    ):
        await register(
            request=request,
            http_request=http_request,
            db=db,
        )

    auth_service.register.assert_called_once()


@pytest.mark.asyncio
async def test_login_sets_cookie_and_returns_token() -> None:
    """login() calls auth_service.login, sets cookie, and returns token (lines 107-124)."""
    fake_token = MagicMock()
    fake_refresh = "refresh_token_value"

    auth_service = MagicMock()
    auth_service.login = AsyncMock(return_value=(fake_token, fake_refresh))

    http_request = MagicMock()
    http_request.client = MagicMock()
    http_request.client.host = "127.0.0.1"
    http_request.headers = {"user-agent": "test-agent"}

    response = MagicMock()
    response.set_cookie = MagicMock()
    db = MagicMock()
    request = MagicMock()

    with (
        patch("echoroo.api.v1.auth.AuthService", return_value=auth_service),
        patch("echoroo.api.v1.auth.settings") as mock_settings,
    ):
        mock_settings.ENVIRONMENT = "test"
        mock_settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS = 30

        result = await login(
            request=request,
            response=response,
            http_request=http_request,
            db=db,
            _rate_limit=None,
        )

    assert result is fake_token
    response.set_cookie.assert_called_once()


@pytest.mark.asyncio
async def test_logout_calls_auth_service_logout() -> None:
    """logout() calls auth_service.logout and clears cookie (lines 159-171)."""
    auth_service = MagicMock()
    auth_service.logout = AsyncMock()

    response = MagicMock()
    response.delete_cookie = MagicMock()
    db = MagicMock()
    current_user = MagicMock()
    current_user.id = "user-id"

    with patch("echoroo.api.v1.auth.AuthService", return_value=auth_service):
        await logout(
            response=response,
            current_user=current_user,
            db=db,
        )

    auth_service.logout.assert_called_once_with("user-id")
    response.delete_cookie.assert_called_once()


@pytest.mark.asyncio
async def test_refresh_raises_401_when_no_token() -> None:
    """refresh() raises 401 when refresh_token cookie is absent (lines 204,206-207)."""
    db = MagicMock()
    response = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await refresh(
            response=response,
            db=db,
            refresh_token=None,
        )

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_refresh_sets_new_cookie() -> None:
    """refresh() rotates refresh token and returns new token (lines 212-226)."""
    fake_token = MagicMock()
    new_refresh = "new_refresh_value"

    auth_service = MagicMock()
    auth_service.refresh_token = AsyncMock(return_value=(fake_token, new_refresh))

    db = MagicMock()
    response = MagicMock()
    response.set_cookie = MagicMock()

    with (
        patch("echoroo.api.v1.auth.AuthService", return_value=auth_service),
        patch("echoroo.api.v1.auth.settings") as mock_settings,
    ):
        mock_settings.ENVIRONMENT = "test"
        mock_settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS = 30

        result = await refresh(
            response=response,
            db=db,
            refresh_token="old_refresh",
        )

    assert result is fake_token
    response.set_cookie.assert_called_once()


# spec/011 Step 10 (FR-011-005) — the
# ``test_request_password_reset_calls_service`` /
# ``test_confirm_password_reset_calls_service`` /
# ``test_verify_email_calls_service_and_returns_user`` cases were
# removed alongside the deleted ``/api/v1/auth/password-reset/*`` and
# ``/api/v1/auth/verify-email`` endpoints (T120).
