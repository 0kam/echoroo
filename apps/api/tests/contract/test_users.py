"""Contract tests for user profile endpoints.

Tests that user endpoints conform to OpenAPI specification (T096-T098).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user for profile tests."""
    user = User(
        email="testuser@example.com",
        hashed_password=hash_password("TestPass123"),
        display_name="Test User",
        organization="Test Org",
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers(client: AsyncClient, test_user: User) -> dict[str, str]:
    """Get authentication headers for test user."""
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPass123",
        },
    )
    access_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


# T096: GET /users/me Tests


@pytest.mark.asyncio
async def test_get_current_user_success(
    client: AsyncClient, auth_headers: dict[str, str], test_user: User
) -> None:
    """Test successful get current user profile."""
    response = await client.get("/api/v1/users/me", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()

    # Verify response structure matches UserResponse schema
    assert data["id"] == str(test_user.id)
    assert data["email"] == "testuser@example.com"
    assert data["display_name"] == "Test User"
    assert data["organization"] == "Test Org"
    assert data["is_active"] is True
    assert data["is_superuser"] is False
    assert data["is_verified"] is True
    assert "created_at" in data
    assert "last_login_at" in data


@pytest.mark.asyncio
async def test_get_current_user_unauthorized(client: AsyncClient) -> None:
    """Test get current user without authentication returns 401."""
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


# T097: PATCH /users/me Tests


@pytest.mark.asyncio
async def test_update_user_display_name(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test updating user display name."""
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"display_name": "New Display Name"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "New Display Name"
    # Organization should remain unchanged
    assert data["organization"] == "Test Org"


@pytest.mark.asyncio
async def test_update_user_organization(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test updating user organization."""
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"organization": "New Organization"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["organization"] == "New Organization"
    # Display name should remain unchanged
    assert data["display_name"] == "Test User"


@pytest.mark.asyncio
async def test_update_user_both_fields(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test updating both display name and organization."""
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={
            "display_name": "Updated Name",
            "organization": "Updated Org",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Updated Name"
    assert data["organization"] == "Updated Org"


@pytest.mark.asyncio
async def test_update_user_display_name_max_length(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test display name max length validation (100 chars)."""
    # Exactly 100 chars should work
    long_name = "A" * 100
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"display_name": long_name},
    )
    assert response.status_code == 200
    assert response.json()["display_name"] == long_name

    # 101 chars should fail
    too_long_name = "A" * 101
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"display_name": too_long_name},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_user_organization_max_length(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test organization max length validation (200 chars)."""
    # Exactly 200 chars should work
    long_org = "B" * 200
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"organization": long_org},
    )
    assert response.status_code == 200
    assert response.json()["organization"] == long_org

    # 201 chars should fail
    too_long_org = "B" * 201
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={"organization": too_long_org},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_user_unauthorized(client: AsyncClient) -> None:
    """Test update user without authentication returns 401."""
    response = await client.patch(
        "/api/v1/users/me",
        json={"display_name": "New Name"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_user_empty_body(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test update user with empty body keeps existing values."""
    response = await client.patch(
        "/api/v1/users/me",
        headers=auth_headers,
        json={},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["display_name"] == "Test User"
    assert data["organization"] == "Test Org"


# T098: PUT /users/me/password Tests


@pytest.mark.asyncio
async def test_change_password_success(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test successful password change."""
    response = await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "TestPass123",
            "new_password": "NewSecure456",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Password changed successfully"

    # Verify new password works for login
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "NewSecure456",
        },
    )
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_change_password_wrong_current(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test password change with wrong current password returns 400."""
    response = await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "WrongPassword123",
            "new_password": "NewSecure456",
        },
    )

    assert response.status_code == 400
    assert "current password" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_change_password_weak_new_too_short(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test password change with weak new password (too short) returns 422."""
    response = await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "TestPass123",
            "new_password": "Short1",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_weak_no_letters(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test password change with password containing no letters returns 422."""
    response = await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "TestPass123",
            "new_password": "12345678",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_weak_no_numbers(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test password change with password containing no numbers returns 422."""
    response = await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "TestPass123",
            "new_password": "onlyletters",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_change_password_same_as_current(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test password change with same password as current returns 400."""
    response = await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "TestPass123",
            "new_password": "TestPass123",
        },
    )

    assert response.status_code == 400
    assert "different" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_change_password_unauthorized(client: AsyncClient) -> None:
    """Test password change without authentication returns 401."""
    response = await client.put(
        "/api/v1/users/me/password",
        json={
            "current_password": "TestPass123",
            "new_password": "NewSecure456",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_change_password_old_password_no_longer_works(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Test that old password no longer works after password change."""
    # Change password
    await client.put(
        "/api/v1/users/me/password",
        headers=auth_headers,
        json={
            "current_password": "TestPass123",
            "new_password": "NewSecure456",
        },
    )

    # Try to login with old password
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPass123",
        },
    )
    assert login_response.status_code == 401
