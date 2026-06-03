"""Contract tests for project management endpoints.

Tests verify that endpoints conform to the OpenAPI specification in
specs/001-administration/contracts/openapi.yaml.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient

if TYPE_CHECKING:
    from echoroo.models.project import ProjectMember


@pytest.mark.asyncio
class TestProjectEndpoints:
    """Test project CRUD endpoints."""

    async def test_list_projects(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test GET /api/v1/projects - List projects with pagination.

        Phase 9 polish round 3 致命 1 + Major 1 (2026-04-27): the response
        shape is now :class:`ProjectSummaryListResponse` (contracts/
        projects.yaml:7 covers both ``/api/v1`` and ``/web-api/v1``;
        ``ProjectListResponse`` declares ``items: ProjectSummary[]``) and
        the contract envelope is ``items / total / page`` only — no
        ``limit`` field. Each row is the ``ProjectSummary`` shape (id /
        name / description / visibility / status / license /
        owner_display_name / dataset_count / species_preview), so the
        legacy assertions for ``restricted_config`` / ``owner`` sub-object
        / timestamps are gone too (those keys are structurally absent).
        """
        response = await client.get(
            "/api/v1/projects",
            headers=auth_headers,
            params={"page": 1, "limit": 20},
        )

        assert response.status_code == 200
        data = response.json()

        # Contract envelope (contracts/projects.yaml:375-383):
        # items / total / page only.
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "limit" not in data, (
            "ProjectListResponse contract has no 'limit' field "
            "(contracts/projects.yaml:375-383)"
        )
        assert isinstance(data["items"], list)
        assert data["page"] == 1

        # Spot-check ProjectSummary row shape if any rows are present.
        if data["items"]:
            row = data["items"][0]
            for required_key in (
                "id",
                "name",
                "description",
                "visibility",
                "status",
                "license",
                "owner_display_name",
                "dataset_count",
                "species_preview",
            ):
                assert required_key in row, (
                    f"ProjectSummary contract requires '{required_key}'"
                )
            # Fields that belong to the legacy ProjectResponse shape but
            # are deliberately omitted from ProjectSummary to prevent
            # Restricted enumeration leaks (FR-018 / FR-019 / FR-030).
            for forbidden_key in (
                "restricted_config",
                "restricted_config_version",
                "owner",
                "created_at",
                "updated_at",
                "dormant_since",
                "archived_since",
            ):
                assert forbidden_key not in row, (
                    f"ProjectSummary list rows must not carry "
                    f"'{forbidden_key}' (contracts/projects.yaml:"
                    f"ProjectSummary)"
                )

    async def test_list_projects_unauthorized(self, client: AsyncClient) -> None:
        """Test GET /api/v1/projects requires authentication."""
        response = await client.get("/api/v1/projects")

        assert response.status_code == 401

    async def test_create_project(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test POST /api/v1/projects - Create project.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: Phase 7 / T320
        (FR-085) made ``license`` required at creation and the spec
        eliminated ``"private"`` visibility (Public / Restricted only).
        The legacy body using ``"visibility": "private"`` and no license
        now 422s on schema validation. Use ``visibility="public"`` here so
        the test does not also need to populate the eight-toggle
        ``restricted_config`` shape required by the
        ``ck_projects_restricted_config_shape`` DB CHECK; the goal of
        the assertion is the contract envelope, not the Restricted
        toggle plumbing (which has its own dedicated suites).
        """
        project_data = {
            "name": "Test Project",
            "description": "A test research project",
            "visibility": "public",
            "license_id": "cc-by",
        }

        response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json=project_data,
        )

        assert response.status_code == 201, response.text
        data = response.json()

        # Verify response structure matches ProjectResponse
        assert "id" in data
        assert data["name"] == project_data["name"]
        assert data["description"] == project_data["description"]
        assert data["visibility"] == project_data["visibility"]
        assert "owner" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_project_minimal(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test POST /api/v1/projects with minimal required fields.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: Phase 7 / T320
        (FR-085) made ``visibility`` and ``license`` required at creation.
        The legacy "minimal = name only" expectation no longer matches
        the contract; the new minimum is name + visibility + license.
        Use ``"public"`` to skip the Restricted toggle plumbing.
        """
        project_data = {
            "name": "Minimal Project",
            "visibility": "public",
            "license_id": "cc-by",
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
        assert data["visibility"] == "public"

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

    async def test_create_project_rejects_legacy_private_visibility(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Test POST /api/v1/projects rejects legacy private visibility."""
        project_data = {
            "name": "Legacy Private Project",
            "visibility": "private",
            "license_id": "cc-by",
        }

        response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json=project_data,
        )

        assert response.status_code == 422

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
        """Test GET /api/v1/projects/{projectId} without access.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: the legacy
        expectation was 403 because the old "private" visibility hid
        all non-member detail. Phase 9 (FR-018 / FR-019) replaced that
        with the Public / Restricted matrix: a Restricted project (the
        ``test_project`` fixture default) **does** allow Authenticated
        non-members to read the detail metadata via
        ``Permission.VIEW_PROJECT_METADATA`` so the Web UI can render
        the "Request access" callout (US4 AC2). Restricted detail
        responses still scrub ``restricted_config`` / owner email for
        non-members (covered by the dedicated Phase 9 / US4 suites).
        The expectation here is therefore 200 — Authenticated callers
        always reach the Restricted-metadata surface.
        """
        response = await client.get(
            f"/api/v1/projects/{test_project_id}",
            headers=auth_headers_other,
        )

        assert response.status_code == 200, response.text

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
        """Test DELETE /api/v1/projects/{projectId} - Delete project.

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: Phase 7 / T320
        requires ``visibility`` + ``license`` at creation; bringing the
        request body in line with the contract so the delete path can
        actually reach the DELETE assertion.
        """
        # Create a project to delete
        create_response = await client.post(
            "/api/v1/projects",
            headers=auth_headers,
            json={
                "name": "Project to Delete",
                "visibility": "public",
                "license_id": "cc-by",
            },
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

    # NOTE (2026-06-03, preview feedback #7): the direct member-add tests
    # (test_add_member / test_add_member_already_exists /
    # test_add_member_not_admin) were removed alongside the
    # ``POST /api/v1/projects/{id}/members`` endpoint. Adding a user to a
    # project is invitation-only; the invitation flow is covered by the
    # member-invitation suites.

    async def test_update_member_role(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_member: ProjectMember,  # noqa: F821
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
        test_member: ProjectMember,  # noqa: F821
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
