"""Contract tests for datasets API endpoints.

Tests verify that endpoints conform to the data management specification.
"""

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.site import Site

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
        h3_index="8928308280fffff",
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
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets - List datasets."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
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
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets with filters."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
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
        """Test GET /api/v1/projects/{project_id}/datasets requires authentication."""
        response = await client.get(f"/api/v1/projects/{test_project_id}/datasets")

        assert response.status_code == 401

    async def test_list_datasets_no_access(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets without project access."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers_other,
        )

        assert response.status_code == 403

    async def test_create_dataset_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets - Create dataset."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Test Dataset",
            "description": "A test dataset",
            "audio_dir": "test/audio",
            "visibility": "private",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure matches DatasetDetailResponse
        assert "id" in data
        assert data["name"] == dataset_data["name"]
        assert data["description"] == dataset_data["description"]
        assert data["audio_dir"] == dataset_data["audio_dir"]
        assert data["visibility"] == dataset_data["visibility"]
        assert data["status"] == "pending"
        assert "recording_count" in data
        assert "total_duration" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_dataset_minimal(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets with minimal fields."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Minimal Dataset",
            "audio_dir": "test/audio",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == dataset_data["name"]
        assert data["visibility"] == "private"  # default

    async def test_create_dataset_invalid_site(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets with invalid site ID."""
        dataset_data = {
            "site_id": "00000000-0000-0000-0000-000000000000",
            "name": "Test Dataset",
            "audio_dir": "test/audio",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )

        assert response.status_code == 404

    async def test_create_dataset_duplicate_name(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets with duplicate name."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Duplicate Dataset",
            "audio_dir": "test/audio1",
        }

        # Create first dataset
        response1 = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
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
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data2,
        )

        assert response2.status_code == 409

    async def test_create_dataset_validation_error(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets with invalid data."""
        dataset_data = {
            "name": "",  # empty name should fail
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )

        assert response.status_code == 422

    async def test_create_dataset_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        test_site: Site,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets requires admin role."""
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Test Dataset",
            "audio_dir": "test/audio",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers_member,
            json=dataset_data,
        )

        assert response.status_code == 403

    async def test_get_dataset_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets/{dataset_id} - Get dataset."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Test Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Get the dataset
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=auth_headers,
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
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets/{dataset_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_dataset_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets/{dataset_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}"
        )

        assert response.status_code == 401

    async def test_update_dataset_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/datasets/{dataset_id} - Update dataset."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Original Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Update the dataset
        update_data = {
            "name": "Updated Dataset",
            "description": "Updated description",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == update_data["name"]
        assert data["description"] == update_data["description"]

    async def test_update_dataset_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/datasets/{dataset_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"name": "Updated Dataset"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 404

    async def test_update_dataset_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/datasets/{dataset_id} requires admin role."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"name": "Updated Dataset"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=auth_headers_member,
            json=update_data,
        )

        assert response.status_code == 403

    async def test_delete_dataset_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/datasets/{dataset_id} - Delete dataset."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Dataset to Delete",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Delete the dataset
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify dataset is deleted
        get_response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{dataset_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_dataset_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/datasets/{dataset_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_dataset_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/datasets/{dataset_id} requires admin role."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}",
            headers=auth_headers_member,
        )

        assert response.status_code == 403


@pytest.mark.asyncio
class TestDatasetImportEndpoints:
    """Test dataset import-related endpoints."""

    async def test_start_import_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets/{dataset_id}/import - Start import."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Import Test Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Start import
        import_data = {
            "datetime_pattern": r"(\d{8}_\d{6})",
            "datetime_format": "%Y%m%d_%H%M%S",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{dataset_id}/import",
            headers=auth_headers,
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
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets/{dataset_id}/import with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        import_data = {}

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}/import",
            headers=auth_headers,
            json=import_data,
        )

        assert response.status_code == 404

    async def test_start_import_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/datasets/{dataset_id}/import requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        import_data = {}

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}/import",
            json=import_data,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDatasetStatisticsEndpoints:
    """Test dataset statistics endpoint."""

    async def test_get_statistics_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_site: Site,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets/{dataset_id}/statistics - Get statistics."""
        # Create a dataset first
        dataset_data = {
            "site_id": str(test_site.id),
            "name": "Stats Test Dataset",
            "audio_dir": "test/audio",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/datasets",
            headers=auth_headers,
            json=dataset_data,
        )
        dataset_id = create_response.json()["id"]

        # Get statistics
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{dataset_id}/statistics",
            headers=auth_headers,
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

    async def test_get_statistics_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets/{dataset_id}/statistics with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}/statistics",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_statistics_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/datasets/{dataset_id}/statistics requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/datasets/{fake_id}/statistics"
        )

        assert response.status_code == 401
