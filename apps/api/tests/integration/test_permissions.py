"""Integration tests for role-based access control (RBAC).

Tests verify the complete flow of permission checking across multiple operations.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.user import User


@pytest.mark.asyncio
class TestRoleBasedAccessControlFlow:
    """Test complete RBAC flow with different user roles."""

    async def test_role_based_access_control_full_flow(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """Test complete RBAC flow: owner, admin, member, viewer permissions.

        This integration test verifies:
        1. Owner creates project and has full control
        2. Owner adds admin member who can manage members and settings
        3. Owner adds regular member who can only view
        4. Owner adds viewer who has read-only access
        5. Each role has appropriate permissions enforced
        6. Permission escalation is prevented
        """
        # Setup: Create users
        owner = User(
            email="owner@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name="Owner User",
            is_active=True,
            is_verified=True,
        )
        admin = User(
            email="admin@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name="Admin User",
            is_active=True,
            is_verified=True,
        )
        member = User(
            email="member@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name="Member User",
            is_active=True,
            is_verified=True,
        )
        viewer = User(
            email="viewer@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name="Viewer User",
            is_active=True,
            is_verified=True,
        )
        outsider = User(
            email="outsider@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name="Outsider User",
            is_active=True,
            is_verified=True,
        )

        db_session.add_all([owner, admin, member, viewer, outsider])
        await db_session.commit()
        await db_session.refresh(owner)
        await db_session.refresh(admin)
        await db_session.refresh(member)
        await db_session.refresh(viewer)
        await db_session.refresh(outsider)

        # Create auth tokens
        owner_token = create_access_token({"sub": str(owner.id)})
        admin_token = create_access_token({"sub": str(admin.id)})
        member_token = create_access_token({"sub": str(member.id)})
        viewer_token = create_access_token({"sub": str(viewer.id)})
        outsider_token = create_access_token({"sub": str(outsider.id)})

        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        member_headers = {"Authorization": f"Bearer {member_token}"}
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
        outsider_headers = {"Authorization": f"Bearer {outsider_token}"}

        # Step 1: Owner creates project
        create_response = await client.post(
            "/api/v1/projects",
            headers=owner_headers,
            json={
                "name": "RBAC Test Project",
                "description": "Testing role-based access control",
                "visibility": "private",
            },
        )
        assert create_response.status_code == 201
        project_data = create_response.json()
        project_id = project_data["id"]

        # Step 2: Owner adds admin member
        add_admin_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=owner_headers,
            json={"email": admin.email, "role": "admin"},
        )
        assert add_admin_response.status_code == 201
        assert add_admin_response.json()["role"] == "admin"

        # Step 3: Owner adds regular member
        add_member_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=owner_headers,
            json={"email": member.email, "role": "member"},
        )
        assert add_member_response.status_code == 201
        assert add_member_response.json()["role"] == "member"

        # Step 4: Owner adds viewer
        add_viewer_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=owner_headers,
            json={"email": viewer.email, "role": "viewer"},
        )
        assert add_viewer_response.status_code == 201
        assert add_viewer_response.json()["role"] == "viewer"

        # Verify: All roles can view project
        for headers in [owner_headers, admin_headers, member_headers, viewer_headers]:
            view_response = await client.get(
                f"/api/v1/projects/{project_id}",
                headers=headers,
            )
            assert view_response.status_code == 200

        # Verify: Outsider cannot view project (private)
        outsider_view = await client.get(
            f"/api/v1/projects/{project_id}",
            headers=outsider_headers,
        )
        assert outsider_view.status_code == 403

        # Verify: Admin can update project settings
        admin_update_response = await client.patch(
            f"/api/v1/projects/{project_id}",
            headers=admin_headers,
            json={"description": "Updated by admin"},
        )
        assert admin_update_response.status_code == 200
        assert admin_update_response.json()["description"] == "Updated by admin"

        # Verify: Member cannot update project settings
        member_update_response = await client.patch(
            f"/api/v1/projects/{project_id}",
            headers=member_headers,
            json={"description": "Attempted by member"},
        )
        assert member_update_response.status_code == 403

        # Verify: Viewer cannot update project settings
        viewer_update_response = await client.patch(
            f"/api/v1/projects/{project_id}",
            headers=viewer_headers,
            json={"description": "Attempted by viewer"},
        )
        assert viewer_update_response.status_code == 403

        # Verify: Admin can add new members
        admin_add_member_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=admin_headers,
            json={"email": outsider.email, "role": "viewer"},
        )
        assert admin_add_member_response.status_code == 201

        # Verify: Member cannot add new members
        temp_user = User(
            email="temp@example.com",
            hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
            display_name="Temp User",
            is_active=True,
            is_verified=True,
        )
        db_session.add(temp_user)
        await db_session.commit()

        member_add_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=member_headers,
            json={"email": temp_user.email, "role": "viewer"},
        )
        assert member_add_response.status_code == 403

        # Verify: Viewer cannot add new members
        viewer_add_response = await client.post(
            f"/api/v1/projects/{project_id}/members",
            headers=viewer_headers,
            json={"email": temp_user.email, "role": "viewer"},
        )
        assert viewer_add_response.status_code == 403

        # Verify: Admin can update member roles
        admin_role_update = await client.patch(
            f"/api/v1/projects/{project_id}/members/{member.id}",
            headers=admin_headers,
            json={"role": "viewer"},
        )
        assert admin_role_update.status_code == 200
        assert admin_role_update.json()["role"] == "viewer"

        # Verify: Member cannot update roles
        member_role_update = await client.patch(
            f"/api/v1/projects/{project_id}/members/{viewer.id}",
            headers=member_headers,
            json={"role": "admin"},
        )
        assert member_role_update.status_code == 403

        # Verify: Admin can remove members
        admin_remove_response = await client.delete(
            f"/api/v1/projects/{project_id}/members/{outsider.id}",
            headers=admin_headers,
        )
        assert admin_remove_response.status_code == 204

        # Verify: Member cannot remove members
        member_remove_response = await client.delete(
            f"/api/v1/projects/{project_id}/members/{viewer.id}",
            headers=member_headers,
        )
        assert member_remove_response.status_code == 403

        # Verify: Admin cannot delete project (owner-only)
        admin_delete_response = await client.delete(
            f"/api/v1/projects/{project_id}",
            headers=admin_headers,
        )
        assert admin_delete_response.status_code == 403

        # Verify: Owner can delete project
        owner_delete_response = await client.delete(
            f"/api/v1/projects/{project_id}",
            headers=owner_headers,
        )
        assert owner_delete_response.status_code == 204

        # Verify: Project is deleted
        verify_delete = await client.get(
            f"/api/v1/projects/{project_id}",
            headers=owner_headers,
        )
        assert verify_delete.status_code == 404
