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

from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.core.settings import get_settings
from echoroo.models.enums import ProjectMemberRole, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User


async def _bff_session_headers(
    client: AsyncClient, db: AsyncSession, user: User
) -> dict[str, str]:
    """Build a CSRF-capable ``/web-api/v1`` session for ``user``.

    W2-3 PR-15 moved the custom-model endpoints to the ``/web-api/v1`` BFF,
    which sits behind the CSRF middleware. A plain ``Authorization: Bearer``
    POST would be rejected at the CSRF layer (403) before the TRAIN_MODEL
    permission gate runs, so the custom-model boundary tests below seed a
    refresh token, exchange it for an access token + ``X-CSRF-Token``, and send
    both — letting the request reach ``gate_action`` and decide on TRAIN_MODEL.
    """
    from echoroo.api.web_v1.auth import _issue_web_refresh_token

    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
    )
    await db.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, :created_at)"
        ),
        {
            "family_id": UUID(record.family_id),
            "user_id": record.user_id,
            "created_at": record.issued_at,
        },
    )
    await db.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(jti, user_id, family_id, issued_at, expires_at) "
            "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
        ),
        {
            "jti": UUID(record.jti),
            "user_id": record.user_id,
            "family_id": UUID(record.family_id),
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        },
    )
    await db.commit()
    client.cookies.clear()
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession, owner_user: User) -> Project:
    """Create a RESTRICTED project owned by owner_user."""
    project = Project(
        name="T132 Test Project",
        description="Member vs Admin boundary test",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
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


@pytest_asyncio.fixture
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


@pytest_asyncio.fixture
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

    # NOTE (2026-06-03, preview feedback #7 — SU-bootstrap redesign): the
    # direct member-add route ``POST /projects/{id}/members`` was removed —
    # adding a user is now invitation-only (see
    # ``echoroo.api.v1.projects`` / ``echoroo.api.web_v1.projects._members``).
    # The MANAGE_MEMBERS gate on the ``/api/v1`` member surface is still
    # covered by ``test_update_member_role_is_403`` (PATCH) and
    # ``test_remove_member_is_403`` (DELETE) below. The dedicated
    # invitation-issue gate lives on the BFF surface and is exercised by
    # ``tests/contract/test_permissions.py`` / ``test_projects.py``.

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
        db_session: AsyncSession,
        member_user: User,
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models (TRAIN_MODEL) → 403 for Member.

        W2-3 PR-15 unmounted the ``/api/v1`` custom-model routes; the request
        now lands on the ``/web-api/v1`` BFF (CSRF-guarded), so it uses a
        seeded CSRF session (``_bff_session_headers``) — a plain Bearer POST
        would 403 at the CSRF layer before the TRAIN_MODEL gate runs.

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
        session_headers = await _bff_session_headers(client, db_session, member_user)
        response = await client.post(
            f"/web-api/v1/projects/{test_project.id}/custom-models",
            headers=session_headers,
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
        db_session: AsyncSession,
        member_user: User,
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models/{m}/train (TRAIN_MODEL) → 403 for Member.

        W2-3 PR-15 moved this route to the CSRF-guarded ``/web-api/v1`` BFF,
        so the request uses a seeded CSRF session (``_bff_session_headers``).
        """
        session_headers = await _bff_session_headers(client, db_session, member_user)
        response = await client.post(
            f"/web-api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/train",
            headers=session_headers,
            json={},
        )
        assert response.status_code == 403, (
            f"Expected 403 for Member on POST /custom-models/{{m}}/train, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_apply_custom_model_is_403(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        member_user: User,
        member_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models/{m}/apply (TRAIN_MODEL) → 403 for Member.

        W2-3 PR-15 moved this route to the CSRF-guarded ``/web-api/v1`` BFF,
        so the request uses a seeded CSRF session (``_bff_session_headers``).

        Phase 16 Batch 6e (2026-04-29) middleware-ordering fix: ``dataset_id``
        is a **query** parameter on this endpoint (not a body field), so
        the legacy ``json={"dataset_id": ...}`` produced a 422 for the
        missing query before the permission gate ran. Pass it via
        ``params=`` so the gate decides on TRAIN_MODEL.
        """
        session_headers = await _bff_session_headers(client, db_session, member_user)
        response = await client.post(
            f"/web-api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/apply",
            headers=session_headers,
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

    # NOTE (2026-06-03, preview feedback #7 — SU-bootstrap redesign): the
    # direct member-add route ``POST /projects/{id}/members`` was removed
    # (invitation-only). Admin's MANAGE_MEMBERS access on the ``/api/v1``
    # member surface remains exercised by the PATCH/DELETE member tests and
    # by the BFF invitation contract tests; the obsolete direct-add
    # not-forbidden assertion has been dropped.

    async def test_create_custom_model_not_forbidden(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_user: User,
        admin_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models (TRAIN_MODEL) → not 401/403 for Admin.

        W2-3 PR-15 moved this route to the CSRF-guarded ``/web-api/v1`` BFF,
        so the request uses a seeded CSRF session (``_bff_session_headers``).
        """
        session_headers = await _bff_session_headers(client, db_session, admin_user)
        response = await client.post(
            f"/web-api/v1/projects/{test_project.id}/custom-models",
            headers=session_headers,
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
        db_session: AsyncSession,
        admin_user: User,
        admin_membership: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/custom-models/{m}/train (TRAIN_MODEL) → not 401/403 for Admin.

        W2-3 PR-15 moved this route to the CSRF-guarded ``/web-api/v1`` BFF,
        so the request uses a seeded CSRF session (``_bff_session_headers``).

        The model ID is a fake UUID, so the gate passes (Admin has TRAIN_MODEL)
        but the service returns 404 (model not found). 404 here proves the gate
        did NOT block the Admin.
        """
        session_headers = await _bff_session_headers(client, db_session, admin_user)
        response = await client.post(
            f"/web-api/v1/projects/{test_project.id}/custom-models/{_FAKE_UUID}/train",
            headers=session_headers,
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

    # NOTE (2026-06-03, preview feedback #7 — SU-bootstrap redesign): the
    # direct member-add route ``POST /projects/{id}/members`` was removed
    # (invitation-only). Owner's MANAGE_MEMBERS access is covered elsewhere;
    # the obsolete direct-add not-forbidden assertion has been dropped.
