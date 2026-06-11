"""Contract tests for detection annotation endpoints.

Tests verify that endpoints conform to the OpenAPI specification for
Feature 003: Detection Review.
"""



# Phase 13 P1.5 R2 (Codex follow-up — Fatal): this suite exercises the
# rich-shape ``Annotation`` ORM (``recording_id`` / ``tag_id`` / ``status``
# / ``confidence`` / ``start_time`` / ``end_time`` / ``freq_low`` /
# ``freq_high`` / ``reviewed_by_id`` / ``reviewed_at`` /
# ``search_session_id`` / ``detection_run_id``). The DB-truth schema only
# carries the minimal detection-based shape (id / detection_id / user_id /
# source / taxon_id / label) — the rich shape is **deferred to Phase 14+**
# when a separate ``recording_annotations`` table will reinstate it. Until
# then the suite below cannot run; reactivate it in Phase 14+ when the
# ``recording_annotations`` ORM + table are wired up.
#
# TODO(Phase 14+ recording_annotations): drop this skip and re-validate.
import pytest as _pytest_phase14_skip  # noqa: E402

pytestmark = _pytest_phase14_skip.mark.skip(
    reason=(
        "Phase 14+ deferred — rich-shape Annotation columns (recording_id /"
        " tag_id / status / start_time / end_time / etc) live on the future"
        " ``recording_annotations`` table; see ``apps/api/echoroo/models/"
        "annotation.py`` and ``apps/api/echoroo/models/recording_annotation.py``"
        " module docstrings."
    ),
)
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    DetectionSource,
    DetectionStatus,
    TagCategory,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation as Annotation
