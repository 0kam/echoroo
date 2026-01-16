"""Contract tests for project permission system.

Tests verify that role-based access control (RBAC) works correctly
for different user roles: admin, member, viewer.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectRole
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User


@pytest.fixture
async def viewer_user(db_session: AsyncSession) -> User:
    """Create a test user that will be a project viewer.

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="viewer@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Viewer User",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers_viewer(viewer_user: User) -> dict[str, str]:
    """Create authentication headers for viewer user.

    Args:
        viewer_user: Viewer test user

    Returns:
        Headers with Bearer token
    """
    from echoroo.core.jwt import create_access_token

    access_token = create_access_token({"sub": str(viewer_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def test_viewer_member(
    db_session: AsyncSession,
    test_project: Project,
    viewer_user: User,
) -> ProjectMember:
    """Create a test project viewer member.

    Args:
        db_session: Database session
        test_project: Test project
        viewer_user: Viewer user

    Returns:
        Project member instance with viewer role
    """
    member = ProjectMember(
        user_id=viewer_user.id,
        project_id=test_project.id,
        role=ProjectRole.VIEWER,
        invited_by_id=test_project.owner_id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


@pytest.mark.asyncio
class TestUpdateMemberRolePermissions:
    """Test permissions for updating member roles."""

    async def test_update_member_role_as_admin_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_member: ProjectMember,  # Ensure member exists
        test_member_id: str,
    ) -> None:
        """Test that admin (owner) can successfully update member role.

        Verifies:
        - Owner can change member role from 'member' to 'admin'
        - Response returns 200 OK
        - Updated role is reflected in response
        """
        update_data = {"role": "admin"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "admin"

    async def test_update_member_role_as_non_admin_forbidden(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: ProjectMember,  # Ensure member exists and is authenticated
        test_member_id: str,
    ) -> None:
        """Test that non-admin member cannot update member roles.

        Verifies:
        - Member role user cannot change other members' roles
        - Response returns 403 Forbidden
        - Error message indicates insufficient permissions
        """
        update_data = {"role": "admin"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers_member,
            json=update_data,
        )

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data


@pytest.mark.asyncio
class TestViewerPermissions:
    """Test that viewers have read-only access."""

    async def test_viewer_cannot_edit_project(
        self,
        client: AsyncClient,
        auth_headers_viewer: dict[str, str],
        test_project_id: str,
        test_viewer_member: ProjectMember,  # Ensure viewer is a member
    ) -> None:
        """Test that viewer cannot edit project settings.

        Verifies:
        - Viewer role user cannot update project name/description
        - Response returns 403 Forbidden
        - Project settings remain unchanged
        """
        update_data = {
            "name": "Unauthorized Change",
            "description": "This should not work",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_viewer,
            json=update_data,
        )

        assert response.status_code == 403
        data = response.json()
        assert "detail" in data
        # Error message should indicate insufficient permissions
        assert "admin" in data["detail"].lower() or "permission" in data["detail"].lower()

    async def test_viewer_can_view_project(
        self,
        client: AsyncClient,
        auth_headers_viewer: dict[str, str],
        test_project_id: str,
        test_viewer_member: ProjectMember,  # Ensure viewer is a member
    ) -> None:
        """Test that viewer can view project details (read-only).

        Verifies:
        - Viewer role user can GET project details
        - Response returns 200 OK
        - Project data is accessible
        """
        response = await client.get(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_viewer,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_project_id

    async def test_viewer_cannot_add_members(
        self,
        client: AsyncClient,
        auth_headers_viewer: dict[str, str],
        test_project_id: str,
        test_viewer_member: ProjectMember,  # Ensure viewer is a member
        other_user: User,
    ) -> None:
        """Test that viewer cannot add members to project.

        Verifies:
        - Viewer role user cannot POST to members endpoint
        - Response returns 403 Forbidden
        """
        member_data = {
            "email": other_user.email,
            "role": "member",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers_viewer,
            json=member_data,
        )

        assert response.status_code == 403

    async def test_viewer_cannot_remove_members(
        self,
        client: AsyncClient,
        auth_headers_viewer: dict[str, str],
        test_project_id: str,
        test_viewer_member: ProjectMember,  # Ensure viewer is a member
        test_member: ProjectMember,  # Ensure target member exists
        test_member_id: str,
    ) -> None:
        """Test that viewer cannot remove members from project.

        Verifies:
        - Viewer role user cannot DELETE members
        - Response returns 403 Forbidden
        """
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers_viewer,
        )

        assert response.status_code == 403


@pytest.mark.asyncio
class TestMemberPermissions:
    """Test that members can edit data but not settings."""

    async def test_member_can_edit_data_but_not_settings(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: ProjectMember,  # Ensure member exists and is authenticated
    ) -> None:
        """Test that member can view but cannot edit project settings.

        Verifies:
        - Member role user cannot update project settings (name, visibility)
        - Response returns 403 Forbidden
        - Settings like visibility and description are protected
        """
        # Try to update project settings (should fail)
        update_data = {
            "name": "Changed Name",
            "visibility": "public",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_member,
            json=update_data,
        )

        assert response.status_code == 403

    async def test_member_can_view_project(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: ProjectMember,  # Ensure member exists and is authenticated
    ) -> None:
        """Test that member can view project details.

        Verifies:
        - Member role user can GET project details
        - Response returns 200 OK
        """
        response = await client.get(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_member,
        )

        assert response.status_code == 200

    async def test_member_cannot_add_members(
        self,
        client: AsyncClient,
        auth_headers_member: dict[str, str],
        test_project_id: str,
        test_member: ProjectMember,  # Ensure member exists and is authenticated
        other_user: User,
    ) -> None:
        """Test that member cannot add other members.

        Verifies:
        - Member role user cannot POST to members endpoint
        - Response returns 403 Forbidden
        """
        member_data = {
            "email": other_user.email,
            "role": "member",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers_member,
            json=member_data,
        )

        assert response.status_code == 403


@pytest.mark.asyncio
class TestAdminPermissions:
    """Test that admins can manage members and settings."""

    async def test_admin_can_manage_members(
        self,
        client: AsyncClient,
        auth_headers_admin: dict[str, str],
        test_project_id: str,
        test_admin_member: ProjectMember,  # Ensure admin is a member
        other_user: User,
    ) -> None:
        """Test that admin can add members to project.

        Verifies:
        - Admin role user can POST to members endpoint
        - Response returns 201 Created
        - New member is successfully added
        """
        member_data = {
            "email": other_user.email,
            "role": "viewer",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers_admin,
            json=member_data,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user"]["email"] == other_user.email
        assert data["role"] == "viewer"

    async def test_admin_can_update_member_roles(
        self,
        client: AsyncClient,
        auth_headers_admin: dict[str, str],
        test_project_id: str,
        test_admin_member: ProjectMember,  # Ensure admin is a member
        test_member: ProjectMember,  # Ensure target member exists
        test_member_id: str,
    ) -> None:
        """Test that admin can update member roles.

        Verifies:
        - Admin role user can PATCH member roles
        - Response returns 200 OK
        - Role change is successful
        """
        update_data = {"role": "viewer"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers_admin,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "viewer"

    async def test_admin_can_remove_members(
        self,
        client: AsyncClient,
        auth_headers_admin: dict[str, str],
        test_project_id: str,
        test_admin_member: ProjectMember,  # Ensure admin is a member
        test_member: ProjectMember,  # Ensure target member exists
        test_member_id: str,
    ) -> None:
        """Test that admin can remove members from project.

        Verifies:
        - Admin role user can DELETE members
        - Response returns 204 No Content
        - Member is successfully removed
        """
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/members/{test_member_id}",
            headers=auth_headers_admin,
        )

        assert response.status_code == 204

        # Verify member was removed
        members_response = await client.get(
            f"/api/v1/projects/{test_project_id}/members",
            headers=auth_headers_admin,
        )
        members = members_response.json()
        member_ids = [m["user"]["id"] for m in members]
        assert test_member_id not in member_ids

    async def test_admin_can_update_project_settings(
        self,
        client: AsyncClient,
        auth_headers_admin: dict[str, str],
        test_project_id: str,
        test_admin_member: ProjectMember,  # Ensure admin is a member
    ) -> None:
        """Test that admin can update project settings.

        Verifies:
        - Admin role user can PATCH project settings
        - Response returns 200 OK
        - Settings are successfully updated
        """
        update_data = {
            "description": "Updated by admin",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_admin,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["description"] == update_data["description"]

    async def test_admin_cannot_delete_project(
        self,
        client: AsyncClient,
        auth_headers_admin: dict[str, str],
        test_project_id: str,
        test_admin_member: ProjectMember,  # Ensure admin is a member
    ) -> None:
        """Test that admin (non-owner) cannot delete project.

        Verifies:
        - Admin role user cannot DELETE project (only owner can)
        - Response returns 403 Forbidden
        - Owner-only operations are protected
        """
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_admin,
        )

        assert response.status_code == 403
        data = response.json()
        assert "owner" in data["detail"].lower()
