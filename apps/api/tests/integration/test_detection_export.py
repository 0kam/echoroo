"""Integration tests for detection export functionality.

Tests verify the actual content and structure of exported data, including:
- CSV column names and data format
- CSV filter behavior by status, tag, and dataset
- ML dataset ZIP archive structure and file contents
- metadata.json schema validation

W2-3 PR-17 (2026-07-02): the two ``/api/v1/.../detections/export/{csv,
ml-dataset}`` routes were unmounted; the request paths below were repointed
to the surviving ``/web-api/v1`` BFF surface for source correctness. This
module stays skip-marked under the Phase 14+ recording_annotations deferral.
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
import csv
import io
import json
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.confirmed_region import ConfirmedRegion
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
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def export_site(db_session: AsyncSession, test_project: Project) -> Site:
    """Create a test site for export tests.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Export Test Site",
        h3_index_member="851fb46ffffffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def export_dataset(
    db_session: AsyncSession,
    test_project: Project,
    export_site: Site,
    test_user: User,
) -> Dataset:
    """Create a test dataset for export tests.

    Args:
        db_session: Database session
        test_project: Parent project
        export_site: Parent site (required by schema)
        test_user: Dataset creator

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=export_site.id,
        created_by_id=test_user.id,
        name="Export Test Dataset",
        audio_dir="/data/export-test",
        status=DatasetStatus.COMPLETED,
        visibility=DatasetVisibility.PRIVATE,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def export_recording(
    db_session: AsyncSession,
    export_dataset: Dataset,
) -> Recording:
    """Create a test recording for export tests.

    Args:
        db_session: Database session
        export_dataset: Parent dataset

    Returns:
        Test recording instance
    """
    recording = Recording(
        dataset_id=export_dataset.id,
        filename="export_recording.wav",
        path="export-test/export_recording.wav",
        hash="export001",
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
async def export_species_tag(
    db_session: AsyncSession,
    test_project: Project,
) -> Tag:
    """Create a species tag for export tests.

    Args:
        db_session: Database session
        test_project: Parent project

    Returns:
        Test tag instance
    """
    tag = Tag(
        project_id=test_project.id,
        name="Erithacus rubecula",
        category=TagCategory.SPECIES,
        scientific_name="Erithacus rubecula",
        common_name="European robin",
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def unreviewed_annotation(
    db_session: AsyncSession,
    export_recording: Recording,
    export_species_tag: Tag,
) -> Annotation:
    """Create an unreviewed detection annotation for export tests.

    Args:
        db_session: Database session
        export_recording: Source recording
        export_species_tag: Species tag

    Returns:
        Unreviewed annotation instance
    """
    annotation = Annotation(
        recording_id=export_recording.id,
        tag_id=export_species_tag.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.75,
        start_time=5.0,
        end_time=8.0,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


@pytest.fixture
async def confirmed_annotation(
    db_session: AsyncSession,
    export_recording: Recording,
    export_species_tag: Tag,
) -> Annotation:
    """Create a confirmed detection annotation for export tests.

    Args:
        db_session: Database session
        export_recording: Source recording
        export_species_tag: Species tag

    Returns:
        Confirmed annotation instance
    """
    annotation = Annotation(
        recording_id=export_recording.id,
        tag_id=export_species_tag.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.CONFIRMED,
        confidence=0.95,
        start_time=15.0,
        end_time=18.0,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


@pytest.fixture
async def rejected_annotation(
    db_session: AsyncSession,
    export_recording: Recording,
    export_species_tag: Tag,
) -> Annotation:
    """Create a rejected detection annotation for export tests.

    Args:
        db_session: Database session
        export_recording: Source recording
        export_species_tag: Species tag

    Returns:
        Rejected annotation instance
    """
    annotation = Annotation(
        recording_id=export_recording.id,
        tag_id=export_species_tag.id,
        source=DetectionSource.HUMAN,
        status=DetectionStatus.REJECTED,
        confidence=None,
        start_time=30.0,
        end_time=33.0,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


@pytest.fixture
async def confirmed_region(
    db_session: AsyncSession,
    export_recording: Recording,
    test_user: User,
) -> ConfirmedRegion:
    """Create a confirmed region (negative example) for ML dataset export tests.

    Args:
        db_session: Database session
        export_recording: Source recording
        test_user: Reviewer user

    Returns:
        ConfirmedRegion instance
    """
    region = ConfirmedRegion(
        recording_id=export_recording.id,
        start_time=50.0,
        end_time=53.0,
        reviewed_by_id=test_user.id,
    )
    db_session.add(region)
    await db_session.commit()
    await db_session.refresh(region)
    return region


# ---------------------------------------------------------------------------
# CSV Export Content Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_export_correct_columns(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
) -> None:
    """Test that CSV export contains all expected columns in the correct order."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)

    expected_columns = [
        "recording_filename",
        "start_time",
        "end_time",
        "species",
        "confidence",
        "source",
        "model_name",
        "model_version",
        "verified",
        "verified_by",
    ]
    assert header == expected_columns


