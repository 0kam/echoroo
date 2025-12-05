"""Test suite for spectrogram endpoints."""

from uuid import uuid4

from fastapi.testclient import TestClient

from echoroo import schemas


class TestSpectrograms:
    """Test spectrogram endpoints."""

    async def test_get_spectrogram_invalid_recording_returns_404(
        self,
        client: TestClient,
    ):
        """Test getting a spectrogram for nonexistent recording returns 404."""
        response = client.get(
            "/api/v1/spectrograms/",
            params={
                "recording_uuid": str(uuid4()),
                "start_time": 0.0,
                "end_time": 0.1,
            },
        )
        assert response.status_code == 404

    async def test_get_spectrogram_missing_required_params_returns_422(
        self,
        client: TestClient,
    ):
        """Test that missing required parameters returns 422."""
        response = client.get(
            "/api/v1/spectrograms/",
            params={
                "recording_uuid": str(uuid4()),
                # Missing start_time and end_time
            },
        )
        assert response.status_code == 422

    async def test_get_spectrogram_with_invalid_recording_uuid(
        self,
        client: TestClient,
    ):
        """Test with invalid recording UUID format."""
        response = client.get(
            "/api/v1/spectrograms/",
            params={
                "recording_uuid": "not-a-uuid",
                "start_time": 0.0,
                "end_time": 0.1,
            },
        )
        assert response.status_code == 422

    async def test_get_spectrogram_with_negative_start_time(
        self,
        client: TestClient,
    ):
        """Test with negative start time."""
        response = client.get(
            "/api/v1/spectrograms/",
            params={
                "recording_uuid": str(uuid4()),
                "start_time": -1.0,
                "end_time": 0.1,
            },
        )
        # Should handle error gracefully
        assert response.status_code in [404, 422, 400]

    async def test_get_spectrogram_with_start_after_end(
        self,
        client: TestClient,
    ):
        """Test with start_time > end_time."""
        response = client.get(
            "/api/v1/spectrograms/",
            params={
                "recording_uuid": str(uuid4()),
                "start_time": 1.0,
                "end_time": 0.1,
            },
        )
        # Should return 404 for nonexistent recording
        assert response.status_code == 404
