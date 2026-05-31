"""CSV export raw-coordinate leak guard (T312, FR-086 / FR-028 / SC-016).

Drives :func:`echoroo.services.detection_export.DetectionExportService.export_csv`
end-to-end against an in-memory database so we can assert:

1. **Header columns**

   * NEVER contain raw-coordinate fields (``latitude`` / ``longitude`` /
     ``lat`` / ``lng`` / ``gps_*``) — FR-028 / SC-016.
   * MUST contain the FR-086 disclosure trio:
     ``license`` / ``license_history_url`` / ``location_generalization`` /
     ``withheld_reason``.

2. **Data rows**

   For at least one row in the export:

   * ``location_generalization`` is a positive integer.
   * ``license`` is a non-empty CC-style slug (``CC0`` / ``CC-BY`` / ...).
   * ``license_history_url`` references the canonical
     ``/api/v1/projects/{id}/license-history`` path.
   * ``withheld_reason`` is empty (Public + member-resolution row) or one of
     the ``project_toggle`` / ``taxon_sensitivity:*`` whitelisted values
     (Restricted toggle path).

The test runs the service directly rather than through the HTTP layer so
it can also exercise the Restricted ``public_location_precision_h3_res``
clamp without needing a vote / session fixture.
"""

from __future__ import annotations



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
import pytest_asyncio

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
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation import Annotation
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionSource,
    DetectionStatus,
    ProjectStatus,
    ProjectVisibility,
    TagCategory,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User
from echoroo.services.detection_export import DetectionExportService

# ---------------------------------------------------------------------------
# Forbidden raw-coordinate field names (FR-028 / SC-016).
# ---------------------------------------------------------------------------

_FORBIDDEN_HEADER_NAMES: frozenset[str] = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lng",
        "gps_latitude",
        "gps_longitude",
        "gps",
    }
)

# Required FR-086 trailing columns.
_REQUIRED_FR_086_COLUMNS: tuple[str, ...] = (
    "license",
    "license_history_url",
    "location_generalization",
    "withheld_reason",
)