@pytest.mark.asyncio
async def test_csv_export_unreviewed_annotation_data(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    unreviewed_annotation: Annotation,
    export_recording: Recording,
    export_species_tag: Tag,
) -> None:
    """Test that CSV export includes correct data for unreviewed annotations."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    rows = list(reader)

    assert len(rows) >= 1
    row = rows[0]
    col = {name: idx for idx, name in enumerate(header)}

    assert row[col["recording_filename"]] == "export_recording.wav"
    assert row[col["start_time"]] == "5.000"
    assert row[col["end_time"]] == "8.000"
    assert row[col["species"]] == "Erithacus rubecula"
    assert row[col["confidence"]] == "0.7500"
    assert row[col["source"]] == "birdnet"
    # Unreviewed annotations have empty verified field
    assert row[col["verified"]] == ""


@pytest.mark.asyncio
async def test_csv_export_confirmed_annotation_verified_true(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    confirmed_annotation: Annotation,
) -> None:
    """Test that confirmed annotations have verified=true in CSV export."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
        params={"status": "confirmed"},
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    rows = list(reader)

    assert len(rows) >= 1
    col = {name: idx for idx, name in enumerate(header)}
    row = rows[0]

    assert row[col["verified"]] == "true"


@pytest.mark.asyncio
async def test_csv_export_rejected_annotation_verified_false(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    rejected_annotation: Annotation,
) -> None:
    """Test that rejected annotations have verified=false in CSV export."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
        params={"status": "rejected"},
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    rows = list(reader)

    assert len(rows) >= 1
    col = {name: idx for idx, name in enumerate(header)}
    row = rows[0]

    assert row[col["verified"]] == "false"


@pytest.mark.asyncio
async def test_csv_export_filter_by_status_unreviewed(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    unreviewed_annotation: Annotation,
    confirmed_annotation: Annotation,
) -> None:
    """Test CSV export filtered by unreviewed status returns only unreviewed rows."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
        params={"status": "unreviewed"},
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    rows = list(reader)
    col = {name: idx for idx, name in enumerate(header)}

    # All returned rows should have empty verified (unreviewed)
    for row in rows:
        assert row[col["verified"]] == "", f"Expected unreviewed, got verified={row[col['verified']]}"


@pytest.mark.asyncio
async def test_csv_export_filter_by_tag(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    unreviewed_annotation: Annotation,
    export_species_tag: Tag,
) -> None:
    """Test CSV export filtered by tag_id returns only matching annotations."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
        params={"tag_id": str(export_species_tag.id)},
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    rows = list(reader)
    col = {name: idx for idx, name in enumerate(header)}

    assert len(rows) >= 1
    for row in rows:
        assert row[col["species"]] == "Erithacus rubecula"


@pytest.mark.asyncio
async def test_csv_export_filter_by_dataset(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    unreviewed_annotation: Annotation,
    export_dataset: Dataset,
) -> None:
    """Test CSV export filtered by dataset_id returns only annotations from that dataset."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/csv",
        headers=auth_headers,
        params={"dataset_id": str(export_dataset.id)},
    )

    assert response.status_code == 200

    reader = csv.reader(io.StringIO(response.text))
    next(reader)  # skip header
    rows = list(reader)

    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_csv_export_no_annotations_outside_project(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    unreviewed_annotation: Annotation,
) -> None:
    """Test CSV export only returns annotations belonging to the requested project."""
    # Request with a fake project ID - should return empty CSV
    fake_project_id = "00000000-0000-0000-0000-000000000000"
    response = await client.get(
        f"/web-api/v1/projects/{fake_project_id}/detections/export/csv",
        headers=auth_headers,
    )

    # The project does not exist but export still returns 200 with empty data
    # (project ownership is scoped via dataset join, not a 404 guard)
    assert response.status_code == 200
    reader = csv.reader(io.StringIO(response.text))
    next(reader)  # skip header
    rows = list(reader)
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# ML Dataset ZIP Export Content Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ml_dataset_zip_contains_expected_files(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
) -> None:
    """Test that ML dataset ZIP contains annotations.csv, metadata.json, and README.txt."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
        assert "annotations.csv" in names
        assert "metadata.json" in names
        assert "README.txt" in names


@pytest.mark.asyncio
async def test_ml_dataset_metadata_json_schema(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
) -> None:
    """Test that metadata.json in ML dataset ZIP has the correct schema structure."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        metadata_bytes = zf.read("metadata.json")
        metadata = json.loads(metadata_bytes)

    # Verify required fields exist
    assert "project_id" in metadata
    assert "exported_at" in metadata
    assert "total_entries" in metadata
    assert "positive_count" in metadata
    assert "negative_count" in metadata
    assert "species" in metadata

    # Verify types
    assert isinstance(metadata["total_entries"], int)
    assert isinstance(metadata["positive_count"], int)
    assert isinstance(metadata["negative_count"], int)
    assert isinstance(metadata["species"], list)

    # Verify project_id matches
    assert metadata["project_id"] == str(test_project.id)


