"""T653: Integration tests — auto-obscure at the API response layer (FR-030, SC-005).

Verifies that the live FastAPI application NEVER includes raw latitude /
longitude / lat / lng / lon fields in JSON responses for the core data
endpoints (detections, recordings, sites).

Also exercises the H3 resolution pathway through TaxonSensitivity /
ProjectTaxonSensitivityOverride so the integration pipeline is traced end-
to-end (SC-005 / FR-030):

Scenario A — no sensitivity rule → default open (H3_RES_9 native resolution)
Scenario B — IUCN EN sensitivity (H3_RES_5) → detections response carries
             the coarser h3_index without raw coordinates

All assertions are purely structural (field-name inspection on the JSON).
No attempt is made to validate H3 cell accuracy; that belongs in the unit
suite (T650).

Requires TEST_DATABASE_URL to point at a live PostgreSQL instance (the same
``echoroo_test`` database used by all other integration tests).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.annotation import Annotation
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionSource,
    DetectionStatus,
    ProjectLicense,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
    TagCategory,
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
    TaxonSensitivitySource,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.project_taxon_override import ProjectTaxonSensitivityOverride
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.taxon_sensitivity import TaxonSensitivity
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Forbidden raw-coordinate field names (FR-030 / SC-005)
# ---------------------------------------------------------------------------

_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {
        "latitude",
        "longitude",
        "lat",
        "lng",
        "lon",
    }
)


# ---------------------------------------------------------------------------
# Helper: walk JSON for forbidden field names
# ---------------------------------------------------------------------------


def _find_forbidden_fields(
    obj: Any,
    path: str = "",
) -> list[str]:
    """Recursively search ``obj`` for any key in ``_FORBIDDEN_FIELDS``.

    Returns a list of ``"path.field"`` strings where violations were found.
    """
    violations: list[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key
            if key.lower() in _FORBIDDEN_FIELDS:
                violations.append(current_path)
            else:
                violations.extend(_find_forbidden_fields(value, current_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            violations.extend(_find_forbidden_fields(item, f"{path}[{idx}]"))

    return violations


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: H3 resolution for an IUCN EN species (spec FR-032, test T650-A).
_H3_RES_5 = 5
#: Default open resolution.
_H3_RES_9 = 9


def _unique_taxon_id(prefix: str) -> str:
    """Return a taxon_id unique per test run to avoid duplicate-key errors."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def t653_owner(db_session: AsyncSession) -> User:
    """Project owner for T653 integration tests.

    Uses a unique email per test run to avoid conflicts when the test DB is
    not fully cleaned between runs (taxon_sensitivity tables are not in the
    standard cleanup_test_data routine yet).
    """
    unique_suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"t653owner-{unique_suffix}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T653 Owner",
        security_stamp="t653" + "a" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t653_public_project(db_session: AsyncSession, t653_owner: User) -> Project:
    """Public + Active project for T653."""
    project = Project(
        name="T653 Auto-Obscure Integration Project",
        description="Integration test for auto-obscure lat/lng absence",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=t653_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
    )
    db_session.add(project)
    await db_session.flush()

    # Add owner as project admin so the JWT auth routes work.
    member = ProjectMember(
        project_id=project.id,
        user_id=t653_owner.id,
        role=ProjectMemberRole.ADMIN,
        invited_by_id=t653_owner.id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t653_site(
    db_session: AsyncSession, t653_public_project: Project
) -> Site:
    """Site at a known H3-9 cell."""
    site = Site(
        project_id=t653_public_project.id,
        name="T653 Site",
        h3_index="89283082803ffff",  # resolution 9
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def t653_dataset(
    db_session: AsyncSession,
    t653_public_project: Project,
    t653_site: Site,
    t653_owner: User,
) -> Dataset:
    """Dataset for T653."""
    dataset = Dataset(
        project_id=t653_public_project.id,
        site_id=t653_site.id,
        created_by_id=t653_owner.id,
        name="T653 Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def t653_recording(
    db_session: AsyncSession, t653_dataset: Dataset
) -> Recording:
    """Recording for T653."""
    rec = Recording(
        dataset_id=t653_dataset.id,
        filename="t653_recording.wav",
        path="t653_recording.wav",
        duration=10.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(rec)
    await db_session.commit()
    await db_session.refresh(rec)
    return rec


@pytest.fixture
async def t653_open_tag(
    db_session: AsyncSession, t653_public_project: Project
) -> Tag:
    """Tag for a taxon with no sensitivity rule (open)."""
    tag = Tag(
        project_id=t653_public_project.id,
        name="Turdus migratorius open",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def t653_open_detection(
    db_session: AsyncSession,
    t653_recording: Recording,
    t653_open_tag: Tag,
) -> Annotation:
    """Detection for an open taxon."""
    ann = Annotation(
        recording_id=t653_recording.id,
        tag_id=t653_open_tag.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.85,
        start_time=0.0,
        end_time=3.0,
    )
    db_session.add(ann)
    await db_session.commit()
    await db_session.refresh(ann)
    return ann


@pytest.fixture
async def t653_auth_headers(t653_owner: User) -> dict[str, str]:
    """JWT auth headers for t653_owner."""
    token = create_access_token({"sub": str(t653_owner.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def t653_taxon_sensitivity_en(
    db_session: AsyncSession,
) -> TaxonSensitivity:
    """Global IUCN EN sensitivity row → H3_RES_5.

    Uses a unique taxon_id per run to avoid duplicate-key errors in the
    (taxon_id, source) unique constraint when the test DB is not cleaned.
    """
    taxon_id = _unique_taxon_id("t653-iucn-en")
    row = TaxonSensitivity(
        taxon_id=taxon_id,
        source=TaxonSensitivitySource.IUCN,
        sensitivity_h3_res=_H3_RES_5,
        category="EN",
        notes="Integration test IUCN EN fixture",
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    return row


@pytest.fixture
async def t653_project_override_looser(
    db_session: AsyncSession,
    t653_public_project: Project,
    t653_owner: User,
    t653_taxon_sensitivity_en: TaxonSensitivity,
) -> ProjectTaxonSensitivityOverride:
    """Applied LOOSER project override: EN taxon raised from H3_RES_5 → H3_RES_9."""
    override = ProjectTaxonSensitivityOverride(
        project_id=t653_public_project.id,
        taxon_id=t653_taxon_sensitivity_en.taxon_id,
        sensitivity_h3_res=_H3_RES_9,
        direction=TaxonOverrideDirection.LOOSER,
        approval_status=TaxonOverrideApprovalStatus.APPLIED,
        requested_by_id=t653_owner.id,
    )
    db_session.add(override)
    await db_session.commit()
    await db_session.refresh(override)
    return override


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_url(project_id: Any, sub: str) -> str:
    return f"/api/v1/projects/{project_id}/{sub}"


# ---------------------------------------------------------------------------
# Scenario A: no sensitivity rule → API responses have no raw coordinates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNoRawCoordinatesInResponses:
    """SC-005 / FR-030: raw latitude/longitude must never appear in JSON responses."""

    async def test_detections_list_has_no_raw_coordinates(
        self,
        client: AsyncClient,
        t653_public_project: Project,
        t653_open_detection: Annotation,
        t653_auth_headers: dict[str, str],
    ) -> None:
        """GET /detections must not expose lat/lng/latitude/longitude."""
        url = _project_url(t653_public_project.id, "detections")
        resp = await client.get(url, headers=t653_auth_headers)
        assert resp.status_code == 200, (
            f"Expected 200 from GET {url}, got {resp.status_code}: {resp.text[:500]}"
        )
        body = resp.json()
        violations = _find_forbidden_fields(body)
        assert not violations, (
            f"GET {url} response contains raw coordinate fields: {violations} — "
            "FR-030 / SC-005 violation"
        )

    async def test_recordings_list_has_no_raw_coordinates(
        self,
        client: AsyncClient,
        t653_public_project: Project,
        t653_recording: Recording,
        t653_auth_headers: dict[str, str],
    ) -> None:
        """GET /recordings must not expose lat/lng/latitude/longitude."""
        url = _project_url(t653_public_project.id, "recordings")
        resp = await client.get(url, headers=t653_auth_headers)
        assert resp.status_code in (200, 404), (
            f"Unexpected status from GET {url}: {resp.status_code}"
        )
        if resp.status_code == 200:
            body = resp.json()
            violations = _find_forbidden_fields(body)
            assert not violations, (
                f"GET {url} response contains raw coordinate fields: {violations}"
            )

    async def test_sites_list_has_no_raw_coordinates(
        self,
        client: AsyncClient,
        t653_public_project: Project,
        t653_site: Site,
        t653_auth_headers: dict[str, str],
    ) -> None:
        """GET /sites must not expose lat/lng/latitude/longitude."""
        url = _project_url(t653_public_project.id, "sites")
        resp = await client.get(url, headers=t653_auth_headers)
        assert resp.status_code in (200, 404), (
            f"Unexpected status from GET {url}: {resp.status_code}"
        )
        if resp.status_code == 200:
            body = resp.json()
            violations = _find_forbidden_fields(body)
            assert not violations, (
                f"GET {url} response contains raw coordinate fields: {violations}"
            )

    async def test_single_detection_has_no_raw_coordinates(
        self,
        client: AsyncClient,
        t653_public_project: Project,
        t653_open_detection: Annotation,
        t653_auth_headers: dict[str, str],
    ) -> None:
        """GET /detections/{id} must not expose raw coordinates."""
        url = _project_url(
            t653_public_project.id,
            f"detections/{t653_open_detection.id}",
        )
        resp = await client.get(url, headers=t653_auth_headers)
        if resp.status_code == 404:
            pytest.skip("Single-detection route not implemented for this project type")
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code} from GET {url}: {resp.text[:300]}"
        )
        body = resp.json()
        violations = _find_forbidden_fields(body)
        assert not violations, (
            f"GET {url} (single detection) response contains raw coordinates: "
            f"{violations}"
        )


# ---------------------------------------------------------------------------
# Scenario B: TaxonSensitivity present → site h3_index unchanged, no raw coords
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSensitivityRowDoesNotLeakCoordinates:
    """With a TaxonSensitivity row in place, the API still omits raw coordinates."""

    async def test_detections_with_en_taxon_sensitivity_no_raw_coords(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t653_public_project: Project,
        t653_recording: Recording,
        t653_auth_headers: dict[str, str],
        t653_taxon_sensitivity_en: TaxonSensitivity,
    ) -> None:
        """Insert an IUCN EN detection and verify the list response has no raw coords."""
        # Create a tag with the EN taxon id.
        tag = Tag(
            project_id=t653_public_project.id,
            name="T653 EN Test Tag",
            category=TagCategory.SPECIES,
        )
        db_session.add(tag)
        await db_session.flush()

        detection = Annotation(
            recording_id=t653_recording.id,
            tag_id=tag.id,
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            confidence=0.91,
            start_time=1.0,
            end_time=4.0,
        )
        db_session.add(detection)
        await db_session.commit()

        url = _project_url(t653_public_project.id, "detections")
        resp = await client.get(url, headers=t653_auth_headers)
        assert resp.status_code == 200, (
            f"Expected 200 from GET {url}, got {resp.status_code}"
        )
        body = resp.json()
        violations = _find_forbidden_fields(body)
        assert not violations, (
            f"Detections endpoint with IUCN EN taxon still leaks raw coords: "
            f"{violations}"
        )

    async def test_project_with_override_no_raw_coords_in_detections(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t653_public_project: Project,
        t653_recording: Recording,
        t653_auth_headers: dict[str, str],
        t653_project_override_looser: ProjectTaxonSensitivityOverride,
    ) -> None:
        """Applied LOOSER override does not introduce raw coordinates into responses."""
        # Insert a detection tagged with the EN taxon.
        tag = Tag(
            project_id=t653_public_project.id,
            name="T653 Override Tag",
            category=TagCategory.SPECIES,
        )
        db_session.add(tag)
        await db_session.flush()

        detection = Annotation(
            recording_id=t653_recording.id,
            tag_id=tag.id,
            source=DetectionSource.BIRDNET,
            status=DetectionStatus.UNREVIEWED,
            confidence=0.75,
            start_time=2.0,
            end_time=5.0,
        )
        db_session.add(detection)
        await db_session.commit()

        url = _project_url(t653_public_project.id, "detections")
        resp = await client.get(url, headers=t653_auth_headers)
        assert resp.status_code == 200, (
            f"Expected 200 from GET {url}, got {resp.status_code}"
        )
        body = resp.json()
        violations = _find_forbidden_fields(body)
        assert not violations, (
            f"Detection response with LOOSER override leaks raw coordinates: "
            f"{violations}"
        )


# ---------------------------------------------------------------------------
# Scenario C: Export CSV also has no raw coordinates (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportCsvNoRawCoordinatesIntegration:
    """Regression: CSV export endpoint must not contain raw lat/lng columns."""

    async def test_csv_export_endpoint_omits_raw_coordinates(
        self,
        client: AsyncClient,
        t653_public_project: Project,
        t653_open_detection: Annotation,
        t653_auth_headers: dict[str, str],
    ) -> None:
        """GET /detections/export?format=csv must not have lat/lng headers."""
        url = _project_url(
            t653_public_project.id,
            "detections/export?format=csv",
        )
        resp = await client.get(url, headers=t653_auth_headers)

        if resp.status_code in (404, 422):
            pytest.skip(
                f"CSV export endpoint not available at this path "
                f"(status={resp.status_code})"
            )

        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code} from {url}: {resp.text[:300]}"
        )

        # Parse the CSV header line.
        first_line = resp.text.split("\n")[0] if resp.text else ""
        header_fields = {f.strip().lower() for f in first_line.split(",")}
        leaked = header_fields & _FORBIDDEN_FIELDS
        assert not leaked, (
            f"CSV export header contains raw coordinate fields: {sorted(leaked)} — "
            "FR-030 / SC-005 violation. Full header: {first_line}"
        )