# Restricted project toggles for the clamped-resolution test row.
_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": True,
    "allow_detection_view": True,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": True,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 5,
    "allow_precise_location_to_viewer": False,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def t312_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t312owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T312 Owner",
        security_stamp="t312" + "a" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def t312_public_project(
    db_session: AsyncSession, t312_owner: User
) -> Project:
    """Public + Active project — license is the canonical CC-BY slug."""
    project = Project(
        name="T312 Public Project",
        description="CSV export raw-coord guard fixture",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=t312_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def t312_restricted_project(
    db_session: AsyncSession, t312_owner: User
) -> Project:
    """Restricted project with public_location_precision_h3_res=5 toggle."""
    project = Project(
        name="T312 Restricted Project",
        description="CSV export with Restricted clamp",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc0",
        owner_id=t312_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_RESTRICTED_CONFIG,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def t312_site_public(
    db_session: AsyncSession, t312_public_project: Project
) -> Site:
    """Public project site at a known H3-9 cell (member-resolution)."""
    site = Site(
        project_id=t312_public_project.id,
        name="T312 Public Site",
        # Resolution-9 H3 index — get_resolution() returns 9 for this string.
        h3_index_member="89283082803ffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest_asyncio.fixture
async def t312_site_restricted(
    db_session: AsyncSession, t312_restricted_project: Project
) -> Site:
    """Restricted project site at H3-9 — clamped down to 5 by toggle."""
    site = Site(
        project_id=t312_restricted_project.id,
        name="T312 Restricted Site",
        h3_index_member="89283082803ffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest_asyncio.fixture
async def t312_dataset_public(
    db_session: AsyncSession,
    t312_public_project: Project,
    t312_site_public: Site,
    t312_owner: User,
) -> Dataset:
    dataset = Dataset(
        project_id=t312_public_project.id,
        site_id=t312_site_public.id,
        created_by_id=t312_owner.id,
        name="T312 Public Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest_asyncio.fixture
async def t312_dataset_restricted(
    db_session: AsyncSession,
    t312_restricted_project: Project,
    t312_site_restricted: Site,
    t312_owner: User,
) -> Dataset:
    dataset = Dataset(
        project_id=t312_restricted_project.id,
        site_id=t312_site_restricted.id,
        created_by_id=t312_owner.id,
        name="T312 Restricted Dataset",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest_asyncio.fixture
async def t312_recording_public(
    db_session: AsyncSession, t312_dataset_public: Dataset
) -> Recording:
    rec = Recording(
        dataset_id=t312_dataset_public.id,
        filename="t312_pub.wav",
        path="t312_pub.wav",
        duration=10.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(rec)
    await db_session.commit()
    await db_session.refresh(rec)
    return rec


@pytest_asyncio.fixture
async def t312_recording_restricted(
    db_session: AsyncSession, t312_dataset_restricted: Dataset
) -> Recording:
    rec = Recording(
        dataset_id=t312_dataset_restricted.id,
        filename="t312_restricted.wav",
        path="t312_restricted.wav",
        duration=10.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(rec)
    await db_session.commit()
    await db_session.refresh(rec)
    return rec


@pytest_asyncio.fixture
async def t312_tag_public(
    db_session: AsyncSession, t312_public_project: Project
) -> Tag:
    tag = Tag(
        project_id=t312_public_project.id,
        name="Cyanocitta cristata",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest_asyncio.fixture
async def t312_tag_restricted(
    db_session: AsyncSession, t312_restricted_project: Project
) -> Tag:
    tag = Tag(
        project_id=t312_restricted_project.id,
        name="Turdus migratorius",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest_asyncio.fixture
async def t312_annotation_public(
    db_session: AsyncSession,
    t312_recording_public: Recording,
    t312_tag_public: Tag,
) -> Annotation:
    ann = Annotation(
        recording_id=t312_recording_public.id,
        tag_id=t312_tag_public.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.91,
        start_time=1.0,
        end_time=4.0,
    )
    db_session.add(ann)
    await db_session.commit()
    await db_session.refresh(ann)
    return ann


@pytest_asyncio.fixture
async def t312_annotation_restricted(
    db_session: AsyncSession,
    t312_recording_restricted: Recording,
    t312_tag_restricted: Tag,
) -> Annotation:
    ann = Annotation(
        recording_id=t312_recording_restricted.id,
        tag_id=t312_tag_restricted.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.77,
        start_time=2.0,
        end_time=5.0,
    )
    db_session.add(ann)
    await db_session.commit()
    await db_session.refresh(ann)
    return ann


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_export(
    db: AsyncSession,
    project_id: UUID,
) -> tuple[list[str], list[dict[str, str]]]:
    """Run the CSV export and return ``(header, rows)`` parsed via csv module."""
    service = DetectionExportService(db)
    csv_text = await service.export_csv(project_id=project_id)
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader)
    body = [
        dict(zip(header, row, strict=True))
        for row in reader
        if any(field.strip() for field in row)
    ]
    return header, body


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportCsvHeaderShape:
    """Header-level guarantees that hold regardless of project visibility."""

    async def test_header_omits_raw_coordinate_columns(
        self,
        db_session: AsyncSession,
        t312_public_project: Project,
        t312_annotation_public: Annotation,
    ) -> None:
        """FR-028 / SC-016: raw lat/lng MUST NOT appear in the CSV header."""
        header, _ = await _run_export(db_session, t312_public_project.id)
        normalised = {col.strip().lower() for col in header}
        leaked = normalised & _FORBIDDEN_HEADER_NAMES
        assert not leaked, (
            f"CSV export leaked raw-coordinate columns: {sorted(leaked)} — "
            f"FR-028 / SC-016 violation. Full header: {header}"
        )

    async def test_header_includes_fr086_columns(
        self,
        db_session: AsyncSession,
        t312_public_project: Project,
        t312_annotation_public: Annotation,
    ) -> None:
        """FR-086: license / location_generalization / withheld_reason etc."""
        header, _ = await _run_export(db_session, t312_public_project.id)
        missing = [col for col in _REQUIRED_FR_086_COLUMNS if col not in header]
        assert not missing, (
            f"CSV export is missing required FR-086 columns {missing}. "
            f"Full header: {header}"
        )


@pytest.mark.asyncio
class TestExportCsvPublicRowValues:
    """Public projects expose the Site's natural H3 resolution."""

    async def test_public_row_has_member_resolution_and_no_withheld_reason(
        self,
        db_session: AsyncSession,
        t312_public_project: Project,
        t312_annotation_public: Annotation,
    ) -> None:
        """``location_generalization`` is positive int, ``withheld_reason`` empty."""
        _, rows = await _run_export(db_session, t312_public_project.id)
        assert rows, "Expected at least one row in the public export"
        row = rows[0]

        # FR-086: location_generalization is the H3 resolution (a positive int).
        assert row["location_generalization"].isdigit(), (
            f"location_generalization must be a positive integer, "
            f"got {row['location_generalization']!r}"
        )
        assert int(row["location_generalization"]) > 0

        # Public + member-resolution → no withholding reason.
        assert row["withheld_reason"] == "", (
            f"Public project export should not set withheld_reason, "
            f"got {row['withheld_reason']!r}"
        )

    async def test_public_row_has_license_and_history_url(
        self,
        db_session: AsyncSession,
        t312_public_project: Project,
        t312_annotation_public: Annotation,
    ) -> None:
        """FR-086 + FR-087: license slug + license-history reference URL."""
        _, rows = await _run_export(db_session, t312_public_project.id)
        assert rows
        row = rows[0]

        # license is the CC slug (e.g. CC-BY).
        assert row["license"].startswith("CC"), (
            f"Expected a CC-style license slug, got {row['license']!r}"
        )
        assert row["license"] == "CC-BY"

        # license_history_url points at the canonical FR-087 endpoint.
        expected_url = f"/api/v1/projects/{t312_public_project.id}/license-history"
        assert row["license_history_url"] == expected_url, (
            f"license_history_url should be {expected_url!r}, "
            f"got {row['license_history_url']!r}"
        )

    async def test_public_row_has_no_raw_coord_fields_in_dict(
        self,
        db_session: AsyncSession,
        t312_public_project: Project,
        t312_annotation_public: Annotation,
    ) -> None:
        """Defence in depth: no row dict key matches a forbidden coord name."""
        _, rows = await _run_export(db_session, t312_public_project.id)
        assert rows
        row_keys = {k.strip().lower() for k in rows[0]}
        leaked = row_keys & _FORBIDDEN_HEADER_NAMES
        assert not leaked, (
            f"Row dict leaked raw-coordinate keys: {sorted(leaked)}"
        )


@pytest.mark.asyncio
class TestExportCsvRestrictedRowValues:
    """Restricted ``public_location_precision_h3_res`` clamp shows up in CSV."""

    async def test_restricted_row_clamps_resolution_and_marks_reason(
        self,
        db_session: AsyncSession,
        t312_restricted_project: Project,
        t312_annotation_restricted: Annotation,
    ) -> None:
        """When toggle res < site res → location_generalization clamped + reason set."""
        _, rows = await _run_export(db_session, t312_restricted_project.id)
        assert rows
        row = rows[0]

        # The Restricted toggle clamps to public_location_precision_h3_res=5.
        assert row["location_generalization"] == "5", (
            f"Expected location_generalization clamp to 5, "
            f"got {row['location_generalization']!r}"
        )
        # The reason MUST be one of the FR-086 whitelisted strings — Phase 6
        # ships ``project_toggle`` for the Restricted toggle path. The
        # ``taxon_sensitivity:*`` reason path lands in Phase 11.
        assert row["withheld_reason"] in {
            "project_toggle",
        } or row["withheld_reason"].startswith("taxon_sensitivity:"), (
            f"withheld_reason must be 'project_toggle' or 'taxon_sensitivity:*'"
            f", got {row['withheld_reason']!r}"
        )

    async def test_restricted_row_has_license_slug_cc0(
        self,
        db_session: AsyncSession,
        t312_restricted_project: Project,
        t312_annotation_restricted: Annotation,
    ) -> None:
        """FR-085: every project has a CC-style license slug emitted."""
        _, rows = await _run_export(db_session, t312_restricted_project.id)
        assert rows
        assert rows[0]["license"] == "CC0"
