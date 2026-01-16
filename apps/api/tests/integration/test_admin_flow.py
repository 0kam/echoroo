"""Integration tests for admin flows."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.user import User


@pytest.fixture
async def superuser(db_session: AsyncSession) -> User:
    """Create a test superuser.

    Args:
        db_session: Database session

    Returns:
        Superuser instance
    """
    user = User(
        email="superuser@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Superuser",
        is_active=True,
        is_verified=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def superuser_headers(superuser: User) -> dict[str, str]:
    """Create authentication headers for superuser.

    Args:
        superuser: Superuser instance

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(superuser.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def system_settings(db_session: AsyncSession) -> None:
    """System settings are already created in conftest.py.

    This fixture exists for clarity in test signatures but doesn't
    need to create additional settings.

    Args:
        db_session: Database session
    """
    # Settings are already created in conftest.py during database setup
    pass


async def test_full_admin_flow(
    client: AsyncClient,
    superuser_headers: dict[str, str],
    db_session: AsyncSession,
    system_settings: None,  # noqa: ARG001 - needed to ensure settings exist
) -> None:
    """Test complete admin workflow.

    This test covers:
    1. Listing all users
    2. Creating a new user (via registering)
    3. Finding the user through search
    4. Deactivating the user
    5. Verifying the user is inactive in the list
    6. Reactivating the user
    7. Promoting user to superuser
    8. Updating system settings
    9. Verifying settings were updated

    Args:
        async_client: HTTP test client
        superuser_headers: Authentication headers for superuser
        db_session: Database session
        system_settings: System settings fixture
    """
    # 1. List all users initially
    response = await client.get("/api/v1/admin/users", headers=superuser_headers)
    assert response.status_code == 200
    initial_data = response.json()
    initial_count = initial_data["total"]

    # 2. Create a new user manually for testing
    new_user = User(
        email="newuser@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="New User",
        is_active=True,
        is_verified=False,
        is_superuser=False,
    )
    db_session.add(new_user)
    await db_session.commit()
    await db_session.refresh(new_user)

    # 3. Find the new user through search
    response = await client.get(
        "/api/v1/admin/users",
        headers=superuser_headers,
        params={"search": "newuser"},
    )
    assert response.status_code == 200
    search_data = response.json()
    assert search_data["total"] >= 1
    found_user = next(u for u in search_data["items"] if u["email"] == "newuser@example.com")
    assert found_user["is_active"] is True
    assert found_user["is_verified"] is False
    user_id = found_user["id"]

    # 4. Deactivate the user
    response = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        headers=superuser_headers,
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    # 5. Verify the user is inactive in the list
    response = await client.get(
        "/api/v1/admin/users",
        headers=superuser_headers,
        params={"is_active": "false"},
    )
    assert response.status_code == 200
    inactive_data = response.json()
    inactive_user = next(u for u in inactive_data["items"] if u["id"] == user_id)
    assert inactive_user["is_active"] is False

    # 6. Reactivate and verify the user
    response = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        headers=superuser_headers,
        json={"is_active": True, "is_verified": True},
    )
    assert response.status_code == 200
    updated_user = response.json()
    assert updated_user["is_active"] is True
    assert updated_user["is_verified"] is True

    # 7. Promote user to superuser
    response = await client.patch(
        f"/api/v1/admin/users/{user_id}",
        headers=superuser_headers,
        json={"is_superuser": True},
    )
    assert response.status_code == 200
    assert response.json()["is_superuser"] is True

    # 8. Update system settings
    response = await client.patch(
        "/api/v1/admin/settings",
        headers=superuser_headers,
        json={
            "registration_mode": "invitation",
            "allow_registration": False,
            "session_timeout_minutes": 90,
        },
    )
    assert response.status_code == 200

    # 9. Verify settings were updated
    response = await client.get("/api/v1/admin/settings", headers=superuser_headers)
    assert response.status_code == 200
    settings = response.json()
    assert settings["registration_mode"]["value"] == "invitation"
    assert settings["allow_registration"]["value"] is False
    assert settings["session_timeout_minutes"]["value"] == 90

    # 10. Verify final user count
    response = await client.get("/api/v1/admin/users", headers=superuser_headers)
    assert response.status_code == 200
    final_data = response.json()
    assert final_data["total"] == initial_count + 1
