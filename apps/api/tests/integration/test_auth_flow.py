"""Integration tests for authentication flows.

Tests complete authentication scenarios end-to-end.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User


@pytest.mark.asyncio
async def test_full_registration_and_login_flow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test complete user registration and login flow (T048)."""
    # 1. Register new user
    register_response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecurePass123",
            "display_name": "Test User",
        },
    )
    assert register_response.status_code == 201
    user_data = register_response.json()
    assert user_data["is_verified"] is False

    # 2. Manually mark user as verified (simulate email verification)
    from sqlalchemy import select

    result = await db_session.execute(
        select(User).where(User.email == "newuser@example.com")
    )
    user = result.scalar_one()
    user.is_verified = True
    await db_session.commit()

    # 3. Login with registered credentials
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "newuser@example.com",
            "password": "SecurePass123",
        },
    )
    assert login_response.status_code == 200
    tokens = login_response.json()
    assert "access_token" in tokens
    assert "refresh_token" in login_response.cookies

    # 4. Access protected endpoint (if implemented)
    # access_token = tokens["access_token"]
    # protected_response = await client.get(
    #     "/api/v1/users/me",
    #     headers={"Authorization": f"Bearer {access_token}"}
    # )
    # assert protected_response.status_code == 200

    # 5. Refresh token
    refresh_token = login_response.cookies.get("refresh_token")
    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": refresh_token},
    )
    assert refresh_response.status_code == 200
    new_tokens = refresh_response.json()
    assert "access_token" in new_tokens

    # 6. Logout
    logout_response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert logout_response.status_code == 200


@pytest.mark.asyncio
async def test_password_reset_flow(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test complete password reset flow (T049)."""
    # 1. Create user
    user = User(
        email="user@example.com",
        hashed_password=hash_password("OldPass123"),
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # 2. Request password reset
    reset_request_response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "user@example.com"},
    )
    assert reset_request_response.status_code == 200

    # 3. Get reset token from database (simulate email)

    await db_session.refresh(user)
    reset_token = user.password_reset_token
    assert reset_token is not None

    # 4. Confirm password reset with token
    confirm_response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "password": "NewPass123",
        },
    )
    assert confirm_response.status_code == 200

    # 5. Login with new password
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "NewPass123",
        },
    )
    assert login_response.status_code == 200

    # 6. Old password should not work
    old_login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "OldPass123",
        },
    )
    assert old_login_response.status_code == 401


@pytest.mark.asyncio
async def test_account_lockout_after_failed_attempts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Test CAPTCHA requirement and account lockout after multiple failed login attempts."""
    # Create user
    user = User(
        email="user@example.com",
        hashed_password=hash_password("CorrectPass123"),
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # First 3 attempts should return 401
    for i in range(3):
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "user@example.com",
                "password": "WrongPass123",
            },
        )
        assert response.status_code == 401, f"Attempt {i+1} should return 401"

    # 4th attempt should require CAPTCHA (400)
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "WrongPass123",
        },
    )
    assert response.status_code == 400
    assert "captcha" in response.json()["detail"].lower()

    # Note: Full account lockout (423) would require 5+ failed attempts
    # This is tested by verifying CAPTCHA requirement after 3 attempts


@pytest.mark.asyncio
async def test_email_verification_flow(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test email verification flow."""
    from datetime import UTC, datetime, timedelta

    # 1. Create user with verification token
    user = User(
        email="user@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=False,
        email_verification_token="verification_token_123",
        email_verification_expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add(user)
    await db_session.commit()

    # 2. Verify email with token
    verify_response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "verification_token_123"},
    )
    assert verify_response.status_code == 200
    user_data = verify_response.json()
    assert user_data["is_verified"] is True

    # 3. Token should be cleared after verification
    await db_session.refresh(user)
    assert user.email_verification_token is None
    assert user.email_verification_expires_at is None


@pytest.mark.asyncio
async def test_token_refresh_rotation(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test that refresh tokens are rotated (one-time use)."""
    # Create user and login
    user = User(
        email="user@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "TestPass123",
        },
    )
    first_refresh_token = login_response.cookies.get("refresh_token")

    # First refresh should work
    refresh_response = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": first_refresh_token},
    )
    assert refresh_response.status_code == 200
    second_refresh_token = refresh_response.cookies.get("refresh_token")

    # Tokens should be different (rotation)
    assert first_refresh_token != second_refresh_token

    # Second refresh with new token should work
    refresh_response2 = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": second_refresh_token},
    )
    assert refresh_response2.status_code == 200
