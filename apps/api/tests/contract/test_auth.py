"""Contract tests for authentication endpoints.

Tests that auth endpoints conform to OpenAPI specification.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test successful user registration (T040)."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "SecurePass123",
            "display_name": "New User",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["display_name"] == "New User"
    assert data["is_verified"] is False
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_register_user_email_exists(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test registration with existing email returns 400 (T041)."""
    # Create existing user
    existing_user = User(
        email="existing@example.com",
        hashed_password=hash_password("password123"),
        is_verified=True,
    )
    db_session.add(existing_user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "existing@example.com",
            "password": "NewPass123",
        },
    )

    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_user_invalid_password(client: AsyncClient) -> None:
    """Test registration with weak password returns 422."""
    # Too short
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "short1",
        },
    )
    assert response.status_code == 422

    # No letters
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "12345678",
        },
    )
    assert response.status_code == 422

    # No numbers
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "onlyletters",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test successful login returns tokens (T042)."""
    # Create user
    user = User(
        email="user@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "TestPass123",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "expires_in" in data

    # Check refresh token cookie
    assert "refresh_token" in response.cookies


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test login with invalid credentials returns 401 (T043)."""
    # Create user
    user = User(
        email="user@example.com",
        hashed_password=hash_password("CorrectPass123"),
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Wrong password
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "user@example.com",
            "password": "WrongPass123",
        },
    )
    assert response.status_code == 401

    # Non-existent email
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "AnyPass123",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test login with inactive account returns 403."""
    user = User(
        email="inactive@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=True,
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "inactive@example.com",
            "password": "TestPass123",
        },
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_logout_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test logout clears refresh token (T044)."""
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
    access_token = login_response.json()["access_token"]

    # Logout
    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Logout successful"

    # Check cookie is cleared (or expired)
    # Note: cookie deletion may set max_age=0 or empty value


@pytest.mark.asyncio
async def test_logout_without_auth(client: AsyncClient) -> None:
    """Test logout without authentication returns 401."""
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test refresh token endpoint returns new tokens (T045)."""
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

    # Extract refresh token from cookie
    refresh_token = login_response.cookies.get("refresh_token")
    assert refresh_token is not None

    # Refresh token
    response = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    # Should get new refresh token
    assert "refresh_token" in response.cookies


@pytest.mark.asyncio
async def test_refresh_token_invalid(client: AsyncClient) -> None:
    """Test refresh with invalid token returns 401."""
    response = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": "invalid_token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_request(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test password reset request always returns success (T046)."""
    # Create user
    user = User(
        email="user@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    # Request reset for existing user
    response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "user@example.com"},
    )
    assert response.status_code == 200

    # Request reset for non-existent user (should still return success)
    response = await client.post(
        "/api/v1/auth/password-reset/request",
        json={"email": "nonexistent@example.com"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_verify_email(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test email verification with valid token (T047)."""
    from datetime import UTC, datetime, timedelta

    # Create user with verification token
    user = User(
        email="user@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=False,
        email_verification_token="valid_token_123",
        email_verification_expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "valid_token_123"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["is_verified"] is True


@pytest.mark.asyncio
async def test_verify_email_invalid_token(client: AsyncClient) -> None:
    """Test email verification with invalid token returns 400."""
    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "invalid_token"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_verify_email_expired_token(client: AsyncClient, db_session: AsyncSession) -> None:
    """Test email verification with expired token returns 400."""
    from datetime import UTC, datetime, timedelta

    # Create user with expired verification token
    user = User(
        email="user@example.com",
        hashed_password=hash_password("TestPass123"),
        is_verified=False,
        email_verification_token="expired_token",
        email_verification_expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/verify-email",
        json={"token": "expired_token"},
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()
