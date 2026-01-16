"""Integration tests for complete setup workflow.

Tests the full setup flow from initial state to completion.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.system import SystemSetting
from echoroo.models.user import User


@pytest.mark.asyncio
class TestSetupFlow:
    """Test complete setup workflow end-to-end."""

    async def test_full_setup_flow(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test complete setup workflow from start to finish.

        Workflow:
            1. Check initial setup status (required)
            2. Initialize setup with first admin user
            3. Verify setup status (completed)
            4. Verify user was created in database
            5. Verify system settings were updated
            6. Attempt second setup (should fail)
        """
        # Step 1: Check initial status
        response = await client.get("/api/v1/setup/status")
        assert response.status_code == 200
        assert response.json()["setup_required"] is True
        assert response.json()["setup_completed"] is False

        # Step 2: Initialize setup
        setup_data = {
            "email": "admin@echoroo.app",
            "password": "SuperSecurePassword123!",
            "display_name": "System Administrator",
        }
        response = await client.post("/api/v1/setup/initialize", json=setup_data)
        assert response.status_code == 201

        user_data = response.json()
        assert user_data["email"] == "admin@echoroo.app"
        assert user_data["display_name"] == "System Administrator"
        assert user_data["is_superuser"] is True
        assert user_data["is_verified"] is True

        # Step 3: Verify setup status changed
        response = await client.get("/api/v1/setup/status")
        assert response.status_code == 200
        assert response.json()["setup_required"] is False
        assert response.json()["setup_completed"] is True

        # Step 4: Verify user exists in database
        result = await db_session.execute(
            select(User).where(User.email == "admin@echoroo.app")
        )
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.email == "admin@echoroo.app"
        assert user.display_name == "System Administrator"
        assert user.is_superuser is True
        assert user.is_verified is True
        assert user.is_active is True
        assert user.hashed_password is not None
        assert not user.hashed_password.startswith("Super")  # Not plain text

        # Step 5: Verify system settings updated
        result = await db_session.execute(
            select(SystemSetting).where(SystemSetting.key == "setup_completed")
        )
        setting = result.scalar_one_or_none()
        assert setting is not None
        assert setting.value == "true"

        # Step 6: Attempt second setup (should fail)
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "second@example.com",
                "password": "AnotherPassword123!",
            },
        )
        assert response.status_code == 403

    async def test_setup_with_existing_user(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test that setup fails if any user already exists.

        This tests the condition where a user was created outside setup.
        """
        # Manually create a user
        from echoroo.core.security import hash_password

        user = User(
            email="existing@example.com",
            hashed_password=hash_password("password123"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
        )
        db_session.add(user)
        await db_session.commit()

        # Attempt setup
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
            },
        )

        # Should fail because users already exist
        assert response.status_code == 403
