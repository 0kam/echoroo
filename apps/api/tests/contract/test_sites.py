"""Contract tests for sites API endpoints.

Tests verify that endpoints conform to the data management specification.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.site import Site


@pytest.mark.asyncio
class TestSiteEndpoints:
    """Test site CRUD endpoints."""

    async def test_list_sites_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites - List sites."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches SiteListResponse
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)

    async def test_list_sites_with_pagination(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites with pagination."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            params={"page": 1, "page_size": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_list_sites_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites requires authentication."""
        response = await client.get(f"/api/v1/projects/{test_project_id}/sites")

        assert response.status_code == 401

    async def test_list_sites_no_access(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites without project access."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers_other,
        )

        assert response.status_code == 403

    async def test_create_site_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/sites - Create site."""
        site_data = {
            "name": "Test Site",
            "h3_index": "8928308280fffff",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure matches SiteResponse
        assert "id" in data
        assert data["name"] == site_data["name"]
        assert data["h3_index"] == site_data["h3_index"]
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_site_invalid_h3_index(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/sites with invalid H3 index."""
        site_data = {
            "name": "Test Site",
            "h3_index": "invalid_h3_index",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data,
        )

        assert response.status_code == 400

    async def test_create_site_duplicate_name(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/sites with duplicate name."""
        # Create first site
        site_data = {
            "name": "Duplicate Site",
            "h3_index": "8928308280fffff",
        }

        response1 = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data,
        )
        assert response1.status_code == 201

        # Try to create site with same name
        site_data2 = {
            "name": "Duplicate Site",
            "h3_index": "8928308280bffff",  # Different valid H3 index (neighbor cell)
        }

        response2 = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data2,
        )

        assert response2.status_code == 409

    async def test_create_site_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/sites requires authentication."""
        site_data = {
            "name": "Test Site",
            "h3_index": "8928308280fffff",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            json=site_data,
        )

        assert response.status_code == 401

    async def test_create_site_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/sites requires admin role."""
        site_data = {
            "name": "Test Site",
            "h3_index": "8928308280fffff",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers_member,
            json=site_data,
        )

        assert response.status_code == 403

    async def test_get_site_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites/{site_id} - Get site."""
        # Create a site first
        site_data = {
            "name": "Test Site",
            "h3_index": "8928308280fffff",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data,
        )
        site_id = create_response.json()["id"]

        # Get the site
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites/{site_id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches SiteDetailResponse
        assert data["id"] == site_id
        assert data["name"] == site_data["name"]
        assert data["h3_index"] == site_data["h3_index"]
        assert "dataset_count" in data
        assert "recording_count" in data

    async def test_get_site_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites/{site_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_site_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/sites/{site_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}"
        )

        assert response.status_code == 401

    async def test_update_site_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/sites/{site_id} - Update site."""
        # Create a site first
        site_data = {
            "name": "Original Site",
            "h3_index": "8928308280fffff",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data,
        )
        site_id = create_response.json()["id"]

        # Update the site
        update_data = {
            "name": "Updated Site",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/sites/{site_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == update_data["name"]
        assert data["h3_index"] == site_data["h3_index"]  # Unchanged

    async def test_update_site_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/sites/{site_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"name": "Updated Site"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 404

    async def test_update_site_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        db_session: AsyncSession,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/sites/{site_id} requires admin role."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_data = {"name": "Updated Site"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}",
            headers=auth_headers_member,
            json=update_data,
        )

        assert response.status_code == 403

    async def test_delete_site_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/sites/{site_id} - Delete site."""
        # Create a site first
        site_data = {
            "name": "Site to Delete",
            "h3_index": "8928308280fffff",
        }

        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/sites",
            headers=auth_headers,
            json=site_data,
        )
        site_id = create_response.json()["id"]

        # Delete the site
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sites/{site_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify site is deleted
        get_response = await client.get(
            f"/api/v1/projects/{test_project_id}/sites/{site_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_site_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/sites/{site_id} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_site_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/sites/{site_id} requires admin role."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}",
            headers=auth_headers_member,
        )

        assert response.status_code == 403

    async def test_delete_site_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/sites/{site_id} requires authentication."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/sites/{fake_id}"
        )

        assert response.status_code == 401