from echoroo.models.tag import Tag


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
        filename="test_recording.wav",
        path="test_recording.wav",
        hash="abc123",
        duration=60.0,
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
async def test_species_tag(db_session: AsyncSession, test_project: Project) -> Tag:
    """Create a test species tag.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Test tag instance
    """
    tag = Tag(
        project_id=test_project.id,
        name="Turdus merula",
        category=TagCategory.SPECIES,
        scientific_name="Turdus merula",
        common_name="Common blackbird",
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def test_annotation(
    db_session: AsyncSession,
    test_recording: Recording,
    test_species_tag: Tag,
) -> Annotation:
    """Create a test detection annotation.

    Args:
        db_session: Database session
        test_recording: Source recording
        test_species_tag: Species tag for the annotation

    Returns:
        Test annotation instance
    """
    annotation = Annotation(
        recording_id=test_recording.id,
        tag_id=test_species_tag.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.85,
        start_time=10.0,
        end_time=13.0,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


@pytest.fixture
def test_annotation_id(test_annotation: Annotation) -> str:
    """Get test annotation ID.

    Args:
        test_annotation: Test annotation

    Returns:
        Annotation UUID as string
    """
    return str(test_annotation.id)


@pytest.fixture
def test_recording_id(test_recording: Recording) -> str:
    """Get test recording ID.

    Args:
        test_recording: Test recording

    Returns:
        Recording UUID as string
    """
    return str(test_recording.id)


@pytest.fixture
def test_species_tag_id(test_species_tag: Tag) -> str:
    """Get test species tag ID.

    Args:
        test_species_tag: Test species tag

    Returns:
        Tag UUID as string
    """
    return str(test_species_tag.id)


@pytest.mark.asyncio
class TestDetectionListEndpoints:
    """Test detection listing endpoints."""

    async def test_list_detections_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections - empty list initially."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
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

    async def test_list_detections_with_annotation(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation: Annotation,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections - returns annotations."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        assert len(data["items"]) >= 1

        item = data["items"][0]
        assert "id" in item
        assert "recording_id" in item
        assert "source" in item
        assert "status" in item
        assert "start_time" in item
        assert "end_time" in item
        assert "confidence" in item

    async def test_list_detections_filter_by_status(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation: Annotation,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections with status filter."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            params={"status": "unreviewed"},
        )

        assert response.status_code == 200
        data = response.json()

        for item in data["items"]:
            assert item["status"] == "unreviewed"

    async def test_list_detections_pagination(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections pagination params."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            params={"page": 1, "page_size": 10},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["page"] == 1
        assert data["page_size"] == 10

    async def test_list_detections_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDetectionSpeciesSummary:
    """Test species summary endpoint."""

    async def test_get_species_summary_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections/species-summary - empty."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/species-summary",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total_species" in data
        assert isinstance(data["items"], list)
        assert data["total_species"] == 0

    async def test_get_species_summary_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation: Annotation,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections/species-summary - with data."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/species-summary",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total_species"] >= 1
        assert len(data["items"]) >= 1

        item = data["items"][0]
        assert "tag_id" in item
        assert "tag_name" in item
        assert "total_count" in item
        assert "unreviewed_count" in item
        assert "confirmed_count" in item
        assert "rejected_count" in item

    async def test_get_species_summary_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections/species-summary requires auth."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/species-summary"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDetectionCRUDEndpoints:
    """Test detection create, read, update, delete endpoints."""

    async def test_create_detection(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_id: str,
        test_species_tag_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/detections - create detection."""
        detection_data = {
            "recording_id": test_recording_id,
            "tag_id": test_species_tag_id,
            "source": "birdnet",
            "confidence": 0.9,
            "start_time": 5.0,
            "end_time": 8.0,
            "freq_low": 2000.0,
            "freq_high": 8000.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            json=detection_data,
        )

        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["recording_id"] == test_recording_id
        assert data["tag_id"] == test_species_tag_id
        assert data["source"] == "birdnet"
        assert data["status"] == "unreviewed"
        assert data["confidence"] == 0.9
        assert data["start_time"] == 5.0
        assert data["end_time"] == 8.0
        assert "created_at" in data
        assert "updated_at" in data

    async def test_create_detection_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_recording_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/detections requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections",
            json={"recording_id": test_recording_id, "source": "birdnet", "start_time": 0.0, "end_time": 3.0},
        )

        assert response.status_code == 401

    async def test_get_detection(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections/{detection_id}."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/{test_annotation_id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == test_annotation_id
        assert "recording_id" in data
        assert "source" in data
        assert "status" in data
        assert "start_time" in data
        assert "end_time" in data

    async def test_get_detection_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /api/v1/projects/{project_id}/detections/{detection_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404

    async def test_delete_detection(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/detections/{detection_id}."""
        # First create a detection
        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            json={"recording_id": test_recording_id, "source": "human", "start_time": 0.0, "end_time": 3.0},
        )
        assert create_response.status_code == 201
        detection_id = create_response.json()["id"]

        # Delete it
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/detections/{detection_id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify deletion
        get_response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/{detection_id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    async def test_delete_detection_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test DELETE /api/v1/projects/{project_id}/detections/{detection_id} - not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.delete(
            f"/api/v1/projects/{test_project_id}/detections/{fake_id}",
            headers=auth_headers,
        )

        assert response.status_code == 404


@pytest.mark.asyncio
class TestDetectionReviewEndpoints:
    """Test detection confirm, reject, and change-species endpoints."""

    async def test_confirm_detection(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/detections/{detection_id}/confirm."""
        confirm_data = {"start_time": 10.0, "end_time": 13.0}

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections/{test_annotation_id}/confirm",
            headers=auth_headers,
            json=confirm_data,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == test_annotation_id
        assert data["status"] == "confirmed"
        assert data["reviewed_by_id"] is not None
        assert data["reviewed_at"] is not None
        assert data["start_time"] == 10.0
        assert data["end_time"] == 13.0

    async def test_reject_detection(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_recording_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/detections/{detection_id}/reject."""
        # Create a fresh annotation to reject
        create_response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections",
            headers=auth_headers,
            json={"recording_id": test_recording_id, "source": "birdnet", "start_time": 20.0, "end_time": 23.0},
        )
        assert create_response.status_code == 201
        detection_id = create_response.json()["id"]

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections/{detection_id}/reject",
            headers=auth_headers,
            json={},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "rejected"
        assert data["reviewed_by_id"] is not None
        assert data["reviewed_at"] is not None

    async def test_change_species(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation_id: str,
        test_species_tag_id: str,
    ) -> None:
        """Test POST /api/v1/projects/{project_id}/detections/{detection_id}/change-species."""
        change_data = {
            "new_tag_id": test_species_tag_id,
            "start_time": 11.0,
            "end_time": 14.0,
        }

        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections/{test_annotation_id}/change-species",
            headers=auth_headers,
            json=change_data,
        )

        assert response.status_code == 200
        data = response.json()

        assert data["tag_id"] == test_species_tag_id
        assert data["start_time"] == 11.0
        assert data["end_time"] == 14.0

    async def test_confirm_detection_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test confirm detection returns 404 when not found."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections/{fake_id}/confirm",
            headers=auth_headers,
            json={"start_time": 0.0, "end_time": 3.0},
        )

        assert response.status_code == 404

    async def test_confirm_detection_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
        test_annotation_id: str,
    ) -> None:
        """Test confirm detection requires authentication."""
        response = await client.post(
            f"/api/v1/projects/{test_project_id}/detections/{test_annotation_id}/confirm",
            json={"start_time": 0.0, "end_time": 3.0},
        )

        assert response.status_code == 401
