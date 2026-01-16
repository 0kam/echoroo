"""Contract tests for recorder admin endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.recorder import Recorder
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
async def test_recorder(db_session: AsyncSession) -> Recorder:
    """Create a test recorder.

    Args:
        db_session: Database session

    Returns:
        Recorder instance
    """
    recorder = Recorder(
        id="am120",
        manufacturer="AudioMoth",
        recorder_name="AudioMoth 1.2.0",
        version="1.2.0",
    )
    db_session.add(recorder)
    await db_session.commit()
    await db_session.refresh(recorder)
    return recorder


class TestListRecorders:
    """Tests for listing recorders."""

    async def test_list_recorders_empty(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test listing recorders when none exist."""
        response = await client.get("/api/v1/admin/recorders", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["limit"] == 20

    async def test_list_recorders_with_data(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test listing recorders with existing data."""
        response = await client.get("/api/v1/admin/recorders", headers=superuser_headers)

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1
        assert data["items"][0]["id"] == test_recorder.id
        assert data["items"][0]["manufacturer"] == test_recorder.manufacturer
        assert data["items"][0]["recorder_name"] == test_recorder.recorder_name
        assert data["items"][0]["version"] == test_recorder.version

    async def test_list_recorders_pagination(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        db_session: AsyncSession,
    ) -> None:
        """Test recorder list pagination."""
        # Create multiple recorders
        for i in range(25):
            recorder = Recorder(
                id=f"recorder{i}",
                manufacturer=f"Manufacturer {i}",
                recorder_name=f"Recorder {i}",
                version=f"v{i}",
            )
            db_session.add(recorder)
        await db_session.commit()

        # Test first page
        response = await client.get(
            "/api/v1/admin/recorders?page=1&limit=10",
            headers=superuser_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 10
        assert data["total"] == 25
        assert data["page"] == 1
        assert data["limit"] == 10

        # Test second page
        response = await client.get(
            "/api/v1/admin/recorders?page=2&limit=10",
            headers=superuser_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 10
        assert data["total"] == 25
        assert data["page"] == 2

    async def test_list_recorders_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test listing recorders as non-superuser returns 403."""
        response = await client.get("/api/v1/admin/recorders", headers=regular_user_headers)

        assert response.status_code == 403

    async def test_list_recorders_unauthorized(
        self,
        client: AsyncClient,
    ) -> None:
        """Test listing recorders without authentication returns 401."""
        response = await client.get("/api/v1/admin/recorders")

        assert response.status_code == 401


class TestCreateRecorder:
    """Tests for creating recorders."""

    async def test_create_recorder_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test successful recorder creation."""
        response = await client.post(
            "/api/v1/admin/recorders",
            headers=superuser_headers,
            json={
                "id": "sm4",
                "manufacturer": "Wildlife Acoustics",
                "recorder_name": "Song Meter SM4",
                "version": "1.0",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "sm4"
        assert data["manufacturer"] == "Wildlife Acoustics"
        assert data["recorder_name"] == "Song Meter SM4"
        assert data["version"] == "1.0"
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_recorder_without_version(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test creating recorder without version field."""
        response = await client.post(
            "/api/v1/admin/recorders",
            headers=superuser_headers,
            json={
                "id": "generic",
                "manufacturer": "Generic",
                "recorder_name": "Generic Recorder",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["id"] == "generic"
        assert data["version"] is None

    async def test_create_recorder_duplicate_id(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test creating recorder with duplicate ID returns 409."""
        response = await client.post(
            "/api/v1/admin/recorders",
            headers=superuser_headers,
            json={
                "id": test_recorder.id,
                "manufacturer": "Another Manufacturer",
                "recorder_name": "Another Recorder",
            },
        )

        assert response.status_code == 409
        data = response.json()
        assert "already exists" in data["detail"].lower()

    async def test_create_recorder_missing_required_fields(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test creating recorder without required fields returns 422."""
        response = await client.post(
            "/api/v1/admin/recorders",
            headers=superuser_headers,
            json={"id": "incomplete"},
        )

        assert response.status_code == 422

    async def test_create_recorder_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
    ) -> None:
        """Test creating recorder as non-superuser returns 403."""
        response = await client.post(
            "/api/v1/admin/recorders",
            headers=regular_user_headers,
            json={
                "id": "test",
                "manufacturer": "Test",
                "recorder_name": "Test Recorder",
            },
        )

        assert response.status_code == 403


class TestGetRecorder:
    """Tests for getting a specific recorder."""

    async def test_get_recorder_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test getting a recorder by ID."""
        response = await client.get(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=superuser_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_recorder.id
        assert data["manufacturer"] == test_recorder.manufacturer
        assert data["recorder_name"] == test_recorder.recorder_name
        assert data["version"] == test_recorder.version

    async def test_get_recorder_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test getting non-existent recorder returns 404."""
        response = await client.get(
            "/api/v1/admin/recorders/nonexistent",
            headers=superuser_headers,
        )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()

    async def test_get_recorder_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test getting recorder as non-superuser returns 403."""
        response = await client.get(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=regular_user_headers,
        )

        assert response.status_code == 403


class TestUpdateRecorder:
    """Tests for updating recorders."""

    async def test_update_recorder_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test successful recorder update."""
        response = await client.patch(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=superuser_headers,
            json={
                "manufacturer": "Updated Manufacturer",
                "recorder_name": "Updated Recorder",
                "version": "2.0.0",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_recorder.id
        assert data["manufacturer"] == "Updated Manufacturer"
        assert data["recorder_name"] == "Updated Recorder"
        assert data["version"] == "2.0.0"

    async def test_update_recorder_partial(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test partial update of recorder."""
        response = await client.patch(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=superuser_headers,
            json={"version": "1.3.0"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_recorder.id
        assert data["manufacturer"] == test_recorder.manufacturer  # Unchanged
        assert data["recorder_name"] == test_recorder.recorder_name  # Unchanged
        assert data["version"] == "1.3.0"  # Updated

    async def test_update_recorder_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test updating non-existent recorder returns 404."""
        response = await client.patch(
            "/api/v1/admin/recorders/nonexistent",
            headers=superuser_headers,
            json={"manufacturer": "Test"},
        )

        assert response.status_code == 404

    async def test_update_recorder_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test updating recorder as non-superuser returns 403."""
        response = await client.patch(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=regular_user_headers,
            json={"manufacturer": "Test"},
        )

        assert response.status_code == 403


class TestDeleteRecorder:
    """Tests for deleting recorders."""

    async def test_delete_recorder_success(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test successful recorder deletion."""
        response = await client.delete(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=superuser_headers,
        )

        assert response.status_code == 204

        # Verify recorder is deleted
        get_response = await client.get(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=superuser_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_recorder_not_found(
        self,
        client: AsyncClient,
        superuser_headers: dict[str, str],
    ) -> None:
        """Test deleting non-existent recorder returns 404."""
        response = await client.delete(
            "/api/v1/admin/recorders/nonexistent",
            headers=superuser_headers,
        )

        assert response.status_code == 404

    async def test_delete_recorder_as_non_superuser_forbidden(
        self,
        client: AsyncClient,
        regular_user_headers: dict[str, str],
        test_recorder: Recorder,
    ) -> None:
        """Test deleting recorder as non-superuser returns 403."""
        response = await client.delete(
            f"/api/v1/admin/recorders/{test_recorder.id}",
            headers=regular_user_headers,
        )

        assert response.status_code == 403