@pytest.mark.asyncio
async def test_ml_dataset_metadata_counts_empty(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
) -> None:
    """Test that metadata.json reports zero counts when no data exists."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        metadata = json.loads(zf.read("metadata.json"))

    assert metadata["total_entries"] == 0
    assert metadata["positive_count"] == 0
    assert metadata["negative_count"] == 0
    assert metadata["species"] == []


@pytest.mark.asyncio
async def test_ml_dataset_annotations_csv_columns(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
) -> None:
    """Test that annotations.csv in ML dataset ZIP has expected column headers."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        csv_content = zf.read("annotations.csv").decode("utf-8")

    reader = csv.reader(io.StringIO(csv_content))
    header = next(reader)

    expected_columns = [
        "recording_filename",
        "start_time",
        "end_time",
        "species",
        "confidence",
        "label",
    ]
    assert header == expected_columns


@pytest.mark.asyncio
async def test_ml_dataset_positive_entry_from_confirmed_annotation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    confirmed_annotation: Annotation,
    export_species_tag: Tag,
) -> None:
    """Test that confirmed annotations appear as positive entries in ML dataset."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        csv_content = zf.read("annotations.csv").decode("utf-8")
        metadata = json.loads(zf.read("metadata.json"))

    reader = csv.reader(io.StringIO(csv_content))
    header = next(reader)
    rows = list(reader)
    col = {name: idx for idx, name in enumerate(header)}

    # At least one positive entry should exist
    positive_rows = [r for r in rows if r[col["label"]] == "positive"]
    assert len(positive_rows) >= 1

    row = positive_rows[0]
    assert row[col["recording_filename"]] == "export_recording.wav"
    assert row[col["species"]] == "Erithacus rubecula"
    assert row[col["label"]] == "positive"

    # Metadata should reflect positive count
    assert metadata["positive_count"] >= 1
    assert "Erithacus rubecula" in metadata["species"]


@pytest.mark.asyncio
async def test_ml_dataset_negative_entry_from_confirmed_region(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    confirmed_region: ConfirmedRegion,
) -> None:
    """Test that confirmed regions without overlapping annotations appear as negative entries."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        csv_content = zf.read("annotations.csv").decode("utf-8")
        metadata = json.loads(zf.read("metadata.json"))

    reader = csv.reader(io.StringIO(csv_content))
    header = next(reader)
    rows = list(reader)
    col = {name: idx for idx, name in enumerate(header)}

    negative_rows = [r for r in rows if r[col["label"]] == "negative"]
    assert len(negative_rows) >= 1

    row = negative_rows[0]
    assert row[col["recording_filename"]] == "export_recording.wav"
    assert row[col["species"]] == ""
    assert row[col["label"]] == "negative"

    assert metadata["negative_count"] >= 1


@pytest.mark.asyncio
async def test_ml_dataset_total_entries_equals_positive_plus_negative(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
    confirmed_annotation: Annotation,
    confirmed_region: ConfirmedRegion,
) -> None:
    """Test that total_entries in metadata equals positive_count + negative_count."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        metadata = json.loads(zf.read("metadata.json"))

    assert metadata["total_entries"] == metadata["positive_count"] + metadata["negative_count"]


@pytest.mark.asyncio
async def test_ml_dataset_readme_is_human_readable(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_project: Project,
) -> None:
    """Test that README.txt in ML dataset ZIP is non-empty and contains key information."""
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/detections/export/ml-dataset",
        headers=auth_headers,
    )

    assert response.status_code == 200

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        readme = zf.read("README.txt").decode("utf-8")

    assert len(readme) > 0
    assert "Echoroo" in readme
    assert "annotations.csv" in readme
    assert "metadata.json" in readme
