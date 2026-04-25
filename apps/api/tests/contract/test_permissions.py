"""Contract tests for project permission system.

Tests verify that role-based access control (RBAC) works correctly
for different user roles: admin, member, viewer.

T130 (spec PR-002, SC-001): adds a table-driven permission matrix test that
covers 28 Permissions × 6 principals × 2 visibilities via ``is_allowed`` and
``ROLE_PERMISSIONS``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import (
    ACTIONS,
    ROLE_PERMISSIONS,
    Permission,
    ProjectRole,
    ProjectVisibility,
    compute_effective_permissions,
    is_allowed,
    normalize_role,
)
from echoroo.models.enums import ProjectMemberRole
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

# =============================================================================
# Local test helpers
# =============================================================================


DEFAULT_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 2,
    "allow_precise_location_to_viewer": False,
}


def _make_project(visibility: ProjectVisibility) -> SimpleNamespace:
    """Build a lightweight project stub for pure-function tests."""
    return SimpleNamespace(
        id="proj-matrix",
        owner_id="owner-matrix",
        visibility=visibility,
        restricted_config=DEFAULT_RESTRICTED_CONFIG.copy(),
        status="active",
    )


def _make_user(
    *,
    user_id: str = "user-matrix",
    project_role: ProjectRole | None = None,
    owner: bool = False,
) -> SimpleNamespace:
    """Build a lightweight user stub for pure-function tests."""
    return SimpleNamespace(
        id="owner-matrix" if owner else user_id,
        is_superuser=False,
        project_role=project_role,
    )


# =============================================================================
# Expected permission sets per spec Canonical Matrix
# =============================================================================

# (role_label, normalized_role, visibility) → frozenset[Permission]
# toggles are all OFF (DEFAULT_RESTRICTED_CONFIG above).

_PUBLIC_GUEST_EXPECTED: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
    }
)

_PUBLIC_AUTHENTICATED_EXPECTED: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.SEARCH_WITHIN_PROJECT,
        Permission.SEARCH_CROSS_PROJECT,
        Permission.DOWNLOAD,
        Permission.EXPORT,
        Permission.VOTE,
        Permission.COMMENT,
    }
)

# Viewer on PUBLIC normalizes to Authenticated (FR-004).
_PUBLIC_VIEWER_EXPECTED: frozenset[Permission] = _PUBLIC_AUTHENTICATED_EXPECTED

_RESTRICTED_GUEST_EXPECTED: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
    }
)

_RESTRICTED_AUTHENTICATED_EXPECTED: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
    }
)

_RESTRICTED_VIEWER_EXPECTED: frozenset[Permission] = frozenset(
    ROLE_PERMISSIONS[ProjectRole.VIEWER]
)

_RESTRICTED_MEMBER_EXPECTED: frozenset[Permission] = frozenset(
    ROLE_PERMISSIONS[ProjectRole.MEMBER]
)

_RESTRICTED_ADMIN_EXPECTED: frozenset[Permission] = frozenset(
    ROLE_PERMISSIONS[ProjectRole.ADMIN]
)

_RESTRICTED_OWNER_EXPECTED: frozenset[Permission] = frozenset(
    ROLE_PERMISSIONS[ProjectRole.OWNER]
)

# Member/Admin/Owner have same perms on Public as Restricted (Canonical Matrix
# is the same; visibility only affects Guest/Authenticated).
_PUBLIC_MEMBER_EXPECTED: frozenset[Permission] = _RESTRICTED_MEMBER_EXPECTED
_PUBLIC_ADMIN_EXPECTED: frozenset[Permission] = _RESTRICTED_ADMIN_EXPECTED
_PUBLIC_OWNER_EXPECTED: frozenset[Permission] = _RESTRICTED_OWNER_EXPECTED


# =============================================================================
# T130-a: ROLE_PERMISSIONS matrix shape (quick sanity, no DB needed)
# =============================================================================


class TestRolePermissionsMatrix:
    """FR-010 Canonical Matrix: ROLE_PERMISSIONS shapes are exact."""

    def test_role_permissions_has_exactly_four_roles(self) -> None:
        expected = {ProjectRole.VIEWER, ProjectRole.MEMBER, ProjectRole.ADMIN, ProjectRole.OWNER}
        assert set(ROLE_PERMISSIONS.keys()) == expected

    def test_role_permissions_are_frozensets(self) -> None:
        for role, perms in ROLE_PERMISSIONS.items():
            assert isinstance(perms, frozenset), f"{role}: expected frozenset"

    @pytest.mark.parametrize("role", list(ProjectRole))
    def test_role_permissions_monotone(self, role: ProjectRole) -> None:
        """Higher roles must include all permissions of lower roles."""
        order = [ProjectRole.VIEWER, ProjectRole.MEMBER, ProjectRole.ADMIN, ProjectRole.OWNER]
        idx = order.index(role)
        for lower in order[:idx]:
            assert ROLE_PERMISSIONS[lower] <= ROLE_PERMISSIONS[role], (
                f"ROLE_PERMISSIONS[{role}] is not a superset of ROLE_PERMISSIONS[{lower}]"
            )


# =============================================================================
# T130-b: compute_effective_permissions — 6 principals × 2 visibilities
# =============================================================================


@pytest.mark.parametrize(
    ("pre_normalize_role", "visibility", "expected"),
    [
        # --- PUBLIC ---
        # normalize_role is called upstream; Viewer → Authenticated on PUBLIC (FR-004).
        ("Guest",         ProjectVisibility.PUBLIC,      _PUBLIC_GUEST_EXPECTED),
        ("Authenticated", ProjectVisibility.PUBLIC,      _PUBLIC_AUTHENTICATED_EXPECTED),
        # Viewer on PUBLIC normalizes to Authenticated before reaching compute_*;
        # the parametrize row label still says "Viewer" to document the principal.
        ("Viewer",        ProjectVisibility.PUBLIC,      _PUBLIC_VIEWER_EXPECTED),
        ("Member",        ProjectVisibility.PUBLIC,      _PUBLIC_MEMBER_EXPECTED),
        ("Admin",         ProjectVisibility.PUBLIC,      _PUBLIC_ADMIN_EXPECTED),
        ("Owner",         ProjectVisibility.PUBLIC,      _PUBLIC_OWNER_EXPECTED),
        # --- RESTRICTED (all toggles OFF) ---
        ("Guest",         ProjectVisibility.RESTRICTED,  _RESTRICTED_GUEST_EXPECTED),
        ("Authenticated", ProjectVisibility.RESTRICTED,  _RESTRICTED_AUTHENTICATED_EXPECTED),
        ("Viewer",        ProjectVisibility.RESTRICTED,  _RESTRICTED_VIEWER_EXPECTED),
        ("Member",        ProjectVisibility.RESTRICTED,  _RESTRICTED_MEMBER_EXPECTED),
        ("Admin",         ProjectVisibility.RESTRICTED,  _RESTRICTED_ADMIN_EXPECTED),
        ("Owner",         ProjectVisibility.RESTRICTED,  _RESTRICTED_OWNER_EXPECTED),
    ],
)
def test_effective_permissions_matrix_cell(
    pre_normalize_role: str,
    visibility: ProjectVisibility,
    expected: frozenset[Permission],
) -> None:
    """T130-b: compute_effective_permissions matches spec for every (role, vis) cell.

    normalize_role is applied before compute_effective_permissions to mirror the
    production call path (resolve_role → normalize_role → compute_effective_*).
    """
    project = _make_project(visibility)
    normalized_role = normalize_role(pre_normalize_role, project)
    actual = compute_effective_permissions(normalized_role=normalized_role, project=project)
    assert actual == expected, (
        f"({normalized_role}, {visibility.value}) mismatch.\n"
        f"  missing: {expected - actual}\n"
        f"  extra:   {actual - expected}"
    )


# =============================================================================
# T130-c: is_allowed gate — 28 permissions × 6 principals × 2 visibilities
# =============================================================================

# Build a parametrize table: (principal_label, normalized_role, visibility, permission, expected_allowed)
# We derive expected_allowed from compute_effective_permissions so the test
# exercises is_allowed (the gate) independently of the raw set.

def _build_is_allowed_params() -> list[tuple[str, str, ProjectVisibility, Permission, bool]]:
    rows: list[tuple[str, str, ProjectVisibility, Permission, bool]] = []

    principal_map = [
        ("Guest",         "Guest"),
        ("AuthUser",      "Authenticated"),
        ("Viewer",        "Viewer"),
        ("Member",        "Member"),
        ("Admin",         "Admin"),
        ("Owner",         "Owner"),
    ]

    for visibility in ProjectVisibility:
        for principal_label, normalized_role in principal_map:
            # For Public, Viewer normalizes to Authenticated upstream.
            effective_role = (
                "Authenticated"
                if visibility == ProjectVisibility.PUBLIC and normalized_role == "Viewer"
                else normalized_role
            )
            project = _make_project(visibility)
            effective = compute_effective_permissions(
                normalized_role=effective_role, project=project
            )
            for perm in Permission:
                # USER_SCOPE_PERMISSIONS require a logged-in user.
                from echoroo.core.permissions import USER_SCOPE_PERMISSIONS
                if perm in USER_SCOPE_PERMISSIONS:
                    expected = normalized_role not in ("Guest",)
                else:
                    expected = perm in effective
                rows.append((principal_label, normalized_role, visibility, perm, expected))
    return rows


_IS_ALLOWED_PARAMS = _build_is_allowed_params()

# Derive a single Action for each Permission from the ACTIONS catalog.
# Some permissions may have no registered Action (admin-only, platform scope,
# or not yet wired in Phase 3) — those are wrapped in xfail below.
def _action_for_permission(perm: Permission) -> Any:
    """Return the first Action with required_permission == perm, or None."""
    for action in ACTIONS.values():
        if action.required_permission == perm:
            return action
    return None


@pytest.mark.parametrize(
    ("principal_label", "normalized_role", "visibility", "permission", "expected_allowed"),
    _IS_ALLOWED_PARAMS,
    ids=[
        f"{p}-{r}-{v.value}-{perm.value}"
        for p, r, v, perm, _ in _IS_ALLOWED_PARAMS
    ],
)
def test_is_allowed_matrix(
    principal_label: str,
    normalized_role: str,
    visibility: ProjectVisibility,
    permission: Permission,
    expected_allowed: bool,
) -> None:
    """T130-c: is_allowed gate matches spec Canonical Matrix for all cells.

    Spec: PR-002, SC-001 — 28 Permission × 6 principals × 2 visibilities.
    Skips cells where no registered Action maps the required_permission.
    """

    action = _action_for_permission(permission)
    if action is None:
        # No Action in catalog for this permission — xfail (not yet wired).
        pytest.xfail(
            f"No Action registered for Permission.{permission.name} "
            f"(permission not yet wired in Phase 3 Action catalog)"
        )

    # Build user stub matching the normalized_role.
    if normalized_role == "Guest":
        user = None
    elif normalized_role == "Owner":
        user = _make_user(owner=True)
    elif normalized_role in ("Viewer", "Member", "Admin"):
        role_map = {
            "Viewer": ProjectRole.VIEWER,
            "Member": ProjectRole.MEMBER,
            "Admin": ProjectRole.ADMIN,
        }
        user = _make_user(project_role=role_map[normalized_role])
    else:
        # Authenticated — logged in but no project membership.
        user = _make_user()

    project = _make_project(visibility)

    allowed, effective = is_allowed(action=action, user=user, project=project)
    assert allowed == expected_allowed, (
        f"is_allowed({principal_label}, {visibility.value}, {permission.value}): "
        f"got {allowed!r}, want {expected_allowed!r}. "
        f"effective={sorted(p.value for p in effective)}"
    )


# =============================================================================
# T130-d: normalize_role correctness (FR-004, FR-007)
# =============================================================================


@pytest.mark.parametrize(
    ("visibility", "raw_role", "expected"),
    [
        (ProjectVisibility.PUBLIC, "Viewer", "Authenticated"),
        (ProjectVisibility.PUBLIC, "Authenticated", "Authenticated"),
        (ProjectVisibility.PUBLIC, "Guest", "Guest"),
        (ProjectVisibility.PUBLIC, "Member", "Member"),
        (ProjectVisibility.PUBLIC, "Admin", "Admin"),
        (ProjectVisibility.PUBLIC, "Owner", "Owner"),
        (ProjectVisibility.RESTRICTED, "Viewer", "Viewer"),
        (ProjectVisibility.RESTRICTED, "Authenticated", "Authenticated"),
        (ProjectVisibility.RESTRICTED, "Guest", "Guest"),
        (ProjectVisibility.RESTRICTED, "Member", "Member"),
        (ProjectVisibility.RESTRICTED, "Admin", "Admin"),
        (ProjectVisibility.RESTRICTED, "Owner", "Owner"),
    ],
)
def test_normalize_role(
    visibility: ProjectVisibility, raw_role: str, expected: str
) -> None:
    """FR-004 / FR-007: normalize_role maps (Public + Viewer) → Authenticated."""
    project = _make_project(visibility)
    assert normalize_role(raw_role, project) == expected


# =============================================================================
# Existing HTTP-level RBAC contract tests (T042 — preserved unchanged)
# =============================================================================


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
        role=ProjectMemberRole.VIEWER,
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
