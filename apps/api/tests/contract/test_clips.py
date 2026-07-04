"""Contract tests for clips API endpoints.

Tests verify that endpoints conform to the data management specification.

W2-3 PR-13 (2026-07-02): the 6 browser-superseded ``/api/v1/projects/{id}/
recordings/{rid}/clips*`` CRUD + generate routes were unmounted in favour of
the project-scoped ``/web-api/v1`` BFF (``_media.py`` GETs + ``_clips.py``
mutations). The BFF sits behind the session + CSRF middleware, so every
authenticated request — GET included — routes through a real
``bff_session_headers`` session (``csrf_headers`` for the owner,
``csrf_headers_other`` for the authenticated non-member 403 path). A plain
``create_access_token`` Bearer is treated as anonymous, so the no-auth cases
stay at 401 (auth fires before the permission gate). Clip writes gate on
``MANAGE_DATASET`` which MEMBER holds, so the owner session reaches 2xx (there
is no member-403 case, unlike datasets).

W2-4 PR-A (2026-07-04): the three ``/api/v1`` clip media routes (audio /
spectrogram / download) were unmounted in favour of the ``/web-api/v1`` BFF
media-token surface. The clip download route now lives at
``/web-api/v1/projects/{id}/recordings/{rid}/clips/{cid}/download`` and is
authenticated either by the session (``csrf_headers``) or by a clip-scoped
media token issued from
``POST /web-api/v1/.../clips/{cid}/media-token`` (``scope="download"``). The
former clip audio / spectrogram GETs had no BFF twin — clip audio/spectrogram
ride the recording-level playback / spectrogram BFF with clip start/end bounds
(covered by ``test_projects_recordings_media.py``) — so their v1-only contract
tests were removed here.
"""

from datetime import UTC, datetime
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
        h3_index_member="8928308280fffff",
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
        datetime=datetime.now(UTC),
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips - List clips."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips with sorting."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=csrf_headers,
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
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips requires authentication."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips"
        )

        assert response.status_code == 401

    async def test_create_clip_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips - Create clip."""
        clip_data = {
            "start_time": 5.0,
            "end_time": 8.0,
            "note": "Test clip creation",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips with invalid time range."""
        clip_data = {
            "start_time": 10.0,
            "end_time": 5.0,  # end before start
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=csrf_headers,
            json=clip_data,
        )

        # FastAPI/Pydantic returns 422 for validation errors
        assert response.status_code == 422

    async def test_create_clip_validation_error_exceeds_duration(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips exceeding recording duration."""
        clip_data = {
            "start_time": 0.0,
            "end_time": 100.0,  # exceeds recording duration
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            headers=csrf_headers,
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
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips requires authentication."""
        clip_data = {
            "start_time": 0.0,
            "end_time": 3.0,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips",
            json=clip_data,
        )

        assert response.status_code == 401

    async def test_get_clip_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} - Get clip."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} requires authentication."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}"
        )

        assert response.status_code == 401

    async def test_update_clip_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} - Update clip."""
        update_data = {
            "start_time": 1.0,
            "end_time": 4.0,
            "note": "Updated clip note",
        }

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with invalid data."""
        update_data = {
            "start_time": 10.0,
            "end_time": 5.0,  # end before start
        }

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            headers=csrf_headers,
            json=update_data,
        )

        # FastAPI/Pydantic returns 422 for validation errors
        assert response.status_code == 422

    async def test_update_clip_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{fake_id}",
            headers=csrf_headers,
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
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} requires authentication."""
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}",
            json=update_data,
        )

        assert response.status_code == 401

    async def test_delete_clip_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        db_session: AsyncSession,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} - Delete clip."""
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
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{clip_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 204

        # Verify clip is deleted
        get_response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{clip_id}",
            headers=csrf_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_clip_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_delete_clip_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} requires authentication."""
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/{test_clip.id}"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestClipGenerateEndpoint:
    """Test clip auto-generation endpoint."""

    async def test_generate_clips_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate - Generate clips."""
        generate_data = {
            "clip_length": 3.0,
            "overlap": 0.0,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate with overlap."""
        generate_data = {
            "clip_length": 5.0,
            "overlap": 0.5,  # 50% overlap (valid range: 0-0.99)
            "start_time": 0.0,
            "end_time": 30.0,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            headers=csrf_headers,
            json=generate_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert "clips_created" in data

    async def test_generate_clips_validation_error(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate with invalid parameters."""
        generate_data = {
            "clip_length": -1.0,  # invalid length
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            headers=csrf_headers,
            json=generate_data,
        )

        assert response.status_code in [400, 422]

    async def test_generate_clips_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate requires authentication."""
        generate_data = {
            "clip_length": 3.0,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}/clips/generate",
            json=generate_data,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestClipDownloadEndpoint:
    """Test the clip download BFF endpoint + its clip-scoped media token.

    W2-4 PR-A migrated the clip download route from ``/api/v1`` to the
    ``/web-api/v1`` BFF media-token surface. The former clip audio /
    spectrogram GETs had no BFF twin (they are served by the recording-level
    playback / spectrogram BFF with clip start/end bounds — see
    ``test_projects_recordings_media.py``), so only the download surface is
    covered here.
    """

    async def test_issue_clip_download_media_token_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """POST clips/{clip_id}/media-token issues a clip-scoped download token."""
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}"
            f"/clips/{test_clip.id}/media-token",
            headers=csrf_headers,
            json={"scope": "download"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["token"]
        assert body["expires_in"] > 0

    async def test_issue_clip_download_media_token_rejects_bad_scope(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """The clip media-token endpoint only accepts scope="download"."""
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}"
            f"/clips/{test_clip.id}/media-token",
            headers=csrf_headers,
            json={"scope": "playback"},
        )

        assert response.status_code == 422

    async def test_issue_clip_download_media_token_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """The clip media-token endpoint requires a session (401 when absent)."""
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}"
            f"/clips/{test_clip.id}/media-token",
            json={"scope": "download"},
        )

        assert response.status_code == 401

    async def test_download_clip_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording_for_clips: Recording,
        test_clip: Clip,
    ) -> None:
        """GET clips/{clip_id}/download streams the clip WAV (session-authed)."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}"
            f"/clips/{test_clip.id}/download",
            headers=csrf_headers,
        )

        # Note: May return 404 or 400 if the audio file doesn't exist in test env.
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
        """GET clips/{clip_id}/download requires a session (401 when absent).

        The BFF adapter authenticates via ``CurrentUser`` (session cookie /
        Bearer / clip-scoped media token), so a signed-out request is rejected
        at the auth layer before the permission gate runs.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording_for_clips.id}"
            f"/clips/{test_clip.id}/download"
        )

        assert response.status_code == 401
