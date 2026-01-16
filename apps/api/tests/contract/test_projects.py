"""Contract tests for project management endpoints.

Tests verify that endpoints conform to the OpenAPI specification in
specs/001-administration/contracts/openapi.yaml.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestProjectEndpoints:
    """Test project CRUD endpoints."""

    async def test_list_projects(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test GET /api/v1/projects - List projects with pagination."""
        response = await client.get(
            "/api/v1/projects",
            headers=auth_headers,
            params={"page": 1, "limit": 20},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure matches ProjectListResponse
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "limit" in data
        assert isinstance(data["items"], list)
        assert data["page"] == 1
        assert data["limit"] == 20

    async def test_list_projects_unauthorized(self, client: AsyncClient) -> None:
        """Test GET /api/v1/projects requires authentication."""
        response = await client.get("/api/v1/projects")

        assert response.status_code == 401

    async def test_create_project(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test POST /api/v1/projects - Create project."""
        project_data = {
            "name": "Test Project",
            "description": "A test research project",
            "target_taxa": "Passeriformes, Strigiformes",
            "visibility": "private",
        }

        response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json=project_data,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure matches ProjectResponse
        assert "id" in data
        assert data["name"] == project_data["name"]
        assert data["description"] == project_data["description"]
        assert data["target_taxa"] == project_data["target_taxa"]
        assert data["visibility"] == project_data["visibility"]
        assert "owner" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_project_minimal(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test POST /api/v1/projects with minimal required fields."""
        project_data = {
            "name": "Minimal Project",
        }

        response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json=project_data,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == project_data["name"]
        assert data["description"] is None
        assert data["target_taxa"] is None
        assert data["visibility"] == "private"  # default

    async def test_create_project_validation_error(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test POST /api/v1/projects with invalid data."""
        project_data = {
            "name": "",  # empty name should fail
        }

        response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json=project_data,
        )

        assert response.status_code == 422  # Validation error

    async def test_create_project_unauthorized(self, client: AsyncClient) -> None:
        """Test POST /api/v1/projects requires authentication."""
        project_data = {"name": "Test Project"}

        response = await client.post("/api/v1/projects", json=project_data)

        assert response.status_code == 401

    async def test_get_project(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{projectId} - Get project details."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert data["id"] == test_project_id
        assert "name" in data
        assert "description" in data
        assert "target_taxa" in data
        assert "visibility" in data
        assert "owner" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_get_project_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test GET /api/v1/projects/{projectId} with non-existent ID."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_project_no_access(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{projectId} without access."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_other,
        )

        assert response.status_code == 403

    async def test_update_project(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{projectId} - Update project."""
        update_data = {
            "name": "Updated Project Name",
            "visibility": "public",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == update_data["name"]
        assert data["visibility"] == update_data["visibility"]

    async def test_update_project_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{projectId} requires admin role."""
        update_data = {"name": "Should Fail"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_member,
            json=update_data,
        )

        assert response.status_code == 403

    async def test_delete_project(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test DELETE /api/v1/projects/{projectId} - Delete project."""
        # Create a project to delete
        create_response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json={"name": "Project to Delete"},
        )
        project_id = create_response.json()["id"]

        # Delete the project
        response = await client.delete(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify project is deleted
        get_response = await client.get(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_project_not_owner(
        self,
        client: AsyncClient,
        auth_headers_admin: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{projectId} requires owner."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_admin,
        )

        assert response.status_code == 403


@pytest.mark.asyncio
class TestProjectMemberEndpoints:
    """Test project member management endpoints."""

    async def test_list_members(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{projectId}/members - List members."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response is an array
        assert isinstance(data, list)

    async def test_add_member(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        member_user: "User",  # noqa: F821
    ) -> None:
        """Test POST /api/v1/projects/{projectId}/members - Add member."""
        member_data = {
            "email": member_user.email,
            "role": "member",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers,
            json=member_data,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure matches ProjectMemberResponse
        assert "id" in data
        assert "user" in data
        assert data["user"]["email"] == member_user.email
        assert data["role"] == "member"
        assert "joined_at" in data

    async def test_add_member_already_exists(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        member_user: "User",  # noqa: F821
    ) -> None:
        """Test POST /api/v1/projects/{projectId}/members with existing member."""
        member_data = {
            "email": member_user.email,
            "role": "member",
        }

        # Try to add same member again (already added via fixture)
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers,
            json=member_data,
        )

        assert response.status_code == 400

    async def test_add_member_not_admin(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        admin_user: "User",  # noqa: F821
    ) -> None:
        """Test POST /api/v1/projects/{projectId}/members requires admin."""
        member_data = {
            "email": admin_user.email,
            "role": "member",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers_member,
            json=member_data,
        )

        assert response.status_code == 403

    async def test_update_member_role(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        test_member_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{projectId}/members/{userId} - Update role."""
        update_data = {"role": "admin"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["role"] == "admin"

    async def test_update_member_role_cannot_change_owner(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_owner_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{projectId}/members/{userId} cannot change owner role."""
        update_data = {"role": "viewer"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/members/{test_owner_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 400

    async def test_remove_member(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_member: "ProjectMember",  # noqa: F821
        test_member_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{projectId}/members/{userId} - Remove member."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify member is removed
        members_response = await client.get(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers,
        )
        members = members_response.json()
        member_ids = [m["user"]["id"] for m in members]
        assert test_member_id not in member_ids

    async def test_remove_member_cannot_remove_owner(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_owner_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{projectId}/members/{userId} cannot remove owner."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/members/{test_owner_id}",
            headers=auth_headers,
        )

        assert response.status_code == 400
