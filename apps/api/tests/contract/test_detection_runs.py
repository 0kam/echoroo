"""Contract tests for detection run endpoints.

Tests verify that endpoints conform to the OpenAPI specification for
Feature 003: Detection Review.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionRunStatus,
    DetectionRunType,
)
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
def stub_celery_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the Celery ``.delay`` dispatch so create tests need no live broker.

    The create path commits the ``DetectionRun`` (including its ``run_type``)
    and only then enqueues a Celery task. The enqueue requires a reachable
    broker, which is unavailable outside the docker network. Replacing the two
    task ``.delay`` methods with no-op stubs keeps the create contract
    (status/response shape, run_type mapping) deterministic in every
    environment without exercising the ML worker.
    """
    from unittest.mock import MagicMock

    from echoroo.workers import ml_tasks

    monkeypatch.setattr(ml_tasks.run_detection, "delay", MagicMock())
    monkeypatch.setattr(ml_tasks.run_embedding_generation, "delay", MagicMock())


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
        # W1-4: run_type is a first-class field on the response. The default
        # fixture run has no embedding flag / custom model, so it is a detection.
        assert item["run_type"] == DetectionRunType.DETECTION.value

    async def test_list_detection_runs_filter_by_run_type(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        db_session: AsyncSession,
        test_project: Project,
        test_project_id: str,
        test_detection_run: DetectionRun,
    ) -> None:
        """W1-4: ``?run_type=embedding`` narrows both items and total server-side."""
        # test_detection_run is a DETECTION run; add one EMBEDDING run.
        embedding_run = DetectionRun(
            project_id=test_project.id,
            model_name="perch",
            model_version="2.0",
            parameters={"embedding_only": True},
            run_type=DetectionRunType.EMBEDDING,
            status=DetectionRunStatus.COMPLETED,
            annotation_count=0,
        )
        db_session.add(embedding_run)
        await db_session.commit()

        # Unfiltered: both runs are visible.
        all_resp = await client.get(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            headers=csrf_headers,
        )
        assert all_resp.status_code == 200
        assert all_resp.json()["total"] >= 2

        # Filtered to embedding: only the embedding run, and total is scoped.
        resp = await client.get(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            headers=csrf_headers,
            params={"run_type": DetectionRunType.EMBEDDING.value},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["run_type"] == DetectionRunType.EMBEDDING.value

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
        stub_celery_dispatch: None,
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
        # W1-4: a plain create (no embedding_only flag) is a detection run.
        assert data["run_type"] == DetectionRunType.DETECTION.value

    async def test_create_embedding_only_maps_to_embedding_run_type(
        self,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        test_project_id: str,
        test_dataset_for_runs: Dataset,
        stub_celery_dispatch: None,
    ) -> None:
        """W1-4: the back-compat ``embedding_only`` flag maps to run_type=embedding."""
        run_data = {
            "dataset_id": str(test_dataset_for_runs.id),
            "model_name": "perch",
            "model_version": "2.0",
            "embedding_only": True,
        }

        response = await client.post(
            f"/web-api/v1/projects/{test_project_id}/detection-runs",
            headers=csrf_headers,
            json=run_data,
        )

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["run_type"] == DetectionRunType.EMBEDDING.value
        # The legacy parameters flag is still persisted for back-compat.
        assert data["parameters"] == {"embedding_only": True}

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


# W1-4: the test database is built from ``create_all`` (not by replaying
# Alembic), so the migration's UPDATE cannot be run against it directly. This
# DB-backed test instead executes the migration's exact backfill CASE
# expression as a SELECT over seeded rows, locking the classification SQL for
# all four branches (and their priority ordering).
_BACKFILL_CASE_SQL = text(
    """
    SELECT CASE
        WHEN parameters->>'embedding_only' = 'true' THEN 'embedding'
        WHEN model_name = 'custom_svm' THEN 'custom'
        WHEN model_name = 'perch' AND annotation_count = 0 THEN 'embedding'
        ELSE 'detection'
    END AS derived
    FROM detection_runs
    WHERE id = :run_id
    """
)


@pytest.mark.asyncio
class TestRunTypeBackfillClassification:
    """Exercise the migration 0032 backfill CASE expression against real rows."""

    @pytest.mark.parametrize(
        ("model_name", "parameters", "annotation_count", "expected"),
        [
            # Priority 1: embedding_only flag wins over model_name.
            ("perch", {"embedding_only": True}, 5, "embedding"),
            ("custom_svm", {"embedding_only": True}, 0, "embedding"),
            # Priority 2: custom_svm (no flag) -> custom, even at 0 annotations.
            ("custom_svm", {"threshold": 0.5}, 0, "custom"),
            # Priority 3: legacy Perch embedding rows predating the flag.
            ("perch", None, 0, "embedding"),
            # else: birdnet, and perch runs that produced annotations.
            ("birdnet", {"min_confidence": 0.5}, 10, "detection"),
            ("perch", None, 7, "detection"),
        ],
    )
    async def test_backfill_case_classifies_row(
        self,
        db_session: AsyncSession,
        test_project: Project,
        model_name: str,
        parameters: dict[str, object] | None,
        annotation_count: int,
        expected: str,
    ) -> None:
        run = DetectionRun(
            project_id=test_project.id,
            model_name=model_name,
            model_version="1.0",
            parameters=parameters,
            status=DetectionRunStatus.COMPLETED,
            annotation_count=annotation_count,
        )
        db_session.add(run)
        await db_session.commit()
        await db_session.refresh(run)

        result = await db_session.execute(_BACKFILL_CASE_SQL, {"run_id": run.id})
        assert result.scalar_one() == expected
