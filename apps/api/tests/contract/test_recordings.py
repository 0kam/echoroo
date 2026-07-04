"""Contract tests for recordings API endpoints.

Tests verify that endpoints conform to the data management specification.

W2-3 PR-16 (2026-07-02): the 6 browser-superseded ``/api/v1/projects/{id}/
recordings*`` routes (list/get/update/delete/playback/spectrogram) were
unmounted in favour of the project-scoped ``/web-api/v1`` BFF. The get /
playback / spectrogram GETs and the update / delete mutations are served by
``web_v1/projects/_media.py`` + ``_recordings.py`` thin delegates; the list
route has an INDEPENDENT reimplementation (``list_public_recordings`` in
``web_v1/projects/_core.py``) with a DIFFERENT ``PublicRecordingListResponse``
shape (``items`` / ``total`` / ``page`` / ``limit`` — no ``page_size`` /
``pages``) and Guest-aware anti-enumeration semantics.

The BFF sits behind the session + CSRF middleware, so every authenticated
request routes through a real ``bff_session_headers`` session (``csrf_headers``
for the owner, ``csrf_headers_other`` for the authenticated non-member 403
path). A signed-out list request is treated as a Guest by the ``list_public_
recordings`` handler and collapses to 404 on a Restricted project
(anti-enumeration, FR-018), NOT 401. The get / update / delete / spectrogram
BFF adapters require a real session, so their no-auth path stays 401 (auth
fires before the permission gate).

The audio / stream media routes (``TestRecordingAudioEndpoints``) KEEP their
``/api/v1`` Bearer semantics — they are not migrated in this PR.

W2-4 PR-A (2026-07-04): the recording download route was migrated to the
``/web-api/v1`` BFF media-token surface (``_media.py:download_recording``), so
``test_download_recording_*`` now exercise the BFF path (session-authed via
``csrf_headers``); the no-auth case collapses to a plain 401.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User


@pytest.fixture
async def test_site_for_recordings(
    db_session: AsyncSession,
    test_project: Project,
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
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset_for_recordings(
    db_session: AsyncSession,
    test_project: Project,
    test_site_for_recordings: Site,
    test_user: User,
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
        datetime=datetime.now(UTC),
        datetime_parse_status="success",
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


# ---------------------------------------------------------------------------
# Public-project fixture chain (WS7 Phase 3 — Guest projection contract).
#
# The Guest-aware BFF endpoint ``GET /web-api/v1/projects/{id}/recordings``
# only returns 200 to a signed-out caller when the project is PUBLIC + ACTIVE
# (FR-016 / FR-018); any other visibility/status collapses to 404 for
# anti-enumeration. We therefore need a dedicated PUBLIC + ACTIVE project with
# a recording attached to a dataset/site so the guest projection can be
# asserted. This mirrors the ``t310_public_project`` chain in
# ``test_guest_authenticated_vote.py``.
# ---------------------------------------------------------------------------


@pytest.fixture
async def public_project(db_session: AsyncSession, test_user: User) -> Project:
    """Create a PUBLIC + ACTIVE project (Guest-listable)."""
    project = Project(
        name="Public Recordings Project",
        description="WS7 Phase 3 guest projection contract",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=test_user.id,
        status=ProjectStatus.ACTIVE,
        # Public projects do not use restricted_config toggles.
        restricted_config={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
def public_project_id(public_project: Project) -> str:
    """Get public project ID as a string."""
    return str(public_project.id)


@pytest.fixture
async def public_site(db_session: AsyncSession, public_project: Project) -> Site:
    """Create a site under the public project."""
    site = Site(
        project_id=public_project.id,
        name="Public Site",
        h3_index_member="89283082803ffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def public_dataset(
    db_session: AsyncSession,
    public_project: Project,
    public_site: Site,
    test_user: User,
) -> Dataset:
    """Create a PUBLIC + COMPLETED dataset under the public project."""
    dataset = Dataset(
        project_id=public_project.id,
        site_id=public_site.id,
        created_by_id=test_user.id,
        name="Public Dataset",
        audio_dir="public/audio",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def public_recording(
    db_session: AsyncSession,
    public_dataset: Dataset,
) -> Recording:
    """Create a recording (with audio metadata) under the public project."""
    recording = Recording(
        dataset_id=public_dataset.id,
        filename="public_recording.wav",
        path="public_recording.wav",
        hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        duration=12.0,
        samplerate=48000,
        channels=2,
        bit_depth=16,
        datetime=datetime.now(UTC),
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
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings - List recordings.

        The BFF list reimplementation returns ``PublicRecordingListResponse``
        (``items`` / ``total`` / ``page`` / ``limit``); it does NOT carry the
        legacy ``page_size`` / ``pages`` fields of ``RecordingListResponse``.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings",
            headers=csrf_headers,
        )

        assert response.status_code == 200, response.text
        data = response.json()

        # Verify response structure matches PublicRecordingListResponse
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["items"], list)

    async def test_list_recordings_member_includes_metadata(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """WS7 Phase 3 (A.1): member projection includes technical metadata.

        The Guest-aware BFF endpoint
        ``GET /web-api/v1/projects/{id}/recordings`` POPULATES the
        member-only fields (``samplerate`` / ``channels`` / ``datetime`` /
        ``datetime_parse_status``) for member-level callers. ``test_user`` is
        the project owner (member-level) on the RESTRICTED ``test_project``,
        so all four fields MUST be present and non-null.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings",
            headers=auth_headers,
        )

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["items"], "Member listing should return the seeded recording"
        item = data["items"][0]

        # Member-only technical metadata is populated for the owner.
        assert item["samplerate"] is not None
        assert item["samplerate"] == test_recording.samplerate
        assert item["channels"] is not None
        assert item["channels"] == test_recording.channels
        assert item["datetime"] is not None
        assert item["datetime_parse_status"] is not None

    async def test_list_recordings_guest_excludes_metadata(
        self,
        client: AsyncClient,
        public_project_id: str,
        public_recording: Recording,
    ) -> None:
        """WS7 Phase 3 (A.2): guest projection excludes technical metadata.

        A signed-out caller listing a PUBLIC + ACTIVE project's recordings
        gets 200 with the Guest-minimal projection: the member-only fields
        (``samplerate`` / ``channels`` / ``datetime`` /
        ``datetime_parse_status``) are withheld (``None``), while the
        Guest-visible identity/label fields remain present.
        """
        response = await client.get(
            f"/web-api/v1/projects/{public_project_id}/recordings",
        )

        assert response.status_code == 200, response.text
        data = response.json()

        assert data["items"], "Guest listing of a Public project should return rows"
        item = data["items"][0]

        # Member-only technical metadata is withheld from the guest.
        assert item["samplerate"] is None
        assert item["channels"] is None
        assert item["datetime"] is None
        assert item["datetime_parse_status"] is None

        # Guest-visible identity / label fields remain present.
        for key in ("id", "project_id", "name", "duration_seconds", "site_h3_index"):
            assert key in item, f"Guest projection is missing key {key!r}"

    async def test_list_recordings_with_filters(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset_for_recordings: Dataset,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings with filters.

        The BFF list uses ``limit`` (not ``page_size``) for the page size, so
        the pagination assertion is adapted to the public shape.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings",
            headers=csrf_headers,
            params={
                "page": 1,
                "limit": 20,
                "dataset_id": str(test_dataset_for_recordings.id),
                "sort_by": "datetime",
                "sort_order": "desc",
            },
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["page"] == 1
        assert data["limit"] == 20

    async def test_list_recordings_guest_restricted_not_found(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings as a signed-out Guest.

        The BFF ``list_public_recordings`` handler treats a signed-out request
        as a Guest (``OptionalCurrentUser``). On a RESTRICTED project (the
        ``test_project`` default) the Guest is collapsed to 404 for
        anti-enumeration (FR-018) rather than the legacy 401 — auth is optional
        on this read surface, so the semantics shift from "requires auth" to
        "invisible to outsiders".
        """
        response = await client.get(f"/web-api/v1/projects/{test_project_id}/recordings")

        assert response.status_code == 404

    async def test_list_recordings_no_access(
        self,
        client: AsyncClient,
        csrf_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings without project access."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings",
            headers=csrf_headers_other,
        )

        assert response.status_code == 403

    async def test_get_recording_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id} - Get recording."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}",
            headers=csrf_headers,
        )

        assert response.status_code == 200, response.text
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
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{fake_id}"
        )

        assert response.status_code == 401

    async def test_update_recording_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id} - Update recording."""
        update_data = {
            "time_expansion": 10.0,
            "note": "Updated recording note",
        }

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}",
            headers=csrf_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["time_expansion"] == update_data["time_expansion"]
        assert data["note"] == update_data["note"]

    async def test_update_recording_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{fake_id}",
            headers=csrf_headers,
            json=update_data,
        )

        assert response.status_code == 404

    async def test_update_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/recordings/{recording_id} requires authentication."""
        update_data = {"note": "Test note"}

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}",
            json=update_data,
        )

        assert response.status_code == 401

    async def test_delete_recording_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
        test_dataset_for_recordings: Dataset,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/recordings/{recording_id} - Delete recording."""
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
            f"/web-api/v1/projects/{test_project_id}/recordings/{recording_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 204

        # Verify recording is deleted
        get_response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{recording_id}",
            headers=csrf_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_recording_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/recordings/{recording_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/recordings/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_delete_recording_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/recordings/{recording_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/recordings/{fake_id}"
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
            # Phase 17 backlog A-5 Round 2 R1-C1: the full-file guarded
            # stream path uses Transfer-Encoding: chunked and DOES NOT
            # advertise Content-Length / Accept-Ranges so a mid-stream
            # permission revoke cannot leave the client waiting for
            # bytes that will never arrive. Range responses (206) on
            # the same endpoint still carry both headers — see
            # ``test_stream_audio_range_response_has_content_length``.
            assert "Content-Length" not in response.headers
            assert "Accept-Ranges" not in response.headers

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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram - Get spectrogram."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}/spectrogram",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{fake_id}/spectrogram",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_spectrogram_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram requires authentication.

        The BFF spectrogram adapter authenticates via ``CurrentUser`` (session
        cookie / Bearer), NOT the legacy ``FlexibleCurrentUser`` query-token
        path. A signed-out request is therefore rejected at the auth layer with
        401 before the permission gate runs, so the legacy 401/403 dual
        expectation collapses to a plain 401 on the BFF surface.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}/spectrogram"
        )

        assert response.status_code == 401

    async def test_get_spectrogram_with_parameters(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram with custom parameters."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}/spectrogram",
            headers=csrf_headers,
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
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_recording: Recording,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/download.

        W2-4 PR-A migrated the recording download route to the ``/web-api/v1``
        BFF media-token surface; it is authenticated by the session
        (``csrf_headers``) or a download-scoped recording media token.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}/download",
            headers=csrf_headers,
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
        """Test GET /web-api/v1/projects/{project_id}/recordings/{recording_id}/download requires auth.

        The BFF adapter authenticates via ``CurrentUser`` (session cookie /
        Bearer / download-scoped media token), so a signed-out request is
        rejected at the auth layer with 401 before the permission gate runs.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/recordings/{test_recording.id}/download"
        )

        assert response.status_code == 401


def test_v1_recording_download_route_unmounted() -> None:
    """The legacy /api/v1 recording download route must stay unmounted (W2-4 PR-A).

    Only the download surface moved in PR-A; the v1 audio + stream routes are
    still mounted until their own migration PR lands.
    """
    from echoroo.main import create_app

    paths = create_app().openapi()["paths"]
    base = "/api/v1/projects/{project_id}/recordings/{recording_id}"
    assert f"{base}/download" not in paths
    assert f"{base}/audio" in paths
