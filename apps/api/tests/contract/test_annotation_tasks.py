"""Contract tests for annotation tasks API endpoints.

Tests verify that endpoints conform to the annotation task specification.
"""

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.clip import Clip
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    AnnotationProjectVisibility,
    AnnotationTaskStatus,
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
)
from echoroo.models.recording import Recording
from echoroo.models.site import Site

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


@pytest.fixture
async def test_clip(
    db_session: AsyncSession,
    test_project: "Project",
    test_user: "User",
) -> Clip:
    """Create a test clip with its parent recording, dataset, and site.

    Args:
        db_session: Database session
        test_project: Parent project
        test_user: Creator user

    Returns:
        Clip instance
    """
    site = Site(
        project_id=test_project.id,
        name="Test Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.flush()

    dataset = Dataset(
        site_id=site.id,
        project_id=test_project.id,
        created_by_id=test_user.id,
        name="Test Dataset",
        audio_dir="/audio/test",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.flush()

    recording = Recording(
        dataset_id=dataset.id,
        filename="test.wav",
        path="test/test.wav",
        hash="abc123",
        duration=60.0,
        samplerate=44100,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
    )
    db_session.add(recording)
    await db_session.flush()

    clip = Clip(
        recording_id=recording.id,
        start_time=0.0,
        end_time=5.0,
    )
    db_session.add(clip)
    await db_session.commit()
    await db_session.refresh(clip)
    return clip


@pytest.fixture
async def test_annotation_task(
    db_session: AsyncSession,
    test_annotation_project: AnnotationProject,
    test_clip: Clip,
) -> AnnotationTask:
    """Create a test annotation task linked to a project and clip.

    Args:
        db_session: Database session
        test_annotation_project: Parent annotation project
        test_clip: Clip to be annotated

    Returns:
        AnnotationTask instance
    """
    task = AnnotationTask(
        annotation_project_id=test_annotation_project.id,
        clip_id=test_clip.id,
        status=AnnotationTaskStatus.PENDING,
        priority=0,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


@pytest.mark.asyncio
class TestAnnotationTaskListEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks."""

    async def test_list_tasks_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET returns empty list when no tasks exist."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)
        assert data["total"] == 0
        assert data["items"] == []

    async def test_list_tasks_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test GET returns tasks when they exist."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 1
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["id"] == str(test_annotation_task.id)
        assert item["status"] == "pending"

    async def test_list_tasks_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationTaskGetDetailEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks/{task_id}."""

    async def test_get_task_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test GET returns annotation task detail (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{test_annotation_task.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(test_annotation_task.id)
        assert data["annotation_project_id"] == str(test_annotation_project.id)
        assert data["clip_id"] == str(test_annotation_task.clip_id)
        assert data["status"] == "pending"
        assert "clip" in data
        assert "annotation_project" in data
        assert "created_at" in data
        assert "updated_at" in data

    async def test_get_task_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET returns 404 for non-existent task."""
        fake_id = "00000000-0000-0000-0000-000000000000"

        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_get_task_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{test_annotation_task.id}",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationTaskUpdateEndpoint:
    """Test PATCH /api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks/{task_id}."""

    async def test_update_task_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test PATCH updates annotation task (200)."""
        update_payload = {
            "status": "in_progress",
            "priority": 5,
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{test_annotation_task.id}",
            headers=auth_headers,
            json=update_payload,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(test_annotation_task.id)
        assert data["status"] == "in_progress"
        assert data["priority"] == 5

    async def test_update_task_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test PATCH requires authentication."""
        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{test_annotation_task.id}",
            json={"status": "in_progress"},
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationTaskCompleteEndpoint:
    """Test POST /api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks/{task_id}/complete."""

    async def test_complete_task_success(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test POST marks task as completed (200)."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{test_annotation_task.id}/complete",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "completed_task_id" in data
        assert data["completed_task_id"] == str(test_annotation_task.id)
        assert "next_task" in data
        # No other tasks in this project so next_task should be None
        assert data["next_task"] is None

    async def test_complete_task_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test POST requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/{test_annotation_task.id}/complete",
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestAnnotationTaskNextEndpoint:
    """Test GET /api/v1/projects/{project_id}/annotation-projects/{ap_id}/tasks/next."""

    async def test_get_next_task_no_tasks(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET returns 204 when no tasks are available."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/next",
            headers=auth_headers,
        )

        assert response.status_code == 204

    async def test_get_next_task_with_pending_task(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_project: AnnotationProject,
        test_annotation_task: AnnotationTask,
    ) -> None:
        """Test GET returns the next pending task (200)."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/next",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(test_annotation_task.id)
        assert data["status"] == "pending"

    async def test_get_next_task_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_project: AnnotationProject,
    ) -> None:
        """Test GET requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/annotation-projects/{test_annotation_project.id}/tasks/next",
        )

        assert response.status_code == 401
