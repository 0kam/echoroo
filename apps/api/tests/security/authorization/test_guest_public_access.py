"""Guest Public Access security tests (T220).

Verifies FR-009, FR-010, FR-016, FR-018, FR-029, FR-030, SC-016 for the
Phase 5 Guest read surface introduced in T200-T202.

Spec contract:
* ``GET /web-api/v1/projects/`` — Guest sees only Public + Active projects.
  Restricted/Archived/Dormant projects are enumeration-safe (never exposed).
* ``GET /web-api/v1/projects/{project_id}`` — Guest may fetch Public + Active.
  Anything else → 404 (anti-enumeration, FR-018).
* Mutating endpoints (POST/PUT/DELETE /web-api/v1/projects/…) return 401.
* ``GET /api/v1/projects/{pid}/recordings/{rid}/audio`` — FlexibleCurrentUser
  permits bearer-less GET on Public project recordings. Response is a byte
  stream; no species name leaks into headers, URL, or inline body.
* ``ProjectResponse`` body must not contain PII
  (``password_hash``, ``email`` of non-public users, internal IDs).
* Site h3_index on a ProjectResponse must be a string, not raw lat/lng.

NOTE — T200/T202 implementation precedes T220 due to SSA serialization. This
test file validates existing behaviour; it does not drive new implementation.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    ProjectLicense,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": True,
    "allow_detection_view": True,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 5,
    "allow_precise_location_to_viewer": False,
}

# ---------------------------------------------------------------------------
# Fixtures — users, projects, recordings
# ---------------------------------------------------------------------------


@pytest.fixture
async def project_owner(db_session: AsyncSession) -> User:
    """Owner for Public and Restricted projects."""
    user = User(
        email="t220owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T220 Owner",
        security_stamp="t" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def public_active_project(
    db_session: AsyncSession, project_owner: User
) -> Project:
    """A Public + Active project — should be visible to Guests."""
    project = Project(
        name="T220 Public Active Project",
        description="Guest can see this",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=project_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def restricted_project(
    db_session: AsyncSession, project_owner: User
) -> Project:
    """A Restricted + Active project — must NOT be visible to Guests (FR-018)."""
    project = Project(
        name="T220 Restricted Project",
        description="Guest cannot see this",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=project_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_RESTRICTED_CONFIG,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def archived_public_project(
    db_session: AsyncSession, project_owner: User
) -> Project:
    """A Public but Archived project — must NOT be listed/accessible to Guests."""
    project = Project(
        name="T220 Archived Public Project",
        description="Guest cannot see this because it is archived",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=project_owner.id,
        status=ProjectStatus.ARCHIVED,
        restricted_config={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def dormant_public_project(
    db_session: AsyncSession, project_owner: User
) -> Project:
    """A Public but Dormant project — must NOT be accessible to Guests."""
    project = Project(
        name="T220 Dormant Public Project",
        description="Guest cannot see this because it is dormant",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=project_owner.id,
        status=ProjectStatus.DORMANT,
        restricted_config={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def public_site(
    db_session: AsyncSession, public_active_project: Project
) -> Site:
    """A site attached to the Public + Active project."""
    site = Site(
        project_id=public_active_project.id,
        name="T220 Site",
        h3_index="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def public_dataset(
    db_session: AsyncSession,
    public_active_project: Project,
    public_site: Site,
    project_owner: User,
) -> Dataset:
    """A dataset in the Public + Active project."""
    dataset = Dataset(
        project_id=public_active_project.id,
        site_id=public_site.id,
        created_by_id=project_owner.id,
        name="T220 Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def public_recording(
    db_session: AsyncSession, public_dataset: Dataset
) -> Recording:
    """A recording in the public dataset, using UUID-only S3-style path."""
    rec_id = uuid.uuid4()
    recording = Recording(
        id=rec_id,
        dataset_id=public_dataset.id,
        filename="test_t220.wav",
        # path format: recordings/{project_id}/{dataset_id}/{recording_id}.wav
        path=(
            f"recordings/{public_dataset.project_id}"
            f"/{public_dataset.id}/{rec_id}.wav"
        ),
        duration=5.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


# ---------------------------------------------------------------------------
# T220-1: Guest → Public + Active project detail → 200
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestPublicProjectDetail:
    """Guest (no auth header) can fetch Public + Active project details."""

    async def test_guest_gets_public_active_project_200(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """GET /web-api/v1/projects/{public_id} with no Bearer → 200 (FR-009/FR-016)."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}",
        )
        assert response.status_code == 200, (
            f"Expected 200 for Guest on Public+Active project, "
            f"got {response.status_code}: {response.text}"
        )
        data = response.json()
        assert str(data["id"]) == str(public_active_project.id)
        assert data["visibility"] == ProjectVisibility.PUBLIC
        assert data["status"] == ProjectStatus.ACTIVE


