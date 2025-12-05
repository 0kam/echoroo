"""Test suite for notes endpoints."""

from uuid import uuid4

from fastapi.testclient import TestClient

from echoroo import schemas


class TestNotes:
    """Test note endpoints."""

    async def test_list_notes(
        self,
        client: TestClient,
    ):
        """Test listing notes."""
        response = client.get("/api/v1/notes/")
        assert response.status_code == 200
        content = response.json()
        assert "items" in content
        assert "total" in content
        assert "limit" in content
        assert "offset" in content

    async def test_list_notes_with_limit(
        self,
        client: TestClient,
    ):
        """Test listing notes with limit."""
        response = client.get(
            "/api/v1/notes/",
            params={"limit": 5},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["limit"] == 5

    async def test_list_notes_with_offset(
        self,
        client: TestClient,
    ):
        """Test listing notes with offset."""
        response = client.get(
            "/api/v1/notes/",
            params={"offset": 10},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["offset"] == 10

    async def test_list_notes_with_sort(
        self,
        client: TestClient,
    ):
        """Test listing notes with sort."""
        response = client.get(
            "/api/v1/notes/",
            params={"sort_by": "created_on"},
        )
        assert response.status_code == 200
        content = response.json()
        assert "items" in content

    async def test_get_nonexistent_note_returns_404(
        self,
        client: TestClient,
    ):
        """Test getting a nonexistent note returns 404."""
        response = client.get(
            "/api/v1/notes/detail/",
            params={"note_uuid": str(uuid4())},
        )
        assert response.status_code == 404


class TestRecordingNotes:
    """Test recording note endpoints."""

    async def test_list_recording_notes(
        self,
        client: TestClient,
        recording: schemas.Recording,
    ):
        """Test listing recording notes."""
        response = client.get("/api/v1/notes/recording_notes/")
        assert response.status_code == 200
        content = response.json()
        assert "items" in content
        assert "total" in content

    async def test_list_recording_notes_with_recording_filter(
        self,
        client: TestClient,
        recording: schemas.Recording,
    ):
        """Test listing recording notes filtered by recording."""
        response = client.get(
            "/api/v1/notes/recording_notes/",
            params={"recording_uuid": str(recording.uuid)},
        )
        assert response.status_code == 200
        content = response.json()
        assert "items" in content


class TestClipAnnotationNotes:
    """Test clip annotation note endpoints."""

    async def test_list_clip_annotation_notes(
        self,
        client: TestClient,
        clip_annotation: schemas.ClipAnnotation,
    ):
        """Test listing clip annotation notes."""
        response = client.get("/api/v1/notes/clip_annotation_notes/")
        assert response.status_code == 200
        content = response.json()
        assert "items" in content
        assert "total" in content

    async def test_list_clip_annotation_notes_with_limit(
        self,
        client: TestClient,
    ):
        """Test listing clip annotation notes with limit."""
        response = client.get(
            "/api/v1/notes/clip_annotation_notes/",
            params={"limit": 5},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["limit"] == 5
        assert "items" in content


class TestSoundEventAnnotationNotes:
    """Test sound event annotation note endpoints."""

    async def test_list_sound_event_annotation_notes(
        self,
        client: TestClient,
        sound_event_annotation: schemas.SoundEventAnnotation,
    ):
        """Test listing sound event annotation notes."""
        response = client.get("/api/v1/notes/sound_event_annotation_notes/")
        assert response.status_code == 200
        content = response.json()
        assert "items" in content
        assert "total" in content

    async def test_list_sound_event_annotation_notes_with_limit(
        self,
        client: TestClient,
    ):
        """Test listing sound event annotation notes with limit."""
        response = client.get(
            "/api/v1/notes/sound_event_annotation_notes/",
            params={"limit": 5},
        )
        assert response.status_code == 200
        content = response.json()
        assert content["limit"] == 5
        assert "items" in content
