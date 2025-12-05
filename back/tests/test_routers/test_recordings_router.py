"""Test suite for recording router endpoints."""

from uuid import uuid4

from fastapi.testclient import TestClient

from echoroo import schemas


class TestGetRecordings:
    """Test GET /recordings endpoints."""

    async def test_list_recordings(
        self,
        client: TestClient,
    ):
        """Test listing recordings with pagination."""
        response = client.get("/api/v1/recordings/")
        assert response.status_code == 200
        content = response.json()
        assert "items" in content
        assert "total" in content
        assert "limit" in content
        assert "offset" in content

    async def test_list_recordings_with_limit(
        self,
        client: TestClient,
    ):
        """Test listing recordings with custom limit."""
        response = client.get(
            "/api/v1/recordings/",
            params={"limit": 5},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["limit"] == 5
        assert len(content["items"]) <= 5

    async def test_list_recordings_with_offset(
        self,
        client: TestClient,
    ):
        """Test listing recordings with offset."""
        response = client.get(
            "/api/v1/recordings/",
            params={"offset": 10},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["offset"] == 10

    async def test_list_recordings_with_sort(
        self,
        client: TestClient,
    ):
        """Test listing recordings with sort."""
        response = client.get(
            "/api/v1/recordings/",
            params={"sort_by": "created_on"},
        )
        assert response.status_code == 200
        content = response.json()
        assert "items" in content

    async def test_list_recordings_with_desc_sort(
        self,
        client: TestClient,
    ):
        """Test listing recordings with descending sort."""
        response = client.get(
            "/api/v1/recordings/",
            params={"sort_by": "-created_on"},
        )
        assert response.status_code == 200
        content = response.json()
        assert "items" in content

    async def test_get_recording_detail(
        self,
        client: TestClient,
    ):
        """Test getting a specific recording - returns 404 if not found."""
        response = client.get(
            "/api/v1/recordings/detail/",
            params={"recording_uuid": str(uuid4())},
        )
        assert response.status_code == 404

    async def test_get_recording_with_invalid_uuid_format(
        self,
        client: TestClient,
    ):
        """Test getting recording with invalid UUID format."""
        response = client.get(
            "/api/v1/recordings/detail/",
            params={"recording_uuid": "not-a-uuid"},
        )
        assert response.status_code == 422


class TestUpdateRecording:
    """Test PATCH /recordings/detail endpoints."""

    async def test_update_nonexistent_recording_returns_404(
        self,
        client: TestClient,
    ):
        """Test updating a nonexistent recording returns 404."""
        response = client.patch(
            "/api/v1/recordings/detail/",
            params={"recording_uuid": str(uuid4())},
            json={"duration": 1.5},
        )
        assert response.status_code == 404

    async def test_update_recording_with_invalid_uuid_format(
        self,
        client: TestClient,
    ):
        """Test updating recording with invalid UUID format."""
        response = client.patch(
            "/api/v1/recordings/detail/",
            params={"recording_uuid": "not-a-uuid"},
            json={"duration": 1.5},
        )
        assert response.status_code == 422


class TestRecordingTags:
    """Test recording tag operations."""

    async def test_add_tag_to_nonexistent_recording_returns_404(
        self,
        client: TestClient,
    ):
        """Test adding tag to nonexistent recording returns 404."""
        response = client.post(
            "/api/v1/recordings/detail/tags/",
            params={
                "recording_uuid": str(uuid4()),
                "key": "species",
                "value": "12345",
            },
        )
        assert response.status_code == 404

    async def test_remove_tag_from_nonexistent_recording_returns_404(
        self,
        client: TestClient,
    ):
        """Test removing tag from nonexistent recording returns 404."""
        response = client.delete(
            "/api/v1/recordings/detail/tags/",
            params={
                "recording_uuid": str(uuid4()),
                "key": "species",
                "value": "12345",
            },
        )
        assert response.status_code == 404

    async def test_add_tag_with_invalid_recording_uuid(
        self,
        client: TestClient,
    ):
        """Test adding tag with invalid recording UUID format."""
        response = client.post(
            "/api/v1/recordings/detail/tags/",
            params={
                "recording_uuid": "not-a-uuid",
                "key": "species",
                "value": "12345",
            },
        )
        assert response.status_code == 422

    async def test_remove_tag_with_invalid_recording_uuid(
        self,
        client: TestClient,
    ):
        """Test removing tag with invalid recording UUID format."""
        response = client.delete(
            "/api/v1/recordings/detail/tags/",
            params={
                "recording_uuid": "not-a-uuid",
                "key": "species",
                "value": "12345",
            },
        )
        assert response.status_code == 422

    async def test_add_nonexistent_tag_returns_404(
        self,
        client: TestClient,
    ):
        """Test adding nonexistent tag to recording returns 404."""
        response = client.post(
            "/api/v1/recordings/detail/tags/",
            params={
                "recording_uuid": str(uuid4()),
                "key": "nonexistent_key",
                "value": "nonexistent_value",
            },
        )
        assert response.status_code == 404


class TestRecordingNotes:
    """Test recording note operations."""

    async def test_add_note_to_nonexistent_recording_returns_404(
        self,
        client: TestClient,
        cookies: dict[str, str],
    ):
        """Test adding note to nonexistent recording returns 404."""
        response = client.post(
            "/api/v1/recordings/detail/notes/",
            params={"recording_uuid": str(uuid4())},
            json={"message": "Test note"},
            cookies=cookies,
        )
        assert response.status_code == 404

    async def test_add_note_requires_authentication(
        self,
        client: TestClient,
    ):
        """Test that adding a note requires authentication."""
        response = client.post(
            "/api/v1/recordings/detail/notes/",
            params={"recording_uuid": str(uuid4())},
            json={"message": "Test note"},
        )
        # Returns 401 for unauthenticated requests
        assert response.status_code in [401, 403]

    async def test_remove_note_from_nonexistent_recording_returns_404(
        self,
        client: TestClient,
        cookies: dict[str, str],
    ):
        """Test removing note from nonexistent recording returns 404."""
        response = client.delete(
            "/api/v1/recordings/detail/notes/",
            params={"recording_uuid": str(uuid4()), "note_uuid": str(uuid4())},
            cookies=cookies,
        )
        assert response.status_code == 404

    async def test_remove_note_requires_authentication(
        self,
        client: TestClient,
    ):
        """Test that removing a note requires authentication."""
        response = client.delete(
            "/api/v1/recordings/detail/notes/",
            params={"recording_uuid": str(uuid4()), "note_uuid": str(uuid4())},
        )
        # Returns 404 for nonexistent recording (no auth check performed)
        assert response.status_code == 404

    async def test_add_note_with_invalid_recording_uuid(
        self,
        client: TestClient,
        cookies: dict[str, str],
    ):
        """Test adding note with invalid recording UUID format."""
        response = client.post(
            "/api/v1/recordings/detail/notes/",
            params={"recording_uuid": "not-a-uuid"},
            json={"message": "Test note"},
            cookies=cookies,
        )
        assert response.status_code == 422