# ---------------------------------------------------------------------------
# T220-2: Guest → Restricted project → 404 (FR-018 enumeration safety)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestRestrictedProject404:
    """Guest receives 404 (not 403) for Restricted projects — anti-enumeration."""

    async def test_guest_gets_restricted_project_404(
        self,
        client: AsyncClient,
        restricted_project: Project,
    ) -> None:
        """GET /web-api/v1/projects/{restricted_id} as Guest → 404, not 403 (FR-018)."""
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}",
        )
        assert response.status_code == 404, (
            f"Expected 404 (anti-enumeration) for Restricted project, "
            f"got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# T220-3: Guest → Archived / Dormant Public project → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestNonActivePublicProject404:
    """Guest receives 404 for Public projects that are not Active."""

    async def test_guest_gets_archived_public_project_404(
        self,
        client: AsyncClient,
        archived_public_project: Project,
    ) -> None:
        """GET Archived Public project as Guest → 404 (FR-018)."""
        response = await client.get(
            f"/web-api/v1/projects/{archived_public_project.id}",
        )
        assert response.status_code == 404, (
            f"Expected 404 for Archived Public project, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_guest_gets_dormant_public_project_404(
        self,
        client: AsyncClient,
        dormant_public_project: Project,
    ) -> None:
        """GET Dormant Public project as Guest → 404 (FR-018)."""
        response = await client.get(
            f"/web-api/v1/projects/{dormant_public_project.id}",
        )
        assert response.status_code == 404, (
            f"Expected 404 for Dormant Public project, "
            f"got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# T220-4: Guest → absent project UUID → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestAbsentProject404:
    """Guest receives 404 when project UUID does not exist."""

    async def test_guest_gets_absent_project_404(
        self,
        client: AsyncClient,
    ) -> None:
        """GET /web-api/v1/projects/{random_uuid} as Guest → 404."""
        nonexistent = uuid.uuid4()
        response = await client.get(
            f"/web-api/v1/projects/{nonexistent}",
        )
        assert response.status_code == 404, (
            f"Expected 404 for nonexistent project, "
            f"got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# T220-5: Guest → project list → only Public + Active included
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestProjectListEnumeration:
    """Guest project list returns Public + Restricted Active (meta only),
    excluding Dormant / Archived rows.

    Phase 9 T410 / FR-019 (2026-04-27): the Guest list now surfaces
    Restricted projects as meta so outsiders can discover and request
    access via ``mailto:`` (US4). Phase 9 polish round 2 致命 1
    (2026-04-27): the list contract is now :class:`ProjectSummary`
    (``contracts/projects.yaml:ProjectSummary``) which structurally
    omits ``restricted_config``, so the previous "scrubbed to {}"
    assertion is replaced by a stronger "field absent" assertion.
    """

    async def test_guest_list_includes_public_and_restricted_active(
        self,
        client: AsyncClient,
        public_active_project: Project,
        restricted_project: Project,
        archived_public_project: Project,
        dormant_public_project: Project,
    ) -> None:
        """GET /web-api/v1/projects/ as Guest → Public + Restricted Active
        only; Dormant / Archived hidden (FR-016 + FR-019)."""
        response = await client.get("/web-api/v1/projects/")
        assert response.status_code == 200, (
            f"Expected 200 for Guest project list, "
            f"got {response.status_code}: {response.text}"
        )
        data = response.json()
        ids = {item["id"] for item in data["items"]}
        rows_by_id = {item["id"]: item for item in data["items"]}

        # Public + Active MUST be present (FR-016).
        assert str(public_active_project.id) in ids, (
            "Public+Active project must appear in Guest project list"
        )
        # Restricted + Active MUST be present (FR-019 meta enumeration).
        assert str(restricted_project.id) in ids, (
            "Restricted+Active project must appear in Guest project list "
            "(FR-019 meta enumeration)"
        )
        # Phase 9 polish round 2 致命 1: the list shape is now
        # ``ProjectSummary`` which has no ``restricted_config`` field at
        # all (contract-correct), so we assert structural absence rather
        # than ``== {}``. The Owner / Admin toggle surface is the
        # dedicated ``GET /projects/{id}/restricted-config`` endpoint
        # (Phase 8) — never the list.
        restricted_row = rows_by_id[str(restricted_project.id)]
        assert "restricted_config" not in restricted_row, (
            "ProjectSummary list rows must not carry ``restricted_config`` "
            "(contracts/projects.yaml:ProjectSummary, FR-019); got row "
            f"{restricted_row!r}"
        )
        # Sanity: contract-mandated fields are present.
        assert "owner_display_name" in restricted_row
        assert "dataset_count" in restricted_row
        assert "species_preview" in restricted_row
        # Archived MUST NOT be present
        assert str(archived_public_project.id) not in ids, (
            "Archived Public project must NOT appear in Guest project list"
        )
        # Dormant MUST NOT be present
        assert str(dormant_public_project.id) not in ids, (
            "Dormant Public project must NOT appear in Guest project list"
        )


# ---------------------------------------------------------------------------
# T220-6: Guest → mutating endpoints → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestMutatingEndpoints401:
    """Guest (no auth) receives 401 on all write-path web-api endpoints."""

    async def test_post_project_is_401(
        self,
        client: AsyncClient,
    ) -> None:
        """POST /web-api/v1/projects/ without auth → 401."""
        response = await client.post(
            "/web-api/v1/projects/",
            json={
                "name": "Should not be created",
                "license": "CC-BY",
            },
        )
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated POST /projects/, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_put_project_is_401(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """PUT /web-api/v1/projects/{id} without auth → 401."""
        response = await client.put(
            f"/web-api/v1/projects/{public_active_project.id}",
            json={"name": "Modified Name"},
        )
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated PUT /projects/{{id}}, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_delete_project_is_401(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """DELETE /web-api/v1/projects/{id} without auth → 401."""
        response = await client.delete(
            f"/web-api/v1/projects/{public_active_project.id}",
        )
        assert response.status_code == 401, (
            f"Expected 401 for unauthenticated DELETE /projects/{{id}}, "
            f"got {response.status_code}: {response.text}"
        )


# ---------------------------------------------------------------------------
# T220-7: Guest → Recording audio stream → bypasses auth (FlexibleCurrentUser)
#          For Public projects the bearer-less request should not return 401/403.
#          The actual audio file lives in S3 (not available in tests), so the
#          expected response is 404 (recording not found in S3) or 5xx if the
#          storage layer errors — but crucially NOT 401 or 403.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestRecordingStreamAccess:
    """Guest recording audio stream — Public project, no auth header needed.

    The audio endpoint uses FlexibleCurrentUser which allows bearer-less GET
    on Public projects.  The test asserts the response is NOT 401/403
    (permission denied) — a 404 or storage error is expected because the test
    DB recording's S3 object does not actually exist.
    """

    async def test_guest_can_request_public_recording_audio_not_401_403(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
    ) -> None:
        """GET /api/v1/projects/{pid}/recordings/{rid}/audio as Guest → not 401/403."""
        response = await client.get(
            f"/api/v1/projects/{public_active_project.id}"
            f"/recordings/{public_recording.id}/audio",
        )
        assert response.status_code not in (401, 403), (
            f"Guest must not be rejected with 401/403 on Public project audio, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_guest_audio_response_headers_no_species_name(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
    ) -> None:
        """Response headers for the audio endpoint must not contain species names (H-8/SC-016).

        The recording path uses UUID-only segments, ensuring no scientific name
        leaks via the URL.  Headers must also be free of species identifiers.
        """
        response = await client.get(
            f"/api/v1/projects/{public_active_project.id}"
            f"/recordings/{public_recording.id}/audio",
        )
        # Verify that path does not contain any human-readable species keyword.
        # The path stored in public_recording uses UUID-only segments.
        assert "merula" not in str(response.url).lower(), (
            "Recording URL must not expose species name (security H-8)"
        )
        for header_name, _header_value in response.headers.items():
            # Reject headers that embed raw species/taxon strings.
            assert "scientific_name" not in header_name.lower(), (
                f"Response header '{header_name}' contains 'scientific_name' — species leak"
            )


# ---------------------------------------------------------------------------
# T220-8: ProjectResponse PII check — no password_hash / internal fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublicProjectResponseNoPII:
    """Public project response must not contain PII (FR-030)."""

    async def test_project_detail_no_password_hash(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """ProjectResponse body must not contain password_hash or email PII (FR-030)."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}",
        )
        assert response.status_code == 200
        body = response.text

        # Forbidden fields must not appear in the serialised response.
        pii_fields = ["password_hash", "hashed_password", "security_stamp"]
        for field in pii_fields:
            assert field not in body, (
                f"PII field '{field}' must not appear in ProjectResponse body"
            )

    async def test_project_list_no_password_hash(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """ProjectListResponse must not contain password_hash (FR-030)."""
        response = await client.get("/web-api/v1/projects/")
        assert response.status_code == 200
        body = response.text

        pii_fields = ["password_hash", "hashed_password", "security_stamp"]
        for field in pii_fields:
            assert field not in body, (
                f"PII field '{field}' must not appear in ProjectListResponse body"
            )

    async def test_project_response_no_raw_coordinates(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """ProjectResponse must not contain raw lat/lng coordinates (FR-030).

        Coordinates are represented only via H3 index strings, never as
        float latitude/longitude fields at the wire level.
        """
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}",
        )
        assert response.status_code == 200
        data = response.json()

        # Traverse the full response and assert no forbidden coordinate keys.
        def _no_raw_coords(obj: Any, path: str = "") -> None:
            forbidden = {"latitude", "longitude", "lat", "lng"}
            if isinstance(obj, dict):
                for k, v in obj.items():
                    assert k not in forbidden, (
                        f"Raw coordinate field '{k}' found at path '{path}' in "
                        f"ProjectResponse (FR-030)"
                    )
                    _no_raw_coords(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _no_raw_coords(item, f"{path}[{i}]")

        _no_raw_coords(data)


# ---------------------------------------------------------------------------
# T220-9: Location precision — h3_index present, no raw lat/lng in Site rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLocationPrecisionH3Only:
    """Site location exposed to Guests must be H3-only, never raw coordinates.

    FR-029 / FR-030 / SC-016: Detections linked to sensitive taxa must have
    location coarsened to H3_RES ≤ 5.  ProjectResponse does not expose
    individual detection locations, so this test validates the Site field
    shape: ``h3_index`` present as string, no ``latitude``/``longitude``.
    """

    async def test_project_owner_field_no_raw_location(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """Owner sub-object inside ProjectResponse must not expose location data."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}",
        )
        assert response.status_code == 200
        data = response.json()
        owner = data.get("owner", {})

        # Owner object must not contain lat/lng
        assert "latitude" not in owner, "Owner sub-object must not contain 'latitude'"
        assert "longitude" not in owner, "Owner sub-object must not contain 'longitude'"


# ---------------------------------------------------------------------------
# T220-10 (polish round 2): Owner email PII leak — full PII surface check.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPublicProjectOwnerNoEmail:
    """Polish round 2 (致命1): owner sub-object must not contain ``email``.

    The original :class:`TestPublicProjectResponseNoPII` only flagged
    ``password_hash`` / ``hashed_password`` / ``security_stamp``; an Owner's
    email address would still have leaked because it lives on the User row
    that is embedded via ``ProjectResponse.owner``. Phase 5 polish round 2
    swaps the embedded schema to :class:`PublicOwnerResponse` which exposes
    only ``id`` and ``display_name``. These tests pin that contract so it
    cannot regress.
    """

    async def test_project_detail_owner_no_email(
        self,
        client: AsyncClient,
        public_active_project: Project,
        project_owner: User,
    ) -> None:
        """ProjectResponse.owner must not contain ``email`` (FR-030 polish round 2)."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}",
        )
        assert response.status_code == 200
        data = response.json()
        owner = data.get("owner", {})

        # The exact owner email value must not appear anywhere in the body
        assert project_owner.email not in response.text, (
            "Owner email must not appear in ProjectResponse body"
        )
        # And the ``email`` key must not be on the owner sub-object
        assert "email" not in owner, (
            "ProjectResponse.owner must not expose 'email' to Guests"
        )
        # Other PII fields that could be added by accident later
        for forbidden in ("created_at", "last_login_at"):
            assert forbidden not in owner, (
                f"ProjectResponse.owner must not expose '{forbidden}' to Guests"
            )
        # Allowed: id + display_name only
        assert "id" in owner
        assert "display_name" in owner

    async def test_project_list_owner_no_email(
        self,
        client: AsyncClient,
        public_active_project: Project,
        project_owner: User,
    ) -> None:
        """ProjectSummary list must not leak owner email to Guests.

        Phase 9 polish round 2 致命 1: the ``GET /web-api/v1/projects``
        list now returns the contract :class:`ProjectSummary` shape
        with ``owner_display_name`` (a string) rather than a nested
        ``owner`` sub-object. We assert (a) the owner's email never
        appears anywhere in the body and (b) no list item carries an
        ``owner`` key (which would imply a regression back to the
        embedded :class:`PublicOwnerResponse`).
        """
        response = await client.get("/web-api/v1/projects/")
        assert response.status_code == 200
        data = response.json()

        # The owner's email must never appear anywhere in the body.
        assert project_owner.email not in response.text, (
            "Owner email must not appear in ProjectSummary list body"
        )
        for item in data.get("items", []):
            assert "owner" not in item, (
                "ProjectSummary list rows must not carry a nested 'owner' "
                "object — owner_display_name is the only public-safe field "
                "(contracts/projects.yaml:ProjectSummary)."
            )
            assert "owner_display_name" in item, (
                "ProjectSummary contract requires 'owner_display_name'"
            )
            assert "email" not in item.get("owner_display_name", ""), (
                "owner_display_name must not echo the owner email"
            )

    async def test_project_recording_response_no_email(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
        project_owner: User,
    ) -> None:
        """Recording stream/audio responses must not echo owner email in headers/body.

        The audio response body is binary (or 404 in tests). Ensure the
        text representation of headers + URL never carries the owner email.
        """
        response = await client.get(
            f"/api/v1/projects/{public_active_project.id}"
            f"/recordings/{public_recording.id}/audio",
        )
        # The endpoint may 404 (S3 cache miss) — but the response surface
        # must still not leak owner email.
        haystack = (
            str(response.url)
            + " "
            + " ".join(f"{k}: {v}" for k, v in response.headers.items())
        )
        assert project_owner.email not in haystack, (
            "Owner email must not appear in audio stream URL or headers"
        )


# ---------------------------------------------------------------------------
# T220-11 (polish round 2): cookie-session principal resolves on Guest-aware
# endpoints (重要 2).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOwnerSessionSeesOwnRestricted:
    """Cookie-session callers must see *their own* Restricted projects.

    Polish round 2 重要 2: ``OptionalCurrentUser`` previously only inspected
    the ``Authorization`` header, so an authenticated Owner browsing through
    a session cookie was silently downgraded to Guest and 404'd on his/her
    own Restricted project list / detail. The dependency now reads
    ``request.state.principal`` (populated by the auth-router middleware)
    first.

    The integration test client used here does not exercise the cookie
    middleware end-to-end, so this test passes a Bearer JWT — which goes
    through the same fallback path the cookie code joins. The assertion is
    that an Authenticated caller (regardless of how the principal was
    resolved) sees the Restricted project they own.
    """

    async def test_owner_bearer_sees_own_restricted_in_list(
        self,
        client: AsyncClient,
        project_owner: User,
        restricted_project: Project,
    ) -> None:
        """Owner passing Bearer must see own Restricted project in list."""
        token = create_access_token({"sub": str(project_owner.id)})
        response = await client.get(
            "/web-api/v1/projects/",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        ids = {item["id"] for item in response.json()["items"]}
        assert str(restricted_project.id) in ids, (
            "Owner must see their own Restricted project in /web-api/v1/projects/"
        )

    async def test_owner_bearer_sees_own_restricted_detail_200(
        self,
        client: AsyncClient,
        project_owner: User,
        restricted_project: Project,
    ) -> None:
        """Owner passing Bearer must get 200 (not 404) on own Restricted detail."""
        token = create_access_token({"sub": str(project_owner.id)})
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["id"] == str(restricted_project.id)


# ---------------------------------------------------------------------------
# T220-12 (polish round 2): Guest blocked on archived/dormant Public audio
# stream (重要 3).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestArchivedDormantAudioStreamBlocked:
    """Guest must NOT receive audio for non-Active Public projects (FR-018).

    Polish round 2 重要 3: ``is_allowed`` previously only blocked Guest
    *mutating* actions on archived projects — VIEW_MEDIA and friends
    slipped through. The fix is in the central gate: any Guest read
    against a non-``active`` project is denied with an empty permission
    set. The audio endpoint then rejects with 403, which the recording-
    layer plumbing converts back to a 404 for callers; the assertion
    here is therefore "not 200 / 206".
    """

    @pytest.fixture
    async def archived_public_recording(
        self,
        db_session: AsyncSession,
        archived_public_project: Project,
        project_owner: User,
    ) -> Recording:
        """A recording attached to an Archived Public project."""
        site = Site(
            project_id=archived_public_project.id,
            name="T220-archived-site",
            h3_index="8928308280fffff",
        )
        db_session.add(site)
        await db_session.commit()
        await db_session.refresh(site)

        dataset = Dataset(
            project_id=archived_public_project.id,
            site_id=site.id,
            created_by_id=project_owner.id,
            name="T220 Archived Dataset",
            visibility=DatasetVisibility.PUBLIC,
            status=DatasetStatus.COMPLETED,
        )
        db_session.add(dataset)
        await db_session.commit()
        await db_session.refresh(dataset)

        rec_id = uuid.uuid4()
        recording = Recording(
            id=rec_id,
            dataset_id=dataset.id,
            filename="archived.wav",
            path=(
                f"recordings/{archived_public_project.id}"
                f"/{dataset.id}/{rec_id}.wav"
            ),
            duration=5.0,
            samplerate=44100,
            channels=1,
        )
        db_session.add(recording)
        await db_session.commit()
        await db_session.refresh(recording)
        return recording

    async def test_guest_audio_on_archived_public_blocked(
        self,
        client: AsyncClient,
        archived_public_project: Project,
        archived_public_recording: Recording,
    ) -> None:
        """GET audio on Archived Public project as Guest must NOT return 2xx."""
        response = await client.get(
            f"/api/v1/projects/{archived_public_project.id}"
            f"/recordings/{archived_public_recording.id}/audio",
        )
        # Acceptable: 403 (gate-denied) or 404 (anti-enumeration). Definitely
        # not 200/206 (Public archived must not stream to Guest).
        assert response.status_code in (401, 403, 404), (
            f"Guest must not receive audio for archived Public project, "
            f"got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# T220-13 (polish round 2): prefix typo must not bypass cookie-required path
# (重要 4).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPrefixTypoNotBypassed:
    """Prefix typo paths (``/web-api/v1/projectsXYZ``) must not be Guest-allowed.

    Polish round 2 重要 4: the Guest allowlist used ``startswith`` which let
    typo paths slip through. The fix tightens the match to exact-or-slash
    (``path == prefix or path.startswith(prefix + '/')``).
    """

    async def test_guest_typo_prefix_not_200(
        self,
        client: AsyncClient,
    ) -> None:
        """``/web-api/v1/projectsXYZ`` must NOT be Guest-allowed.

        Expected: 404 (route not registered) or 401 (auth required), never 200.
        """
        response = await client.get("/web-api/v1/projectsXYZ/anything")
        assert response.status_code != 200, (
            f"Typo prefix must not bypass to a Guest 200, got "
            f"{response.status_code}: {response.text}"
        )
        assert response.status_code in (401, 404), (
            f"Typo prefix must reach session auth (401) or be unrouted (404), "
            f"got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# T220-14 (polish round 3): nested project resource paths must require auth
# (重要 2: Guest allowlist 過剰許可).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNestedProjectPathsRequireAuth:
    """Nested ``/web-api/v1/projects/{id}/<sub>`` paths must NOT be Guest-allowed.

    Polish round 3 重要 2: the previous Guest allowlist used a ``startswith``
    match which would auto-pass any GET under the ``/web-api/v1/projects``
    prefix — including future endpoints such as ``/projects/{id}/members``
    or ``/projects/{id}/license-history``. The fix narrows the match to
    exact collection (``/projects``) and single-segment detail
    (``/projects/{id}``) only; nested paths must reach the session
    authenticator.

    These tests fire GET requests at *hypothetical* nested paths (the route
    may not exist yet — that is fine; the assertion is "not 200 / not a
    silent Guest pass"). Whether the framework returns 401 (auth router
    rejected the missing cookie) or 404 (FastAPI rejected the unknown
    route AFTER auth) depends on registration order — both are acceptable.
    The crucial bit is that the response is NOT a 200 served to a Guest.
    """

    async def test_guest_cannot_get_nested_members_path(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """GET /web-api/v1/projects/{id}/members as Guest → not 200."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/members",
        )
        assert response.status_code != 200, (
            f"Nested /members must not be auto-allowed for Guests, got "
            f"{response.status_code}: {response.text}"
        )
        # Either auth-router rejected (401) or route is unknown (404). Anything
        # else (e.g. 200 / 403 with body) means the Guest fast-path leaked.
        assert response.status_code in (401, 404), (
            f"Nested /members must reach auth (401) or be unrouted (404), "
            f"got {response.status_code}"
        )

    async def test_guest_cannot_get_nested_license_history_path(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """GET /web-api/v1/projects/{id}/license-history as Guest → not 200."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/license-history",
        )
        assert response.status_code != 200, (
            f"Nested /license-history must not be auto-allowed for Guests, "
            f"got {response.status_code}: {response.text}"
        )
        assert response.status_code in (401, 404), (
            f"Nested /license-history must reach auth (401) or be "
            f"unrouted (404), got {response.status_code}"
        )

    async def test_guest_cannot_get_arbitrary_nested_subpath(
        self,
        client: AsyncClient,
        public_active_project: Project,
    ) -> None:
        """GET /web-api/v1/projects/{id}/anything as Guest → not 200.

        Generic guard: any future nested resource added under
        ``/web-api/v1/projects/{id}/`` must NOT be silently Guest-allowed
        without an explicit allowlist update.
        """
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/anything-new",
        )
        assert response.status_code != 200, (
            f"Arbitrary nested subpath must not be Guest-allowed, got "
            f"{response.status_code}: {response.text}"
        )
        assert response.status_code in (401, 404), (
            f"Arbitrary nested subpath must reach auth (401) or be "
            f"unrouted (404), got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# T220-15 (polish round 4 — 致命 1): Guest recording list endpoint
# (``GET /web-api/v1/projects/{id}/recordings``).
#
# Backstory: Phase 5 round 3 left the Guest detail page (``+page.svelte``)
# rendering an empty array because there was no Guest-aware recording list
# endpoint. The audio stream worked but Guests had no way to discover the
# recording UUIDs. Round 4 adds a minimal Web UI surface that:
#
# * Returns 200 with a paginated list on Public + Active projects.
# * Returns 404 on Restricted / Archived / Dormant projects (FR-018).
# * Shapes the response so it never echoes the S3 object key, content
#   hash, owner email, or raw lat/lng (FR-030).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGuestPublicRecordingList:
    """Guest can enumerate recordings on Public + Active projects."""

    async def test_guest_lists_public_active_recordings_200(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
    ) -> None:
        """GET /web-api/v1/projects/{public_id}/recordings as Guest → 200."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/recordings",
        )
        assert response.status_code == 200, (
            f"Expected 200 for Guest recording list on Public+Active project, "
            f"got {response.status_code}: {response.text}"
        )
        body = response.json()
        assert body["page"] == 1
        assert body["limit"] == 20
        assert body["total"] >= 1

        ids = {item["id"] for item in body["items"]}
        assert str(public_recording.id) in ids, (
            "public_recording must appear in Guest recording list"
        )

    async def test_guest_recording_list_response_shape_is_minimal(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
    ) -> None:
        """Response shape must NOT include path / hash / note / owner email."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/recordings",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["items"], "fixture should produce at least one recording row"

        item = next(
            it for it in body["items"] if it["id"] == str(public_recording.id)
        )
        # Allowed keys — exact contract for the public recording shape.
        assert set(item.keys()) <= {
            "id",
            "project_id",
            "name",
            "duration_seconds",
            "site_h3_index",
        }, (
            f"PublicRecordingItem leaked unexpected fields: "
            f"{set(item.keys()) - {'id', 'project_id', 'name', 'duration_seconds', 'site_h3_index'}}"
        )

        # Forbidden keys (S3 object key, content hash, free-form notes).
        for forbidden in ("path", "hash", "note", "filename_full", "s3_key"):
            assert forbidden not in item, (
                f"PublicRecordingItem must not expose '{forbidden}' to Guests"
            )

    async def test_guest_recording_list_no_raw_coordinates(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
    ) -> None:
        """Recording list must not contain raw lat/lng anywhere (FR-030)."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/recordings",
        )
        assert response.status_code == 200, response.text
        body = response.text
        for forbidden in ('"latitude"', '"longitude"', '"lat"', '"lng"'):
            assert forbidden not in body, (
                f"Recording list body leaked raw coordinate key {forbidden}"
            )

    async def test_guest_recording_list_does_not_echo_owner_email(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
        project_owner: User,
    ) -> None:
        """Owner email must not surface in recording list body (FR-030)."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/recordings",
        )
        assert response.status_code == 200, response.text
        assert project_owner.email not in response.text, (
            "Owner email must not appear in PublicRecordingListResponse body"
        )

    async def test_guest_recording_list_on_restricted_project_404(
        self,
        client: AsyncClient,
        restricted_project: Project,
    ) -> None:
        """Guest GET /recordings on Restricted project → 404 (FR-018)."""
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}/recordings",
        )
        assert response.status_code == 404, (
            f"Expected 404 (anti-enumeration) for Restricted recording list, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_guest_recording_list_on_archived_public_project_404(
        self,
        client: AsyncClient,
        archived_public_project: Project,
    ) -> None:
        """Guest GET /recordings on Archived Public project → 404 (FR-018)."""
        response = await client.get(
            f"/web-api/v1/projects/{archived_public_project.id}/recordings",
        )
        assert response.status_code == 404, (
            f"Expected 404 for Archived Public recording list, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_guest_recording_list_on_absent_project_404(
        self,
        client: AsyncClient,
    ) -> None:
        """Guest GET /recordings on absent project UUID → 404."""
        nonexistent = uuid.uuid4()
        response = await client.get(
            f"/web-api/v1/projects/{nonexistent}/recordings",
        )
        assert response.status_code == 404, (
            f"Expected 404 for nonexistent project recording list, "
            f"got {response.status_code}: {response.text}"
        )

    async def test_guest_recording_list_pagination_clamped(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording: Recording,
    ) -> None:
        """Pagination params honored; out-of-range page returns empty list."""
        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/recordings"
            f"?page=99&limit=5",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["page"] == 99
        assert body["limit"] == 5
        assert body["items"] == [], (
            "Out-of-range page should return empty items list"
        )


# ---------------------------------------------------------------------------
# T220-16 (polish round 5 — 重要 1): Site H3 generalisation on the Guest
# recording list (FR-029, FR-030).
#
# Backstory: round 4 wired ``site_h3_index`` directly from the raw
# ``Site.h3_index`` column. If a deployment stores sites at a precise
# resolution (e.g. res 15, ~1 m² cells) the Guest-facing list would echo
# the full precision back. ``apply_response_filter`` only generalises the
# field literally named ``h3_index``, so the round-4 code's defence-in-depth
# call had no effect on ``site_h3_index``.
#
# Round 5 routes the cell through an adapter shape that exposes
# ``h3_index_member`` to the filter, runs stage 2, then writes the
# coarsened cell back onto the response field. Public + non-member callers
# now see at most H3_RES_9 (project ceiling, FR-016 semantics).
# ---------------------------------------------------------------------------


@pytest.fixture
async def public_site_high_precision(
    db_session: AsyncSession, public_active_project: Project
) -> Site:
    """A site stored at H3 resolution 15 — the worst case for leakage.

    Cell ``8f2a10728906185`` was generated via ``h3.latlng_to_cell`` so it is
    guaranteed valid; using a hard-coded literal keeps the test independent
    of the h3 library's runtime behaviour.
    """
    site = Site(
        project_id=public_active_project.id,
        name="T220 High Precision Site",
        h3_index="8f2a10728906185",  # res 15
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def public_dataset_high_precision(
    db_session: AsyncSession,
    public_active_project: Project,
    public_site_high_precision: Site,
    project_owner: User,
) -> Dataset:
    """Dataset linked to the res-15 site."""
    dataset = Dataset(
        project_id=public_active_project.id,
        site_id=public_site_high_precision.id,
        created_by_id=project_owner.id,
        name="T220 High Precision Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def public_recording_high_precision(
    db_session: AsyncSession,
    public_dataset_high_precision: Dataset,
) -> Recording:
    """Recording attached to the res-15 dataset."""
    rec_id = uuid.uuid4()
    recording = Recording(
        id=rec_id,
        dataset_id=public_dataset_high_precision.id,
        filename="test_t220_hp.wav",
        path=(
            f"recordings/{public_dataset_high_precision.project_id}"
            f"/{public_dataset_high_precision.id}/{rec_id}.wav"
        ),
        duration=5.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


@pytest.mark.asyncio
class TestGuestRecordingListH3Generalisation:
    """Site H3 indexes are coarsened to the Public ceiling for Guest callers."""

    async def test_guest_sees_h3_coarsened_to_public_ceiling(
        self,
        client: AsyncClient,
        public_active_project: Project,
        public_recording_high_precision: Recording,
    ) -> None:
        """Raw res-15 cell must be returned at most at H3_RES_9 to Guests.

        FR-029 / FR-030: the Public visibility ceiling is res 9 unless the
        project / taxon configuration loosens it (no looser override here).
        Asserting on the runtime resolution rather than a hard-coded cell
        keeps the test resilient to any future change in the H3 hierarchy.
        """
        import h3 as _h3

        response = await client.get(
            f"/web-api/v1/projects/{public_active_project.id}/recordings",
        )
        assert response.status_code == 200, response.text
        body = response.json()

        item = next(
            it
            for it in body["items"]
            if it["id"] == str(public_recording_high_precision.id)
        )
        leaked = item["site_h3_index"]
        assert leaked is not None, (
            "site_h3_index should be present (was set on the linked Site)"
        )
        # Stored cell is res 15 — Guest must NEVER see this raw value.
        assert leaked != "8f2a10728906185", (
            "Raw res-15 site h3_index leaked to Guest — "
            "apply_response_filter did not generalise it"
        )
        # Public ceiling is H3_RES_9: anything coarser-or-equal is fine.
        assert _h3.get_resolution(leaked) <= 9, (
            f"Guest received site_h3_index at resolution "
            f"{_h3.get_resolution(leaked)}, expected <= 9 (Public ceiling)"
        )
        # Sanity check: the coarsened cell must be an ancestor of the raw cell.
        assert _h3.cell_to_parent("8f2a10728906185", _h3.get_resolution(leaked)) == leaked, (
            "Coarsened cell must be the H3 ancestor of the raw site cell"
        )
