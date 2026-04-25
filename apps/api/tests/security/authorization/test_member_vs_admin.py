"""Member vs Admin permission boundary tests (T132).

Spec: FR-008 — Member does NOT have MANAGE_MEMBERS or TRAIN_MODEL permission;
      Admin has both; Owner additionally has DELETE_PROJECT.

Test structure:
  * ``TestMemberForbidden``  — Member gets 403 on MANAGE_MEMBERS / TRAIN_MODEL /
                               DELETE_PROJECT endpoints.
  * ``TestAdminAllowed``     — Admin gets 200/201/422 (not 401/403) on
                               MANAGE_MEMBERS / TRAIN_MODEL endpoints.
  * ``TestOwnerAllowed``     — Owner gets 204 (not 401/403) on DELETE_PROJECT.

Fixture note: All projects use ProjectVisibility.RESTRICTED. The Stage-1
permission gate fires before any service logic, so 403 from the gate is the
correct assertion for Member on forbidden endpoints.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import ProjectLicense, ProjectMemberRole, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def owner_user(db_session: AsyncSession) -> User:
    """Create the project owner."""
    user = User(
        email="t132owner@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Owner",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def member_user(db_session: AsyncSession) -> User:
    """Create a MEMBER-role user."""
    user = User(
        email="t132member@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Member",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create an ADMIN-role user."""
    user = User(
        email="t132admin@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Admin",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def invite_target_user(db_session: AsyncSession) -> User:
    """Create a user to be invited (for member invite tests)."""
    user = User(
        email="t132invite@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Invite Target",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_project(db_session: AsyncSession, owner_user: User) -> Project:
    """Create a RESTRICTED project owned by owner_user."""
    project = Project(
        name="T132 Test Project",
        description="Member vs Admin boundary test",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=owner_user.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def member_membership(
    db_session: AsyncSession,
    test_project: Project,
    member_user: User,
    owner_user: User,
) -> ProjectMember:
    """Add member_user as MEMBER on test_project."""
    membership = ProjectMember(
        user_id=member_user.id,
        project_id=test_project.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=owner_user.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
async def admin_membership(
    db_session: AsyncSession,
    test_project: Project,
    admin_user: User,
    owner_user: User,
) -> ProjectMember:
    """Add admin_user as ADMIN on test_project."""
    membership = ProjectMember(
        user_id=admin_user.id,
        project_id=test_project.id,
        role=ProjectMemberRole.ADMIN,
        invited_by_id=owner_user.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
def member_headers(member_user: User) -> dict[str, str]:
    """JWT auth headers for member_user."""
    token = create_access_token({"sub": str(member_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    """JWT auth headers for admin_user."""
    token = create_access_token({"sub": str(admin_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_headers(owner_user: User) -> dict[str, str]:
    """JWT auth headers for owner_user."""
    token = create_access_token({"sub": str(owner_user.id)})
    return {"Authorization": f"Bearer {token}"}


# A sentinel UUID that is unlikely to exist in the test DB.
_FAKE_UUID = "00000000-0000-0000-0000-000000000002"


# ---------------------------------------------------------------------------
# TestMemberForbidden — FR-008: Member must get 403 on MANAGE_MEMBERS /
#                               TRAIN_MODEL / DELETE_PROJECT endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemberForbidden:
    """Member must receive 403 on all endpoints that require MANAGE_MEMBERS,
    TRAIN_MODEL, or DELETE_PROJECT.

    The Stage-1 permission gate fires before any service logic, so a 403
    response confirms the gate is wired correctly.
    """

    async def test_invite_member_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
        invite_target_user: User,
    ) -> None:
        """POST /projects/{id}/members (MANAGE_MEMBERS) → 403 for Member."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/members",
            headers=member_headers,
            json={
                "email": invite_target_user.email,
                "role": "viewer",
            },
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on POST /members, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_update_member_role_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """PATCH /projects/{id}/members/{user_id} (MANAGE_MEMBERS) → 403 for Member."""
        response = await client.patch(
            f"/api/v1/projects/{test_project.id}/members/{_FAKE_UUID}",
            headers=member_headers,
            json={"role": "admin"},
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on PATCH /members/{{user_id}}, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_remove_member_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """DELETE /projects/{id}/members/{user_id} (MANAGE_MEMBERS) → 403 for Member."""
        response = await client.delete(
            f"/api/v1/projects/{test_project.id}/members/{_FAKE_UUID}",
            headers=member_headers,
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on DELETE /members/{{user_id}}, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_create_custom_model_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models (TRAIN_MODEL) → 403 for Member."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models",
            headers=member_headers,
            json={
                "name": "Test Model",
                "description": "A test model",
                "base_model": "birdnet",
            },
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on POST /custom-models, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_train_custom_model_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models/{m}/train (TRAIN_MODEL) → 403 for Member."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/train",
            headers=member_headers,
            json={},
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on POST /custom-models/{{m}}/train, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_apply_custom_model_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models/{m}/apply (TRAIN_MODEL) → 403 for Member."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/apply",
            headers=member_headers,
            json={"dataset_id": _FAKE_UUID},
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on POST /custom-models/{{m}}/apply, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_delete_project_is_403(
        self,
        client: AsyncClient,
        member_headers: dict[str, str],
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """DELETE /projects/{id} (DELETE_PROJECT, Owner only) → 403 for Member."""
        response = await client.delete(
            f"/api/v1/projects/{test_project.id}",
            headers=member_headers,
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on DELETE /projects/{{id}}, "
            f"got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# TestAdminAllowed — FR-008: Admin must NOT get 401/403 on MANAGE_MEMBERS /
#                            TRAIN_MODEL endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdminAllowed:
    """Admin must NOT receive 401/403 on MANAGE_MEMBERS / TRAIN_MODEL endpoints.

    Expected status codes for Admin:
      200 / 201 — success (resource created/found).
      404       — resource not found, but the permission gate passed.
      409       — conflict (e.g. member already exists) — gate passed.
      422       — validation error from service — gate passed.
      Any 4xx / 5xx that is NOT 401 / 403 is acceptable here.
    """

    async def test_invite_member_not_forbidden(
        self,
        client: AsyncClient,
        admin_headers: dict[str, str],
        admin_membership: ProjectMember,
        test_project: Project,
        invite_target_user: User,
    ) -> None:
        """POST /projects/{id}/members (MANAGE_MEMBERS) → not 401/403 for Admin."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/members",
            headers=admin_headers,
            json={
                "email": invite_target_user.email,
                "role": "viewer",
            },
        )
        assert response.status_code not in (401, 403), (
            f"Admin should not be blocked on POST /members, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_create_custom_model_not_forbidden(
        self,
        client: AsyncClient,
        admin_headers: dict[str, str],
        admin_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models (TRAIN_MODEL) → not 401/403 for Admin."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models",
            headers=admin_headers,
            json={
                "name": "Admin Model",
                "description": "Created by admin",
                "base_model": "birdnet",
            },
        )
        assert response.status_code not in (401, 403), (
            f"Admin should not be blocked on POST /custom-models, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_train_custom_model_not_forbidden(
        self,
        client: AsyncClient,
        admin_headers: dict[str, str],
        admin_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models/{m}/train (TRAIN_MODEL) → not 401/403 for Admin.

        The model ID is a fake UUID, so the gate passes (Admin has TRAIN_MODEL)
        but the service returns 404 (model not found). 404 here proves the gate
        did NOT block the Admin.
        """
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/train",
            headers=admin_headers,
            json={},
        )
        assert response.status_code not in (401, 403), (
            f"Admin should not be blocked on POST /custom-models/{{m}}/train, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_delete_project_is_403_for_admin(
        self,
        client: AsyncClient,
        admin_headers: dict[str, str],
        admin_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """DELETE /projects/{id} (DELETE_PROJECT, Owner only) → 403 for Admin.

        Admin has MANAGE_MEMBERS and TRAIN_MODEL but NOT DELETE_PROJECT.
        The canonical matrix grants DELETE_PROJECT only to OWNER.
        """
        response = await client.delete(
            f"/api/v1/projects/{test_project.id}",
            headers=admin_headers,
        )
        assert response.status_code == 403, (
            f"Expected 403 for Admin on DELETE /projects/{{id}}, "
            f"got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# TestOwnerAllowed — FR-008: Owner must NOT get 401/403 on DELETE_PROJECT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOwnerAllowed:
    """Owner must NOT receive 401/403 on DELETE_PROJECT endpoint."""

    async def test_delete_project_not_forbidden(
        self,
        client: AsyncClient,
        owner_headers: dict[str, str],
        test_project: Project,
    ) -> None:
        """DELETE /projects/{id} (DELETE_PROJECT) → 204 for Owner.

        The owner deletes their own project — expected 204.
        """
        response = await client.delete(
            f"/api/v1/projects/{test_project.id}",
            headers=owner_headers,
        )
        assert response.status_code not in (401, 403), (
            f"Owner should not be blocked on DELETE /projects/{{id}}, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_invite_member_not_forbidden(
        self,
        client: AsyncClient,
        owner_headers: dict[str, str],
        test_project: Project,
        invite_target_user: User,
    ) -> None:
        """POST /projects/{id}/members (MANAGE_MEMBERS) → not 401/403 for Owner."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/members",
            headers=owner_headers,
            json={
                "email": invite_target_user.email,
                "role": "viewer",
            },
        )
        assert response.status_code not in (401, 403), (
            f"Owner should not be blocked on POST /members, got {response.status_code}: "
            f"{response.text}"
        )
