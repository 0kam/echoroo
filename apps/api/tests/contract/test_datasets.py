"""Contract tests for datasets API endpoints.

Tests verify that endpoints conform to the data management specification.

W2-3 PR-12 (2026-07-02): the 12 browser-superseded ``/api/v1/projects/{id}/
datasets*`` routes were unmounted in favour of the project-scoped
``/web-api/v1/projects/{project_id}/datasets*`` BFF (export stays on v1). The
BFF sits behind the session + CSRF middleware, so every authenticated request
— GET included — routes through a real ``bff_session_headers`` session
(``csrf_headers`` for the owner, ``csrf_headers_other`` for the authenticated
non-member 403 path, an inline member session for the not-admin 403 path). A
plain ``create_access_token`` Bearer is treated as anonymous, so the no-auth
cases stay at 401 (auth fires before the permission gate).
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.recording import Recording
from echoroo.models.site import Site
from tests.contract.conftest import bff_session_headers

if TYPE_CHECKING:
    from echoroo.models.project import Project, ProjectMember
    from echoroo.models.user import User


@pytest.fixture
async def test_site(
    db_session: AsyncSession,
    test_project: "Project",  # noqa: F821
) -> Site:
    """Create a test site for dataset tests.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Test Site for Datasets",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.mark.asyncio
