"""Integration tests for project lifecycle workflow.

Tests the complete workflow of project creation, member management, and deletion.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestProjectLifecycle:
    """Test complete project lifecycle from creation to deletion."""

    async def test_project_lifecycle(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test complete project workflow.

        Flow:
        1. Create a project
        2. Update project settings
        3. List projects (verify it appears)
        4. Add members with different roles
        5. Update member roles
        6. List members
        7. Remove a member
        8. Delete project
        9. Verify project is gone
        """
        # 1. Create a project
        create_response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json={
                "name": "Research Project",
                "description": "A comprehensive bird research project",
                "target_taxa": "Passeriformes, Strigiformes, Piciformes",
                "visibility": "private",
            },
        )
        assert create_response.status_code == 201
        project = create_response.json()
        project_id = project["id"]

        assert project["name"] == "Research Project"
        assert project["description"] == "A comprehensive bird research project"
        assert project["visibility"] == "private"
        assert "owner" in project
        assert "created_at" in project

        # 2. Update project settings
        update_response = await client.patch(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers,
            json={
                "name": "Updated Research Project",
                "visibility": "public",
            },
        )
        assert update_response.status_code == 200
        updated_project = update_response.json()
        assert updated_project["name"] == "Updated Research Project"
        assert updated_project["visibility"] == "public"

        # 3. List projects (verify it appears)
        list_response = await client.get(
            "/api/v1/projects",
            headers=auth_headers,
        )
        assert list_response.status_code == 200
        projects_data = list_response.json()
        assert projects_data["total"] >= 1
        project_ids = [p["id"] for p in projects_data["items"]]
        assert project_id in project_ids

        # 4. Add members with different roles
        # Create test users first
        viewer_register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "viewer@example.com",
                "password": "SecurePass123",
                "display_name": "Viewer User",
            },
        )
        assert viewer_register.status_code == 201

        member_register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "projectmember@example.com",
                "password": "SecurePass123",
                "display_name": "Project Member",
            },
        )
        assert member_register.status_code == 201

        admin_register = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "projectadmin@example.com",
                "password": "SecurePass123",
                "display_name": "Project Admin",
            },
        )
        assert admin_register.status_code == 201

        # Add viewer
        add_viewer_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=auth_headers,
            json={"email": "viewer@example.com", "role": "viewer"},
        )
        assert add_viewer_response.status_code == 201
        viewer_member = add_viewer_response.json()
        assert viewer_member["role"] == "viewer"
        viewer_user_id = viewer_member["user"]["id"]

        # Add member
        add_member_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=auth_headers,
            json={"email": "projectmember@example.com", "role": "member"},
        )
        assert add_member_response.status_code == 201
        project_member = add_member_response.json()
        assert project_member["role"] == "member"

        # Add admin
        add_admin_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=auth_headers,
            json={"email": "projectadmin@example.com", "role": "admin"},
        )
        assert add_admin_response.status_code == 201
        admin_member = add_admin_response.json()
        assert admin_member["role"] == "admin"

        # 5. Update member role (promote viewer to member)
        update_role_response = await client.patch(
            f"/api/v1/projects/{project_id}/members/{viewer_user_id}",
            headers=auth_headers,
            json={"role": "member"},
        )
        assert update_role_response.status_code == 200
        updated_member = update_role_response.json()
        assert updated_member["role"] == "member"

        # 6. List members
        members_response = await client.get(
            f"/api/v1/projects/{project_id}/members",
            headers=auth_headers,
        )
        assert members_response.status_code == 200
        members = members_response.json()
        assert len(members) == 3  # viewer, member, admin

        # Verify all roles are present
        roles = [m["role"] for m in members]
        assert "member" in roles
        assert "admin" in roles

        # 7. Remove a member (remove viewer)
        remove_response = await client.delete(
            f"/api/v1/projects/{project_id}/members/{viewer_user_id}",
            headers=auth_headers,
        )
        assert remove_response.status_code == 204

        # Verify member was removed
        members_after_remove = await client.get(
            f"/api/v1/projects/{project_id}/members",
            headers=auth_headers,
        )
        remaining_members = members_after_remove.json()
        assert len(remaining_members) == 2
        remaining_user_ids = [m["user"]["id"] for m in remaining_members]
        assert viewer_user_id not in remaining_user_ids

        # 8. Delete project
        delete_response = await client.delete(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers,
        )
        assert delete_response.status_code == 204

        # 9. Verify project is gone
        get_deleted_response = await client.get(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers,
        )
        assert get_deleted_response.status_code == 404

        # Verify it's not in the list
        final_list_response = await client.get(
            "/api/v1/projects",
            headers=auth_headers,
        )
        final_projects = final_list_response.json()
        final_project_ids = [p["id"] for p in final_projects["items"]]
        assert project_id not in final_project_ids

    async def test_member_access_control(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test that member role restrictions are enforced.

        Verifies:
        - Viewers can view but not edit
        - Members can view and edit data (not implemented yet)
        - Admins can manage members and settings
        - Only owner can delete project
        """
        # Create a project
        create_response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json={"name": "Access Control Test Project"},
        )
        project_id = create_response.json()["id"]

        # Create viewer user
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "viewer-test@example.com",
                "password": "SecurePass123",
            },
        )

        # Add viewer to project
        await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=auth_headers,
            json={"email": "viewer-test@example.com", "role": "viewer"},
        )

        # Login as viewer
        viewer_login = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "viewer-test@example.com",
                "password": "SecurePass123",
            },
        )
        viewer_token = viewer_login.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # Viewer can view project
        view_response = await client.get(
            f"/api/v1/projects/{project_id}",
            headers=viewer_headers,
        )
        assert view_response.status_code == 200

        # Viewer cannot update project
        update_response = await client.patch(
            f"/api/v1/projects/{project_id}",
            headers=viewer_headers,
            json={"name": "Should Fail"},
        )
        assert update_response.status_code == 403

        # Viewer cannot add members
        add_member_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=viewer_headers,
            json={"email": "newmember@example.com", "role": "member"},
        )
        assert add_member_response.status_code == 403

        # Viewer cannot delete project
        delete_response = await client.delete(
            f"/api/v1/projects/{project_id}",
            headers=viewer_headers,
        )
        assert delete_response.status_code == 403

        # Cleanup: Owner deletes project
        await client.delete(
            f"/api/v1/projects/{project_id}",
            headers=auth_headers,
        )
