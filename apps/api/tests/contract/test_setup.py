"""Contract tests for setup endpoints.

These tests verify that the API contract matches the OpenAPI specification.
Tests should fail initially (TDD) until implementation is complete.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestSetupStatusEndpoint:
    """Test GET /api/v1/setup/status endpoint contract."""

    async def test_get_setup_status_initial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup status when no users exist (initial state).

        Expected:
            - Status 200
            - setup_required: true
            - setup_completed: false
        """
        response = await client.get("/api/v1/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert "setup_required" in data
        assert "setup_completed" in data
        assert data["setup_required"] is True
        assert data["setup_completed"] is False

    async def test_get_setup_status_after_completion(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup status after initial setup is completed.

        Expected:
            - Status 200
            - setup_required: false
            - setup_completed: true
        """
        # First, complete the initial setup
        await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
                "display_name": "System Admin",
            },
        )

        # Then check status
        response = await client.get("/api/v1/setup/status")

        assert response.status_code == 200
        data = response.json()
        assert data["setup_required"] is False
        assert data["setup_completed"] is True


@pytest.mark.asyncio
class TestSetupInitializeEndpoint:
    """Test POST /api/v1/setup/initialize endpoint contract."""

    async def test_initialize_setup_success(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test successful initial setup with first admin user.

        Expected:
            - Status 201
            - Returns user object with id, email, display_name
            - Password is NOT returned
            - User is marked as superuser and verified
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
                "display_name": "Admin User",
            },
        )

        assert response.status_code == 201
        data = response.json()

        # Verify user structure
        assert "id" in data
        assert "email" in data
        assert "display_name" in data
        assert "is_superuser" in data
        assert "is_verified" in data
        assert "is_active" in data
        assert "created_at" in data

        # Verify values
        assert data["email"] == "admin@example.com"
        assert data["display_name"] == "Admin User"
        assert data["is_superuser"] is True
        assert data["is_verified"] is True
        assert data["is_active"] is True

        # Ensure password is NOT in response
        assert "password" not in data
        assert "hashed_password" not in data

    async def test_initialize_setup_minimal_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup with only required fields (email and password).

        Expected:
            - Status 201
            - display_name is None or empty
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "admin@example.com"
        # display_name can be None
        assert "display_name" in data

    async def test_initialize_setup_invalid_email(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup with invalid email format.

        Expected:
            - Status 422 (Validation Error)
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "not-an-email",
                "password": "SecurePassword123!",
            },
        )

        assert response.status_code == 422

    async def test_initialize_setup_short_password(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup with password shorter than 8 characters.

        Expected:
            - Status 422 (Validation Error)
        """
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "short",
            },
        )

        assert response.status_code == 422

    async def test_initialize_setup_already_completed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup when already completed (second attempt).

        Expected:
            - Status 403 (Forbidden)
            - Error message indicating setup already completed
        """
        # First setup
        await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SecurePassword123!",
            },
        )

        # Second attempt should fail
        response = await client.post(
            "/api/v1/setup/initialize",
            json={
                "email": "another@example.com",
                "password": "AnotherPassword123!",
            },
        )

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data

    async def test_initialize_setup_missing_required_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Test setup without required fields.

        Expected:
            - Status 422 (Validation Error)
        """
        # Missing password
        response = await client.post(
            "/api/v1/setup/initialize",
            json={"email": "admin@example.com"},
        )
        assert response.status_code == 422

        # Missing email
        response = await client.post(
            "/api/v1/setup/initialize",
            json={"password": "SecurePassword123!"},
        )
        assert response.status_code == 422

        # Empty body
        response = await client.post("/api/v1/setup/initialize", json={})
        assert response.status_code == 422