class TestDatasetEndpoints:
    """Test dataset CRUD endpoints."""

    async def test_list_datasets_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets - List datasets."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches DatasetListResponse
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)

    async def test_list_datasets_with_filters(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets with filters."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            params={
                "page": 1,
                "page_size": 10,
                "site_id": str(test_site.id),
                "visibility": "private",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_list_datasets_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets requires authentication."""
        response = await client.get(f"/web-api/v1/projects/{test_project_id}/datasets")

        assert response.status_code == 401

    async def test_list_datasets_no_access(
        self,
        client: AsyncClient,
        csrf_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets without project access.

        The canonical 403 path is now an authenticated non-member
        (``csrf_headers_other``) — that identity holds a real session but no
        project membership, so the request reaches the permission gate and is
        denied ``VIEW_DATASET_LIST``.
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers_other,
        )

        assert response.status_code == 403

    async def test_create_dataset_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets - Create dataset.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: the legacy
        ``audio_dir`` field has been removed from
        :class:`DatasetCreate` / :class:`DatasetResponse` (see
        ``apps/api/echoroo/schemas/dataset.py``); audio storage is now
        keyed by S3 object path on each :class:`Recording` row, not a
        per-dataset directory string. Drop the assertion (and the
        request body field).
        """
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Test Dataset",
            "description": "A test dataset",
            "visibility": "private",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )

        assert response.status_code == 201, response.text
        data = response.json()

        # Verify response structure matches DatasetDetailResponse
        assert "id" in data
        assert data["name"] == dataset_data["name"]
        assert data["description"] == dataset_data["description"]
        assert data["visibility"] == dataset_data["visibility"]
        assert data["status"] == "pending"
        assert "recording_count" in data
        assert "total_duration" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_dataset_minimal(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets with minimal fields."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Minimal Dataset",
            "audio_dir": "test/audio",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == dataset_data["name"]
        assert data["visibility"] == "private"  # default

    async def test_create_dataset_invalid_site(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets with invalid site ID."""
        dataset_data = {
            "site_id": "00000000-0000-0000-0000-000000000000",
            "name": "Test Dataset",
            "audio_dir": "test/audio",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )

        assert response.status_code == 404

    async def test_create_dataset_duplicate_name(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets with duplicate name."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Duplicate Dataset",
            "audio_dir": "test/audio1",
        }

        # Create first dataset
        response1 = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        assert response1.status_code == 201

        # Try to create dataset with same name
        dataset_data2 = {
            "site_id": str(test_site.id),
            "name": "Duplicate Dataset",
            "audio_dir": "test/audio2",
        }

        response2 = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data2,
        )

        assert response2.status_code == 409

    async def test_create_dataset_validation_error(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets with invalid data."""
        dataset_data = {
            "name": "",  # empty name should fail
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )

        assert response.status_code == 422

    async def test_create_dataset_not_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        member_user: "User",  # noqa: F821
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        test_site: Site,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets requires admin role.

        Dataset writes gate on ``MANAGE_DATASET_ADMIN`` (admin + owner only), so
        a MEMBER-role caller with a real session reaches the gate and is denied
        with 403. The session is built inline from ``member_user``.
        """
        member_headers = await bff_session_headers(client, db_session, member_user)
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Test Dataset",
            "audio_dir": "test/audio",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=member_headers,
            json=dataset_data,
        )

        assert response.status_code == 403

    async def test_get_dataset_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets/{dataset_id} - Get dataset."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Test Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Get the dataset
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches DatasetDetailResponse
        assert data["id"] == dataset_id
        assert data["name"] == dataset_data["name"]
        assert "recording_count" in data
        assert "total_duration" in data

    async def test_get_dataset_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets/{dataset_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_dataset_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets/{dataset_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}"
        )

        assert response.status_code == 401

    async def test_update_dataset_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/datasets/{dataset_id} - Update dataset."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Original Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Update the dataset
        update_data = {
            "name": "Updated Dataset",
            "description": "Updated description",
        }

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=csrf_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == update_data["name"]
        assert data["description"] == update_data["description"]

    async def test_update_dataset_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/datasets/{dataset_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"name": "Updated Dataset"}

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=csrf_headers,
            json=update_data,
        )

        assert response.status_code == 404

    async def test_update_dataset_not_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        member_user: "User",  # noqa: F821
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
    ) -> None:
        """Test PATCH /web-api/v1/projects/{project_id}/datasets/{dataset_id} requires admin role.

        MEMBER role lacks ``MANAGE_DATASET_ADMIN``; the inline member session
        reaches the gate and is denied with 403 before any 404 lookup.
        """
        member_headers = await bff_session_headers(client, db_session, member_user)
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"name": "Updated Dataset"}

        response = await client.patch(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=member_headers,
            json=update_data,
        )

        assert response.status_code == 403

    async def test_delete_dataset_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/datasets/{dataset_id} - Delete dataset."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Dataset to Delete",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Delete the dataset
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 204

        # Verify dataset is deleted
        get_response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=csrf_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_dataset_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/datasets/{dataset_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_delete_dataset_not_admin(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        member_user: "User",  # noqa: F821
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
    ) -> None:
        """Test DELETE /web-api/v1/projects/{project_id}/datasets/{dataset_id} requires admin role.

        MEMBER role lacks ``MANAGE_DATASET_ADMIN``; the inline member session
        reaches the gate and is denied with 403.
        """
        member_headers = await bff_session_headers(client, db_session, member_user)
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=member_headers,
        )

        assert response.status_code == 403


@pytest.mark.asyncio
class TestDatasetImportEndpoints:
    """Test dataset import-related endpoints."""

    async def test_start_import_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets/{dataset_id}/import - Start import."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Import Test Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Start import
        import_data = {
            "datetime_pattern": r"(\d{8}_\d{6})",
            "datetime_format": "%Y%m%d_%H%M%S",
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}/import",
            headers=csrf_headers,
            json=import_data,
        )

        # Note: Import may fail if directory doesn't exist, but should return valid response
        assert response.status_code in [200, 400, 404]
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "total_files" in data
            assert "processed_files" in data
            assert "progress_percent" in data

    async def test_start_import_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets/{dataset_id}/import with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        import_data: dict[str, object] = {}

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}/import",
            headers=csrf_headers,
            json=import_data,
        )

        assert response.status_code == 404

    async def test_start_import_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/datasets/{dataset_id}/import requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        import_data: dict[str, object] = {}

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}/import",
            json=import_data,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDatasetStatisticsEndpoints:
    """Test dataset statistics endpoint."""

    async def test_get_statistics_success(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets/{dataset_id}/statistics - Get statistics."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Stats Test Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Get statistics
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}/statistics",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches DatasetStatisticsResponse
        assert "recording_count" in data
        assert "total_duration" in data
        assert "date_range" in data
        assert "samplerate_distribution" in data
        assert "format_distribution" in data
        assert "recordings_by_date" in data
        assert "recordings_by_hour" in data
        # Timezone field tells the frontend which tz the hour/date buckets use.
        # Defaults to 'UTC' when the dataset has no datetime_timezone.
        assert data["timezone"] == "UTC"

    async def test_get_statistics_uses_dataset_timezone(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Statistics response reports the dataset's local timezone for buckets."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "TZ Stats Dataset",
            "audio_dir": "test/audio",
            "datetime_timezone": "Asia/Tokyo",
        }

        create_response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}/statistics",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        assert response.json()["timezone"] == "Asia/Tokyo"

    async def test_get_statistics_timezone_bucket_values(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
        db_session: AsyncSession,
    ) -> None:
        """Bucketing actually uses dataset-local time, not UTC.

        Scenario: a recording stored at 2026-01-01T23:30:00Z (UTC) is
        2026-01-02T08:30 JST (UTC+9).  With ``datetime_timezone='Asia/Tokyo'``
        the statistics endpoint must return:
          - ``recordings_by_hour``: hour == 8  (JST), not 23 (UTC)
          - ``recordings_by_date``: date == '2026-01-02' (JST), not '2026-01-01' (UTC)
        """
        # Create a dataset with Asia/Tokyo timezone.
        dataset_resp = await client.post(
            f"/web-api/v1/projects/{test_project_id}/datasets",
            headers=csrf_headers,
            json={
                "site_id": str(test_site.id),
                "name": "TZ Bucket Value Dataset",
                "datetime_timezone": "Asia/Tokyo",
            },
        )
        assert dataset_resp.status_code == 201, dataset_resp.text
        dataset_id = dataset_resp.json()["id"]

        # Insert a recording whose UTC datetime crosses a date boundary when
        # converted to JST: 2026-01-01 23:30 UTC == 2026-01-02 08:30 JST.
        utc_instant = datetime(2026, 1, 1, 23, 30, 0, tzinfo=UTC)
        recording = Recording(
            dataset_id=dataset_id,
            filename="tz_test_recording.wav",
            path="tz_test_recording.wav",
            duration=10.0,
            samplerate=44100,
            channels=1,
            datetime=utc_instant,
            datetime_parse_status="success",
            time_expansion=1.0,
        )
        db_session.add(recording)
        await db_session.commit()

        # Fetch statistics and verify local-time buckets.
        stats_resp = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{dataset_id}/statistics",
            headers=csrf_headers,
        )
        assert stats_resp.status_code == 200, stats_resp.text
        data = stats_resp.json()

        # The timezone field must reflect the dataset's configured timezone.
        assert data["timezone"] == "Asia/Tokyo"

        # recordings_by_hour: must contain hour 8 (JST), not hour 23 (UTC).
        hours = {bucket["hour"]: bucket["count"] for bucket in data["recordings_by_hour"]}
        assert 8 in hours, (
            f"Expected JST hour 8 in recordings_by_hour, got hours: {list(hours.keys())}"
        )
        assert hours[8] == 1
        assert 23 not in hours, (
            f"recordings_by_hour must NOT contain UTC hour 23; got hours: {list(hours.keys())}"
        )

        # recordings_by_date: must contain '2026-01-02' (JST), not '2026-01-01' (UTC).
        dates = {bucket["date"]: bucket["count"] for bucket in data["recordings_by_date"]}
        assert "2026-01-02" in dates, (
            f"Expected JST date '2026-01-02' in recordings_by_date, got dates: {list(dates.keys())}"
        )
        assert dates["2026-01-02"] == 1
        assert "2026-01-01" not in dates, (
            f"recordings_by_date must NOT contain UTC date '2026-01-01'; got: {list(dates.keys())}"
        )

    async def test_get_statistics_not_found(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets/{dataset_id}/statistics with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}/statistics",
            headers=csrf_headers,
        )

        assert response.status_code == 404

    async def test_get_statistics_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/datasets/{dataset_id}/statistics requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/datasets/{fake_id}/statistics"
        )

        assert response.status_code == 401
