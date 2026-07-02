"""Contract tests for detection run endpoints.

Tests verify that endpoints conform to the OpenAPI specification for
Feature 003: Detection Review.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DatasetStatus, DatasetVisibility, DetectionRunStatus
from echoroo.models.project import Project
from echoroo.models.site import Site


@pytest.fixture
async def test_site_for_runs(
    db_session: AsyncSession, test_project: Project
) -> Site:
    """Local Site fixture for detection-run create tests."""
    site = Site(
        project_id=test_project.id,
        name="Detection Run Test Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset_for_runs(
    db_session: AsyncSession,
    test_project: Project,
    test_site_for_runs: Site,
) -> Dataset:
    """Local Dataset fixture for detection-run create tests.

    Phase 16 Batch 6e (2026-04-29) downstream drift fix: the
    :class:`DetectionRunCreate` schema now requires ``dataset_id``
    (Phase 11 / FR-007). Add a minimal Dataset row owned by the
    test project so the contract create test can populate the
    field. ``site_id`` is NOT NULL on the ``datasets`` table so we
    reuse the shared ``test_site`` fixture.
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=test_site_for_runs.id,
        created_by_id=test_project.owner_id,
        name="Detection Run Test Dataset",
        status=DatasetStatus.COMPLETED,
        visibility=DatasetVisibility.PRIVATE,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def test_detection_run(db_session: AsyncSession, test_project: Project) -> DetectionRun:
    """Create a test detection run.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Test detection run instance
    """
    run = DetectionRun(
        project_id=test_project.id,
        model_name="BirdNET-Analyzer",
        model_version="2.4",
        parameters={"min_confidence": 0.5},
        status=DetectionRunStatus.COMPLETED,
        annotation_count=42,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.fixture
def test_run_id(test_detection_run: DetectionRun) -> str:
    """Get test detection run ID.

    Args:
        test_detection_run: Test detection run

    Returns:
        DetectionRun UUID as string
    """
    return str(test_detection_run.id)


@pytest.mark.asyncio
class TestDetectionRunListEndpoints:
    """Test detection run listing endpoints."""

    async def test_list_detection_runs_empty(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/detection-runs - empty list.

        W2-3 PR-14: the legacy ``/api/v1`` list route was unmounted; the surviving
        provider is the ``/web-api/v1`` BFF (session-bound Bearer + CSRF header).
        """
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "pages" in data
        assert isinstance(data["items"], list)

    async def test_list_detection_runs_with_data(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_detection_run: DetectionRun,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/detection-runs - returns runs."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            headers=csrf_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        item = data["items"][0]
        assert "id" in item
        assert "model_name" in item
        assert "model_version" in item
        assert "status" in item
        assert "annotation_count" in item

    async def test_list_detection_runs_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /web-api/v1/projects/{project_id}/detection-runs requires authentication."""
        response = await client.get(
            f"/web-api/v1/projects/{test_project_id}/detection-runs"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDetectionRunCRUDEndpoints:
    """Test detection run create, read, update endpoints."""

    async def test_create_detection_run(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset_for_runs: Dataset,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/detection-runs - create run.

        W2-3 PR-14: the legacy ``/api/v1`` create route was unmounted; the surviving
        provider is the ``/web-api/v1`` BFF (session-bound Bearer + CSRF header).

        Phase 16 Batch 6e (2026-04-29) downstream drift fix: the schema
        ``DetectionRunCreate`` now requires ``dataset_id``.
        """
        # Phase 16 Batch 6e (2026-04-29) downstream drift fix: the live
        # endpoint validates ``model_name`` against the registry of
        # available models (``["birdnet", "perch"]``) and 400s on
        # ``"BirdNET-Analyzer"``. Use the canonical lowercase id.
        run_data = {
            "dataset_id": str(test_dataset_for_runs.id),
            "model_name": "birdnet",
            "model_version": "2.4",
            "parameters": {"min_confidence": 0.5, "overlap": 0.0},
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            headers=csrf_headers,
            json=run_data,
        )

        assert response.status_code == 201, response.text
        data = response.json()

        assert "id" in data
        assert data["project_id"] == test_project_id
        assert data["model_name"] == run_data["model_name"]
        assert data["model_version"] == run_data["model_version"]
        assert data["status"] == "pending"
        assert data["annotation_count"] == 0
        assert "created_at" in data

    async def test_get_detection_run(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_run_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detection-runs/{run_id}."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detection-runs/{test_run_id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == test_run_id
        assert "model_name" in data
        assert "status" in data
        assert "annotation_count" in data

    async def test_get_detection_run_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detection-runs/{run_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detection-runs/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_update_detection_run_status(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_run_id: str,
    ) -> None:
        """Test PATCH /api/v1/projects/{project_id}/detection-runs/{run_id}."""
        update_data = {
            "status": "running",
            "annotation_count": 10,
        }

        response = await client.patch(
            f"/api/v1/projects/{test_project_id}/detection-runs/{test_run_id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "running"
        assert data["annotation_count"] == 10

    async def test_create_detection_run_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test POST /web-api/v1/projects/{project_id}/detection-runs requires authentication."""
        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            json={"model_name": "BirdNET", "model_version": "2.4"},
        )

        assert response.status_code == 401
