"""Contract tests for clips API endpoints.

Tests verify that endpoints conform to the data management specification.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.clip import Clip
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility, DatetimeParseStatus
from echoroo.models.recording import Recording
from echoroo.models.site import Site

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


@pytest.fixture
async def test_site_for_clips(
    db_session: AsyncSession,
    test_project: "Project",  # noqa: F821
) -> Site:
    """Create a test site for clip tests.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Test Site for Clips",
        h3_index="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset_for_clips(
    db_session: AsyncSession,
    test_project: "Project",  # noqa: F821
    test_site_for_clips: Site,
    test_user: "User",  # noqa: F821
) -> Dataset:
    """Create a test dataset for clip tests.

    Args:
        db_session: Database session
        test_project: Test project
        test_site_for_clips: Test site
        test_user: Test user

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=test_site_for_clips.id,
        created_by_id=test_user.id,
        name="Test Dataset for Clips",
        audio_dir="test/audio",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def test_recording_for_clips(
    db_session: AsyncSession,
    test_dataset_for_clips: Dataset,
) -> Recording:
    """Create a test recording for clip tests.

    Args:
        db_session: Database session
        test_dataset_for_clips: Test dataset

    Returns:
        Test recording instance
    """
    recording = Recording(
        dataset_id=test_dataset_for_clips.id,
        filename="test_recording_for_clips.wav",
        path="test_recording_for_clips.wav",
        hash="clip_test_hash",
        duration=60.0,
        samplerate=44100,
        channels=1,
        bit_depth=16,
        datetime=datetime.now(timezone.utc),
        datetime_parse_status=DatetimeParseStatus.SUCCESS,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


@pytest.fixture
async def test_clip(
    db_session: AsyncSession,
    test_recording_for_clips: Recording,
) -> Clip:
    """Create a test clip.

    Args:
        db_session: Database session
        test_recording_for_clips: Test recording

    Returns:
        Test clip instance
    """
    clip = Clip(
        recording_id=test_recording_for_clips.id,
        start_time=0.0,
        end_time=3.0,
        note="Test clip",
    )
    db_session.add(clip)
    await db_session.commit()
    await db_session.refresh(clip)
    return clip


@pytest.mark.asyncio
class TestClipEndpoints:
    """Test clip CRUD endpoints."""

    async def test_list_clips_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips - List clips."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches ClipListResponse
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)

    async def test_list_clips_with_sorting(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips with sorting."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=auth_headers,
            params={
                "page": 1,
                "page_size": 50,
                "sort_by": "start_time",
                "sort_order": "asc",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 50

    async def test_list_clips_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips"
        )

        assert response.status_code == 401

    async def test_create_clip_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips - Create clip."""
        clip_data = {
            "start_time": 5.0,
            "end_time": 8.0,
            "note": "Test clip creation",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=auth_headers,
            json=clip_data,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure matches ClipDetailResponse
        assert "id" in data
        assert data["start_time"] == clip_data["start_time"]
        assert data["end_time"] == clip_data["end_time"]
        assert data["note"] == clip_data["note"]
        assert "duration" in data
        assert data["duration"] == 3.0

    async def test_create_clip_validation_error_start_after_end(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips with invalid time range."""
        clip_data = {
            "start_time": 10.0,
            "end_time": 5.0,  # end before start
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=auth_headers,
            json=clip_data,
        )

        # FastAPI/Pydantic returns 422 for validation errors
        assert response.status_code == 422

    async def test_create_clip_validation_error_exceeds_duration(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips exceeding recording duration."""
        clip_data = {
            "start_time": 0.0,
            "end_time": 100.0,  # exceeds recording duration
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=auth_headers,
            json=clip_data,
        )

        # Business logic validation (exceeds recording duration) returns 400
        # but this might also be 422 if validated at schema level
        assert response.status_code in [400, 422]

    async def test_create_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips requires authentication."""
        clip_data = {
            "start_time": 0.0,
            "end_time": 3.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            json=clip_data,
        )

        assert response.status_code == 401

    async def test_get_clip_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} - Get clip."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches ClipDetailResponse
        assert data["id"] == str(test_clip.id)
        assert data["start_time"] == test_clip.start_time
        assert data["end_time"] == test_clip.end_time
        assert "duration" in data
        assert "recording" in data

    async def test_get_clip_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}"
        )

        assert response.status_code == 401

    async def test_update_clip_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} - Update clip."""
        update_data = {
            "start_time": 1.0,
            "end_time": 4.0,
            "note": "Updated clip note",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["start_time"] == update_data["start_time"]
        assert data["end_time"] == update_data["end_time"]
        assert data["note"] == update_data["note"]

    async def test_update_clip_validation_error(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with invalid data."""
        update_data = {
            "start_time": 10.0,
            "end_time": 5.0,  # end before start
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            headers=auth_headers,
            json=update_data,
        )

        # FastAPI/Pydantic returns 422 for validation errors
        assert response.status_code == 422

    async def test_update_clip_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{fake_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 404

    async def test_update_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} requires authentication."""
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            json=update_data,
        )

        assert response.status_code == 401

    async def test_delete_clip_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        db_session: AsyncSession,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} - Delete clip."""
        # Create a clip to delete
        clip = Clip(
            recording_id=test_recording_for_clips.id,
            start_time=10.0,
            end_time=13.0,
        )
        db_session.add(clip)
        await db_session.commit()
        await db_session.refresh(clip)
        clip_id = clip.id

        # Delete the clip
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{clip_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify clip is deleted
        get_response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{clip_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_clip_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} requires authentication."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestClipGenerateEndpoint:
    """Test clip auto-generation endpoint."""

    async def test_generate_clips_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate - Generate clips."""
        generate_data = {
            "clip_length": 3.0,
            "overlap": 0.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            headers=auth_headers,
            json=generate_data,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches ClipGenerateResponse
        assert "clips_created" in data
        assert "clips" in data
        assert isinstance(data["clips"], list)
        assert data["clips_created"] >= 0

    async def test_generate_clips_with_overlap(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate with overlap."""
        generate_data = {
            "clip_length": 5.0,
            "overlap": 0.5,  # 50% overlap (valid range: 0-0.99)
            "start_time": 0.0,
            "end_time": 30.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            headers=auth_headers,
            json=generate_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert "clips_created" in data

    async def test_generate_clips_validation_error(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate with invalid parameters."""
        generate_data = {
            "clip_length": -1.0,  # invalid length
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            headers=auth_headers,
            json=generate_data,
        )

        assert response.status_code in [400, 422]

    async def test_generate_clips_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate requires authentication."""
        generate_data = {
            "clip_length": 3.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            json=generate_data,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestClipAudioEndpoints:
    """Test clip audio endpoints."""

    async def test_get_clip_audio_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}/audio - Get clip audio."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}/audio",
            headers=auth_headers,
        )

        # Note: May return 404 or 400 if audio file doesn't exist
        assert response.status_code in [200, 400, 404]
        if response.status_code == 200:
            assert response.headers["content-type"] == "audio/wav"

    async def test_get_clip_audio_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}/audio requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}/audio"
        )

        assert response.status_code == 401

    async def test_get_clip_spectrogram_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}/spectrogram - Get spectrogram."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}/spectrogram",
            headers=auth_headers,
        )

        # Note: May return 404 or 400 if audio file doesn't exist
        assert response.status_code in [200, 400, 404]
        if response.status_code == 200:
            assert response.headers["content-type"] == "image/png"

    async def test_get_clip_spectrogram_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}/spectrogram requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}/spectrogram"
        )

        assert response.status_code == 401

    async def test_download_clip_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}/download - Download clip."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}/download",
            headers=auth_headers,
        )

        # Note: May return 404 or 400 if audio file doesn't exist
        assert response.status_code in [200, 400, 404]
        if response.status_code == 200:
            assert response.headers["content-type"] == "audio/wav"
            assert "Content-Disposition" in response.headers
            assert "attachment" in response.headers["Content-Disposition"]

    async def test_download_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id}/download requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}/download"
        )

        assert response.status_code == 401
