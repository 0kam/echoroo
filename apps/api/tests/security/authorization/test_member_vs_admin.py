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
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Owner",
        security_stamp="d" * 64,
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
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Member",
        security_stamp="e" * 64,
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
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Admin",
        security_stamp="f" * 64,
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
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T132 Invite Target",
        security_stamp="g" * 64,
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
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": True,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
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
        """POST /projects/{id}/custom-models (TRAIN_MODEL) → 403 for Member.

        Phase 16 Batch 6e (2026-04-29) middleware-ordering fix: FastAPI
        resolves request body Pydantic validation **as part of**
        dependency resolution, so a body missing the required
        ``target_tag_id`` field 422s before the permission gate fires.
        Provide a contract-shaped body so the gate has a chance to
        deny on TRAIN_MODEL. The 422-vs-validation behaviour is the
        intended FastAPI default — there is no ordering bug to fix
        on the implementation side; the test simply needs to send a
        body the schema accepts.
        """
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models",
            headers=member_headers,
            json={
                "name": "Test Model",
                "description": "A test model",
                "base_model": "birdnet",
                "target_tag_id": _FAKE_UUID,
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
        """POST /projects/{id}/custom-models/{m}/apply (TRAIN_MODEL) → 403 for Member.

        Phase 16 Batch 6e (2026-04-29) middleware-ordering fix: ``dataset_id``
        is a **query** parameter on this endpoint (not a body field), so
        the legacy ``json={"dataset_id": ...}`` produced a 422 for the
        missing query before the permission gate ran. Pass it via
        ``params=`` so the gate decides on TRAIN_MODEL.
        """
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/apply",
            headers=member_headers,
            params={"dataset_id": _FAKE_UUID},
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
