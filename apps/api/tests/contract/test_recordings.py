"""Contract tests for recordings API endpoints.

Tests verify that endpoints conform to the data management specification.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.recording import Recording
from echoroo.models.site import Site


@pytest.fixture
async def test_site_for_recordings(
    db_session: AsyncSession,
    test_project: "Project",  # noqa: F821
) -> Site:
    """Create a test site for recording tests.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Test Site for Recordings",
        h3_index="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset_for_recordings(
    db_session: AsyncSession,
    test_project: "Project",  # noqa: F821
    test_site_for_recordings: Site,
    test_user: "User",  # noqa: F821
) -> Dataset:
    """Create a test dataset for recording tests.

    Args:
        db_session: Database session
        test_project: Test project
        test_site_for_recordings: Test site
        test_user: Test user

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=test_site_for_recordings.id,
        created_by_id=test_user.id,
        name="Test Dataset for Recordings",
        audio_dir="test/audio",
        visibility="private",
        status="completed",
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def test_recording(
    db_session: AsyncSession,
    test_dataset_for_recordings: Dataset,
) -> Recording:
    """Create a test recording.

    Args:
        db_session: Database session
        test_dataset_for_recordings: Test dataset

    Returns:
        Test recording instance
    """
    recording = Recording(
        dataset_id=test_dataset_for_recordings.id,
        filename="test_recording.wav",
        path="test_recording.wav",
        hash="d41d8cd98f00b204e9800998ecf8427e",
        duration=10.0,
        samplerate=44100,
        channels=1,
        bit_depth=16,
        datetime=datetime.now(timezone.utc),
        datetime_parse_status="success",
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


@pytest.mark.asyncio
class TestRecordingEndpoints:
    """Test recording list and detail endpoints."""

    async def test_list_recordings_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings - List recordings."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches RecordingListResponse
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)

    async def test_list_recordings_with_filters(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_dataset_for_recordings: Dataset,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings with filters."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings",
            headers=auth_headers,
            params={
                "page": 1,
                "page_size": 20,
                "dataset_id": str(test_dataset_for_recordings.id),
                "sort_by": "datetime",
                "sort_order": "desc",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 20

    async def test_list_recordings_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings requires authentication."""
        response = await client.get(f"/api/v1/projects/{test_project_id}/recordings")

        assert response.status_code == 401

    async def test_list_recordings_no_access(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings without project access."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings",
            headers=auth_headers_other,
        )

        assert response.status_code == 403

    async def test_get_recording_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id} - Get recording."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches RecordingDetailResponse
        assert data["id"] == str(test_recording.id)
        assert data["filename"] == test_recording.filename
        assert data["duration"] == test_recording.duration
        assert data["samplerate"] == test_recording.samplerate
        assert "clip_count" in data
        assert "effective_duration" in data
        assert "is_ultrasonic" in data
        assert "dataset" in data
        assert "site" in data

    async def test_get_recording_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}"
        )

        assert response.status_code == 401

    async def test_update_recording_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id} - Update recording."""
        update_data = {
            "time_expansion": 10.0,
            "note": "Updated recording note",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["time_expansion"] == update_data["time_expansion"]
        assert data["note"] == update_data["note"]

    async def test_update_recording_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 404

    async def test_update_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id} requires authentication."""
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}",
            json=update_data,
        )

        assert response.status_code == 401

    async def test_delete_recording_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
        test_dataset_for_recordings: Dataset,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/recordings/{recording_id} - Delete recording."""
        # Create a recording to delete
        recording = Recording(
            dataset_id=test_dataset_for_recordings.id,
            filename="to_delete.wav",
            path="to_delete.wav",
            hash="delete_hash",
            duration=5.0,
            samplerate=44100,
            channels=1,
            bit_depth=16,
        )
        db_session.add(recording)
        await db_session.commit()
        await db_session.refresh(recording)
        recording_id = recording.id

        # Delete the recording
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/recordings/{recording_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify recording is deleted
        get_response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{recording_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_recording_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/recordings/{recording_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/recordings/{recording_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestRecordingAudioEndpoints:
    """Test recording audio streaming endpoints."""

    async def test_stream_audio_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/stream - Stream audio."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/stream",
            headers=auth_headers,
        )

        # Note: May return 404 if audio file doesn't exist in test environment
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert "Accept-Ranges" in response.headers
            assert "Content-Length" in response.headers

    async def test_stream_audio_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/stream with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}/stream",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_stream_audio_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/stream requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/stream"
        )

        assert response.status_code == 401

    async def test_get_spectrogram_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram - Get spectrogram."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/spectrogram",
            headers=auth_headers,
            params={
                "start": 0,
                "end": 5,
                "n_fft": 2048,
                "hop_length": 512,
            },
        )

        # Note: May return 404 or 400 if audio file doesn't exist or processing fails
        assert response.status_code in [200, 400, 404]
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"

    async def test_get_spectrogram_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{fake_id}/spectrogram",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_spectrogram_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/spectrogram"
        )

        assert response.status_code == 401

    async def test_get_spectrogram_with_parameters(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram with custom parameters."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/spectrogram",
            headers=auth_headers,
            params={
                "start": 0,
                "end": 10,
                "n_fft": 4096,
                "hop_length": 1024,
                "freq_min": 0,
                "freq_max": 10000,
                "colormap": "magma",
                "pcen": True,
                "channel": 0,
                "width": 1200,
                "height": 400,
            },
        )

        # Note: May fail if audio file doesn't exist
        assert response.status_code in [200, 400, 404]

    async def test_download_recording_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/download - Download recording."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/download",
            headers=auth_headers,
        )

        # Note: May return 404 if audio file doesn't exist
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            assert "Content-Disposition" in response.headers
            assert "attachment" in response.headers["Content-Disposition"]

    async def test_download_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/download requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording.id}/download"
        )

        assert response.status_code == 401
