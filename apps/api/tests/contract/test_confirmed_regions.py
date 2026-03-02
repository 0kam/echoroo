"""Contract tests for confirmed region endpoints.

Tests verify that endpoints conform to the OpenAPI specification for
Feature 003: Detection Review.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility, DatetimeParseStatus
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.user import User


@pytest.fixture
async def test_dataset(db_session: AsyncSession, test_project: Project) -> Dataset:
    """Create a test dataset.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        name="Test Dataset",
        audio_dir="/data/audio",
        status=DatasetStatus.COMPLETED,
        visibility=DatasetVisibility.PRIVATE,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def test_recording(db_session: AsyncSession, test_dataset: Dataset) -> Recording:
    """Create a test recording.

    Args:
        db_session: Database session
        test_dataset: Parent dataset

    Returns:
        Test recording instance
    """
    recording = Recording(
        dataset_id=test_dataset.id,
        filename="confirmed_test.wav",
        path="confirmed_test.wav",
        hash="def456",
        duration=120.0,
        samplerate=44100,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


@pytest.fixture
async def test_confirmed_region(
    db_session: AsyncSession,
    test_recording: Recording,
    test_user: User,
) -> ConfirmedRegion:
    """Create a test confirmed region.

    Args:
        db_session: Database session
        test_recording: Source recording
        test_user: Reviewer user

    Returns:
        Test confirmed region instance
    """
    region = ConfirmedRegion(
        recording_id=test_recording.id,
        start_time=5.0,
        end_time=10.0,
        reviewed_by_id=test_user.id,
    )
    db_session.add(region)
    await db_session.commit()
    await db_session.refresh(region)
    return region


@pytest.fixture
def test_region_id(test_confirmed_region: ConfirmedRegion) -> str:
    """Get test confirmed region ID.

    Args:
        test_confirmed_region: Test confirmed region

    Returns:
        ConfirmedRegion UUID as string
    """
    return str(test_confirmed_region.id)


@pytest.fixture
def test_recording_id(test_recording: Recording) -> str:
    """Get test recording ID.

    Args:
        test_recording: Test recording

    Returns:
        Recording UUID as string
    """
    return str(test_recording.id)


@pytest.mark.asyncio
class TestConfirmedRegionListEndpoints:
    """Test confirmed region listing endpoints."""

    async def test_list_confirmed_regions_no_recording(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/confirmed-regions - no recording_id returns empty."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/confirmed-regions",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_confirmed_regions_by_recording(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_id: str,
        test_confirmed_region: ConfirmedRegion,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/confirmed-regions with recording_id."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/confirmed-regions",
            headers=auth_headers,
            params={"recording_id": test_recording_id},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        item = data["items"][0]
        assert "id" in item
        assert "recording_id" in item
        assert "start_time" in item
        assert "end_time" in item
        assert "reviewed_by_id" in item

    async def test_list_confirmed_regions_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/confirmed-regions requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/confirmed-regions"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestConfirmedRegionCRUDEndpoints:
    """Test confirmed region create and delete endpoints."""

    async def test_create_confirmed_region(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/confirmed-regions - create region."""
        region_data = {
            "recording_id": test_recording_id,
            "start_time": 15.0,
            "end_time": 20.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/confirmed-regions",
            headers=auth_headers,
            json=region_data,
        )

        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["recording_id"] == test_recording_id
        assert data["start_time"] == 15.0
        assert data["end_time"] == 20.0
        assert "reviewed_by_id" in data
        assert "created_at" in data

    async def test_create_confirmed_region_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/confirmed-regions requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/confirmed-regions",
            json={"recording_id": test_recording_id, "start_time": 0.0, "end_time": 5.0},
        )

        assert response.status_code == 401

    async def test_delete_confirmed_region(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/confirmed-regions/{region_id}."""
        # Create a region to delete
        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/confirmed-regions",
            headers=auth_headers,
            json={"recording_id": test_recording_id, "start_time": 30.0, "end_time": 35.0},
        )
        assert create_response.status_code == 201
        region_id = create_response.json()["id"]

        # Delete it
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/confirmed-regions/{region_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

    async def test_delete_confirmed_region_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/confirmed-regions/{region_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/confirmed-regions/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_confirmed_region_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_region_id: str,
    ) -> None:
        """Test DELETE requires authentication."""
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/confirmed-regions/{test_region_id}"
        )

        assert response.status_code == 401
