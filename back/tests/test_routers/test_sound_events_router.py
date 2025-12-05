"""Test suite for sound events router endpoints."""

from uuid import uuid4

from fastapi.testclient import TestClient

from echoroo import schemas


class TestGetSoundEvents:
    """Test GET /sound_events endpoints."""

    async def test_list_sound_events(
        self,
        client: TestClient,
    ):
        """Test listing sound events with pagination."""
        response = client.get("/api/v1/sound_events/")
        assert response.status_code == 200
        content = response.json()
        assert "items" in content
        assert "total" in content
        assert "limit" in content
        assert "offset" in content

    async def test_list_sound_events_with_limit(
        self,
        client: TestClient,
    ):
        """Test listing sound events with custom limit."""
        response = client.get(
            "/api/v1/sound_events/",
            params={"limit": 5},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["limit"] == 5
        assert len(content["items"]) <= 5

    async def test_list_sound_events_with_offset(
        self,
        client: TestClient,
    ):
        """Test listing sound events with offset."""
        response = client.get(
            "/api/v1/sound_events/",
            params={"offset": 10},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["offset"] == 10

    async def test_list_sound_events_with_sort(
        self,
        client: TestClient,
    ):
        """Test listing sound events with sort."""
        response = client.get(
            "/api/v1/sound_events/",
            params={"sort_by": "created_on"},
        )
        assert response.status_code == 200
        content = response.json()
        assert "items" in content

    async def test_get_sound_event_detail(
        self,
        client: TestClient,
    ):
        """Test getting a specific sound event - returns 404 if not found."""
        response = client.get(
            "/api/v1/sound_events/detail/",
            params={"sound_event_uuid": str(uuid4())},
        )
        assert response.status_code == 404

    async def test_get_sound_event_with_invalid_uuid_format(
        self,
        client: TestClient,
    ):
        """Test getting sound event with invalid UUID format."""
        response = client.get(
            "/api/v1/sound_events/detail/",
            params={"sound_event_uuid": "not-a-uuid"},
        )
        assert response.status_code == 422

    async def test_get_sound_event_recording(
        self,
        client: TestClient,
    ):
        """Test getting recording for sound event - returns 404 if not found."""
        response = client.get(
            "/api/v1/sound_events/detail/recording/",
            params={"sound_event_uuid": str(uuid4())},
        )
        assert response.status_code == 404

    async def test_get_sound_event_recording_with_invalid_uuid(
        self,
        client: TestClient,
    ):
        """Test getting recording with invalid sound event UUID format."""
        response = client.get(
            "/api/v1/sound_events/detail/recording/",
            params={"sound_event_uuid": "not-a-uuid"},
        )
        assert response.status_code == 422


class TestCreateSoundEvent:
    """Test POST /sound_events endpoints."""

    async def test_create_sound_event_for_nonexistent_recording(
        self,
        client: TestClient,
    ):
        """Test creating a sound event for nonexistent recording returns 404."""
        response = client.post(
            "/api/v1/sound_events/",
            params={"recording_uuid": str(uuid4())},
            json={"geometry": {"type": "BoundingBox", "coordinates": [0, 0, 1, 1]}},
        )
        assert response.status_code == 404

    async def test_create_sound_event_with_invalid_recording_uuid(
        self,
        client: TestClient,
    ):
        """Test creating sound event with invalid recording UUID format."""
        response = client.post(
            "/api/v1/sound_events/",
            params={"recording_uuid": "not-a-uuid"},
            json={"geometry": {"type": "BoundingBox", "coordinates": [0, 0, 1, 1]}},
        )
        assert response.status_code == 422

    async def test_create_sound_event_with_missing_geometry(
        self,
        client: TestClient,
    ):
        """Test creating sound event with missing geometry."""
        response = client.post(
            "/api/v1/sound_events/",
            params={"recording_uuid": str(uuid4())},
            json={},
        )
        assert response.status_code == 422


class TestUpdateSoundEvent:
    """Test PATCH /sound_events/detail endpoints."""

    async def test_update_nonexistent_sound_event_returns_error(
        self,
        client: TestClient,
    ):
        """Test updating a nonexistent sound event returns error."""
        response = client.patch(
            "/api/v1/sound_events/detail/",
            params={"sound_event_uuid": str(uuid4())},
            json={"geometry": None},
        )
        # May return 422 or 404 depending on validation order
        assert response.status_code in [404, 422]

    async def test_update_sound_event_with_invalid_uuid_format(
        self,
        client: TestClient,
    ):
        """Test updating sound event with invalid UUID format."""
        response = client.patch(
            "/api/v1/sound_events/detail/",
            params={"sound_event_uuid": "not-a-uuid"},
            json={},
        )
        assert response.status_code == 422


class TestSoundEventFeatures:
    """Test sound event feature operations."""

    async def test_add_feature_to_nonexistent_sound_event_returns_404(
        self,
        client: TestClient,
    ):
        """Test adding feature to nonexistent sound event returns 404."""
        response = client.post(
            "/api/v1/sound_events/detail/features/",
            params={
                "sound_event_uuid": str(uuid4()),
                "name": "test_feature",
                "value": 0.5,
            },
        )
        assert response.status_code == 404

    async def test_remove_feature_from_nonexistent_sound_event_returns_404(
        self,
        client: TestClient,
    ):
        """Test removing feature from nonexistent sound event returns 404."""
        response = client.delete(
            "/api/v1/sound_events/detail/features/",
            params={
                "sound_event_uuid": str(uuid4()),
                "name": "test_feature",
                "value": 0.5,
            },
        )
        assert response.status_code == 404

    async def test_add_feature_with_invalid_sound_event_uuid(
        self,
        client: TestClient,
    ):
        """Test adding feature with invalid sound event UUID format."""
        response = client.post(
            "/api/v1/sound_events/detail/features/",
            params={
                "sound_event_uuid": "not-a-uuid",
                "name": "test_feature",
                "value": 0.5,
            },
        )
        assert response.status_code == 422

    async def test_remove_feature_with_invalid_sound_event_uuid(
        self,
        client: TestClient,
    ):
        """Test removing feature with invalid sound event UUID format."""
        response = client.delete(
            "/api/v1/sound_events/detail/features/",
            params={
                "sound_event_uuid": "not-a-uuid",
                "name": "test_feature",
                "value": 0.5,
            },
        )
        assert response.status_code == 422
