"""Contract tests for admin endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.system import SystemSetting
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
async def regular_user(db_session: AsyncSession) -> User:
    """Create a regular test user (non-superuser).

    Args:
        db_session: Database session

    Returns:
        Regular user instance
    """
    user = User(
        email="regular@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Regular User",
        is_active=True,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def regular_user_headers(regular_user: User) -> dict[str, str]:
    """Create authentication headers for regular user.

    Args:
        regular_user: Regular user instance

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(regular_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    """Create an inactive test user.

    Args:
        db_session: Database session

    Returns:
        Inactive user instance
    """
    user = User(
        email="inactive@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Inactive User",
        is_active=False,
        is_verified=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


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


class TestListUsers:
    """Tests for GET /admin/users endpoint."""

    async def test_list_users_as_superuser(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        superuser: User,  # noqa: ARG002 - needed to create user
        regular_user: User,  # noqa: ARG002 - needed to create user
        inactive_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test listing users as superuser."""
        response = await client.get("/api/v1/admin/users", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert data["total"] >= 3  # At least 3 users created
        assert len(data["items"]) >= 3

    async def test_list_users_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test listing users as non-superuser returns 403."""
        response = await client.get("/api/v1/admin/users", headers=regular_user_headers)

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data

    async def test_list_users_with_search(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test listing users with search parameter."""
        response = await client.get(
            "/api/v1/admin/users",
            headers=superuser_headers,
            params={"search": "regular"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        # Check that all returned users match the search
        for user in data["items"]:
            assert "regular" in user["email"].lower() or (
                user["display_name"] and "regular" in user["display_name"].lower()
            )

    async def test_list_users_filter_active(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,  # noqa: ARG002 - needed to create user
        inactive_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test filtering users by is_active status."""
        # Filter active users
        response = await client.get(
            "/api/v1/admin/users",
            headers=superuser_headers,
            params={"is_active": "true"},
        )

        assert response.status_code == 200
        data = response.json()
        for user in data["items"]:
            assert user["is_active"] is True

        # Filter inactive users
        response = await client.get(
            "/api/v1/admin/users",
            headers=superuser_headers,
            params={"is_active": "false"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        for user in data["items"]:
            assert user["is_active"] is False

    async def test_list_users_pagination(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        superuser: User,  # noqa: ARG002 - needed to create user
        regular_user: User,  # noqa: ARG002 - needed to create user
    ) -> None:
        """Test user list pagination."""
        response = await client.get(
            "/api/v1/admin/users",
            headers=superuser_headers,
            params={"page": 1, "limit": 1},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 1
        assert len(data["items"]) == 1


class TestUpdateUser:
    """Tests for PATCH /admin/users/{userId} endpoint."""

    async def test_update_user_activate(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        inactive_user: User,
    ) -> None:
        """Test activating a user."""
        response = await client.patch(
            f"/api/v1/admin/users/{inactive_user.id}",
            headers=superuser_headers,
            json={"is_active": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is True
        assert data["id"] == str(inactive_user.id)

    async def test_update_user_deactivate(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,
    ) -> None:
        """Test deactivating a user."""
        response = await client.patch(
            f"/api/v1/admin/users/{regular_user.id}",
            headers=superuser_headers,
            json={"is_active": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False

    async def test_update_user_make_superuser(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        regular_user: User,
    ) -> None:
        """Test promoting user to superuser."""
        response = await client.patch(
            f"/api/v1/admin/users/{regular_user.id}",
            headers=superuser_headers,
            json={"is_superuser": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_superuser"] is True

    async def test_update_user_verify_email(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Test manually verifying user email."""
        # Create unverified user
        unverified = User(
            email="unverified@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            is_active=True,
            is_verified=False,
        )
        db_session.add(unverified)
        await db_session.commit()
        await db_session.refresh(unverified)

        response = await client.patch(
            f"/api/v1/admin/users/{unverified.id}",
            headers=superuser_headers,
            json={"is_verified": True},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_verified"] is True

    async def test_cannot_disable_last_superuser(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        superuser: User,
    ) -> None:
        """Test that the last superuser cannot be deactivated."""
        response = await client.patch(
            f"/api/v1/admin/users/{superuser.id}",
            headers=superuser_headers,
            json={"is_active": False},
        )

        assert response.status_code == 400
        data = response.json()
        assert "last superuser" in data["detail"].lower()

    async def test_cannot_remove_last_superuser_role(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        superuser: User,
    ) -> None:
        """Test that the last superuser role cannot be removed."""
        response = await client.patch(
            f"/api/v1/admin/users/{superuser.id}",
            headers=superuser_headers,
            json={"is_superuser": False},
        )

        assert response.status_code == 400
        data = response.json()
        assert "last superuser" in data["detail"].lower()

    async def test_update_user_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        inactive_user: User,
    ) -> None:
        """Test updating user as non-superuser returns 403."""
        response = await client.patch(
            f"/api/v1/admin/users/{inactive_user.id}",
            headers=regular_user_headers,
            json={"is_active": True},
        )

        assert response.status_code == 403

    async def test_update_nonexistent_user(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test updating a nonexistent user returns 404."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = await client.patch(
            f"/api/v1/admin/users/{fake_uuid}",
            headers=superuser_headers,
            json={"is_active": False},
        )

        assert response.status_code == 404


class TestSystemSettings:
    """Tests for system settings endpoints."""

    async def test_get_system_settings(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        system_settings: list[SystemSetting],  # noqa: ARG002 - needed to create settings
    ) -> None:
        """Test getting all system settings."""
        response = await client.get("/api/v1/admin/settings", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "registration_mode" in data
        assert "allow_registration" in data
        assert "session_timeout_minutes" in data

        # Check structure of each setting
        setting = data["registration_mode"]
        assert "key" in setting
        assert "value" in setting
        assert "value_type" in setting
        assert "updated_at" in setting

    async def test_get_system_settings_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test getting system settings as non-superuser returns 403."""
        response = await client.get("/api/v1/admin/settings", headers=regular_user_headers)

        assert response.status_code == 403

    async def test_update_system_settings(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        system_settings: list[SystemSetting],  # noqa: ARG002 - needed to create settings
    ) -> None:
        """Test updating system settings."""
        response = await client.patch(
            "/api/v1/admin/settings",
            headers=superuser_headers,
            json={
                "registration_mode": "invitation",
                "allow_registration": False,
                "session_timeout_minutes": 120,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data

        # Verify settings were updated
        get_response = await client.get(
            "/api/v1/admin/settings", headers=superuser_headers
        )
        settings_data = get_response.json()
        assert settings_data["registration_mode"]["value"] == "invitation"
        assert settings_data["allow_registration"]["value"] is False
        assert settings_data["session_timeout_minutes"]["value"] == 120

    async def test_update_system_settings_partial(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        system_settings: list[SystemSetting],  # noqa: ARG002 - needed to create settings
    ) -> None:
        """Test updating only some system settings."""
        response = await client.patch(
            "/api/v1/admin/settings",
            headers=superuser_headers,
            json={"session_timeout_minutes": 30},
        )

        assert response.status_code == 200

    async def test_update_system_settings_validation(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test validation of system settings values."""
        # Invalid session_timeout_minutes (too low)
        response = await client.patch(
            "/api/v1/admin/settings",
            headers=superuser_headers,
            json={"session_timeout_minutes": 2},
        )
        assert response.status_code == 422

        # Invalid session_timeout_minutes (too high)
        response = await client.patch(
            "/api/v1/admin/settings",
            headers=superuser_headers,
            json={"session_timeout_minutes": 2000},
        )
        assert response.status_code == 422

        # Invalid registration_mode
        response = await client.patch(
            "/api/v1/admin/settings",
            headers=superuser_headers,
            json={"registration_mode": "invalid"},
        )
        assert response.status_code == 422

    async def test_update_system_settings_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test updating system settings as non-superuser returns 403."""
        response = await client.patch(
            "/api/v1/admin/settings",
            headers=regular_user_headers,
            json={"allow_registration": False},
        )

        assert response.status_code == 403


class TestAdminAuthRequirements:
    """Tests for admin endpoint authentication requirements."""

    async def test_admin_endpoints_require_authentication(
        self,
        client: AsyncClient,
    ) -> None:
        """Test that admin endpoints require authentication."""
        # List users
        response = await client.get("/api/v1/admin/users")
        assert response.status_code == 401

        # Update user
        response = await client.patch(
            "/api/v1/admin/users/00000000-0000-0000-0000-000000000000",
            json={"is_active": False},
        )
        assert response.status_code == 401

        # Get settings
        response = await client.get("/api/v1/admin/settings")
        assert response.status_code == 401

        # Update settings
        response = await client.patch(
            "/api/v1/admin/settings",
            json={"allow_registration": False},
        )
        assert response.status_code == 401
