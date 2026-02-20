"""Contract tests for annotation projects API endpoints.

Tests verify that endpoints conform to the annotation project specification.
"""

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.enums import AnnotationProjectVisibility

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.user import User


@pytest.fixture
async def test_annotation_project(
    db_session: AsyncSession,
    test_project: "Project",
    test_user: "User",
) -> AnnotationProject:
    """Create a test annotation project directly in the database.

    Args:
        db_session: Database session
        test_project: Parent project
        test_user: Project owner (used as creator)

    Returns:
        AnnotationProject instance
    """
    annotation_project = AnnotationProject(
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Test Annotation Project",
        description="A test annotation project",
        instructions="Label all bird sounds you hear",
        visibility=AnnotationProjectVisibility.PRIVATE,
    )
    db_session.add(annotation_project)
    await db_session.commit()
    await db_session.refresh(annotation_project)
    return annotation_project


@pytest.mark.asyncio
class TestAnnotationProjectListEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-projects."""

    async def test_list_annotation_projects_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET returns empty list when no annotation projects exist."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_annotation_projects_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET returns annotation projects when they exist."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["name"] == test_annotation_project.name

    async def test_list_annotation_projects_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationProjectCreateEndpoint:
    """Test POST /api/v1/projects/{project_id}/annotation-projects."""

    async def test_create_annotation_project_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST creates annotation project with full data (201)."""
        payload = {
            "name": "Bird Species Survey",
            "description": "Annotation project for bird species identification",
            "instructions": "Label each clip with the bird species you hear",
            "visibility": "private",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()

        # Verify response structure
        assert "id" in data
        assert "project_id" in data
        assert "created_by_id" in data
        assert data["name"] == payload["name"]
        assert data["description"] == payload["description"]
        assert data["instructions"] == payload["instructions"]
        assert data["visibility"] == payload["visibility"]
        assert "created_at" in data
        assert "updated_at" in data
        assert "datasets" in data
        assert "tags" in data
        assert "progress" in data

        # Verify progress structure
        progress = data["progress"]
        assert "total_tasks" in progress
        assert "completed_tasks" in progress
        assert "in_progress_tasks" in progress
        assert "pending_tasks" in progress
        assert "review_pending_tasks" in progress
        assert progress["total_tasks"] == 0

    async def test_create_annotation_project_minimal(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST creates annotation project with only required field (name)."""
        payload = {
            "name": "Minimal Annotation Project",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == payload["name"]
        assert data["description"] is None
        assert data["instructions"] is None
        assert data["visibility"] == "private"  # default value

    async def test_create_annotation_project_empty_name_validation_error(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test POST returns 422 when name is empty string."""
        payload = {
            "name": "",
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects",
            headers=auth_headers,
            json=payload,
        )

        assert response.status_code == 422

    async def test_create_annotation_project_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test POST requires authentication."""
        payload = {"name": "Unauthorized Project"}

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects",
            json=payload,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationProjectGetDetailEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-projects/{id}."""

    async def test_get_annotation_project_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET returns annotation project detail with progress (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify full detail structure
        assert data["id"] == str(test_annotation_project.id)
        assert data["project_id"] == str(test_annotation_project.project_id)
        assert data["created_by_id"] == str(test_annotation_project.created_by_id)
        assert data["name"] == test_annotation_project.name
        assert data["description"] == test_annotation_project.description
        assert data["instructions"] == test_annotation_project.instructions
        assert data["visibility"] == test_annotation_project.visibility.value
        assert "created_at" in data
        assert "updated_at" in data

        # Verify related data
        assert "datasets" in data
        assert isinstance(data["datasets"], list)
        assert "tags" in data
        assert isinstance(data["tags"], list)

        # Verify progress structure
        assert "progress" in data
        progress = data["progress"]
        assert "total_tasks" in progress
        assert "completed_tasks" in progress
        assert "in_progress_tasks" in progress
        assert "pending_tasks" in progress
        assert "review_pending_tasks" in progress

    async def test_get_annotation_project_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET returns 404 for non-existent annotation project."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_annotation_project_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationProjectUpdateEndpoint:
    """Test PATCH /api/v1/projects/{project_id}/annotation-projects/{id}."""

    async def test_update_annotation_project_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test PATCH updates annotation project (200)."""
        update_payload = {
            "name": "Updated Annotation Project",
            "description": "Updated description",
            "instructions": "Updated instructions",
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}",
            headers=auth_headers,
            json=update_payload,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == update_payload["name"]
        assert data["description"] == update_payload["description"]
        assert data["instructions"] == update_payload["instructions"]
        assert data["id"] == str(test_annotation_project.id)

    async def test_update_annotation_project_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test PATCH returns 404 for non-existent annotation project."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        update_payload = {"name": "Updated Name"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{fake_id}",
            headers=auth_headers,
            json=update_payload,
        )

        assert response.status_code == 404

    async def test_update_annotation_project_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test PATCH requires authentication."""
        update_payload = {"name": "Updated Name"}

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}",
            json=update_payload,
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationProjectDeleteEndpoint:
    """Test DELETE /api/v1/projects/{project_id}/annotation-projects/{id}."""

    async def test_delete_annotation_project_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
        test_user: "User",
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test DELETE removes annotation project (204)."""
        annotation_project_id = test_annotation_project.id

        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{annotation_project_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify it no longer exists
        get_response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{annotation_project_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_annotation_project_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE returns 404 for non-existent annotation project."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_annotation_project_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test DELETE requires authentication."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestExportAnnotationsEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-projects/{id}/export."""

    async def test_export_json_format(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET export as JSON returns valid response (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/export?format=json",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert "annotation_project" in data
        assert "annotations" in data

    async def test_export_csv_format(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET export as CSV returns valid CSV (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/export?format=csv",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        # Verify CSV headers present in response body
        text = response.text
        assert "Selection" in text
        assert "Begin Time (s)" in text
        assert "End Time (s)" in text

    async def test_export_aoef_format(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET export as AOEF returns valid JSON (200).

        AOEF is a JSON-based format for soundevent compatibility.
        """
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/export?format=aoef",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert "info" in data
        assert data["info"]["format"] == "aoef"
        assert "clip_annotations" in data
        assert "sound_event_annotations" in data

    async def test_export_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/export?format=json"
        )
        assert response.status_code == 401

    async def test_export_invalid_format(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET with invalid format returns 422.

        Uses a fake annotation project ID since format validation happens
        before the project lookup, so no real project is needed.
        """
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{fake_id}/export?format=invalid_format",
            headers=auth_headers,
        )
        assert response.status_code == 422
