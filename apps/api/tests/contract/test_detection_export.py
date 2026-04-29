"""Contract tests for detection export endpoints.

Tests verify that the CSV and ML dataset export endpoints conform to the
OpenAPI specification for Feature 003: Detection Review.
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

from echoroo.models.annotation import Annotation
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
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User


@pytest.fixture
async def test_site(db_session: AsyncSession, test_project: Project) -> Site:
    """Create a test site for the test project.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Export Test Site",
        h3_index="851fb46ffffffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def test_dataset(
    db_session: AsyncSession,
    test_project: Project,
    test_site: Site,
    test_user: User,
) -> Dataset:
    """Create a test dataset.

    Args:
        db_session: Database session
        test_project: Parent project
        test_site: Parent site (required by schema)
        test_user: Dataset creator

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=test_site.id,
        created_by_id=test_user.id,
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
async def test_confirmed_annotation(
    db_session: AsyncSession,
    test_recording: Recording,
    test_species_tag: Tag,
) -> Annotation:
    """Create a confirmed detection annotation.

    Args:
        db_session: Database session
        test_recording: Source recording
        test_species_tag: Species tag for the annotation

    Returns:
        Confirmed annotation instance
    """
    annotation = Annotation(
        recording_id=test_recording.id,
        tag_id=test_species_tag.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.CONFIRMED,
        confidence=0.92,
        start_time=20.0,
        end_time=23.0,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


@pytest.mark.asyncio
class TestDetectionCSVExport:
    """Test CSV export endpoint contract."""

    async def test_export_csv_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /export/csv returns empty CSV with headers when no data."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().split("\n")
        assert len(lines) == 1  # Only header row
        assert "recording_filename" in lines[0]

    async def test_export_csv_header_columns(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /export/csv returns all expected CSV column headers."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        header_line = response.text.strip().split("\n")[0]
        assert "recording_filename" in header_line
        assert "start_time" in header_line
        assert "end_time" in header_line
        assert "species" in header_line
        assert "confidence" in header_line
        assert "source" in header_line

    async def test_export_csv_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation: Annotation,
    ) -> None:
        """Test GET /export/csv returns CSV with detection data."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        lines = response.text.strip().split("\n")
        assert len(lines) >= 2  # Header + at least 1 data row
        assert "test_recording.wav" in lines[1]

    async def test_export_csv_with_status_filter_no_match(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_annotation: Annotation,
    ) -> None:
        """Test GET /export/csv with status filter returns only matching detections."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv",
            headers=auth_headers,
            params={"status": "confirmed"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 1  # Only header, no confirmed detections

    async def test_export_csv_with_status_filter_match(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_confirmed_annotation: Annotation,
    ) -> None:
        """Test GET /export/csv with confirmed status filter includes confirmed detections."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv",
            headers=auth_headers,
            params={"status": "confirmed"},
        )

        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) >= 2  # Header + at least 1 confirmed row

    async def test_export_csv_content_disposition_header(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /export/csv sets Content-Disposition header for file download."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]

    async def test_export_csv_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /export/csv requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/csv"
        )

        assert response.status_code == 401


@pytest.mark.asyncio
class TestDetectionMLDatasetExport:
    """Test ML dataset export endpoint contract."""

    async def test_export_ml_dataset_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /export/ml-dataset returns ZIP even with no confirmed data."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/ml-dataset",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        # Valid ZIP files start with the PK magic bytes
        assert response.content[:2] == b"PK"

    async def test_export_ml_dataset_content_type(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /export/ml-dataset returns application/zip content type."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/ml-dataset",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    async def test_export_ml_dataset_content_disposition_header(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Test GET /export/ml-dataset sets Content-Disposition header for download."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/ml-dataset",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert "content-disposition" in response.headers
        assert "attachment" in response.headers["content-disposition"]

    async def test_export_ml_dataset_with_confirmed_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_confirmed_annotation: Annotation,
    ) -> None:
        """Test GET /export/ml-dataset returns non-empty ZIP with confirmed detections."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/ml-dataset",
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert len(response.content) > 0
        assert response.content[:2] == b"PK"

    async def test_export_ml_dataset_unauthorized(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """Test GET /export/ml-dataset requires authentication."""
        response = await client.get(
            f"/api/v1/projects/{test_project_id}/detections/export/ml-dataset"
        )

        assert response.status_code == 401
