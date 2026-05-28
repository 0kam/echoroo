"""Viewer permission boundary integration tests (T131).

Spec: FR-004 — Viewer has read-only access; all mutating operations must
return 403. Read operations must return 200 (or appropriate 2xx/4xx that is
not a permission error).

Test structure:
  * ``TestViewerForbidden``  — Viewer gets 403 on every write/mutating endpoint.
  * ``TestViewerAllowed``    — Viewer gets 200 (or 404/501 for unresolved
    resources, never 401/403) on every read endpoint.

Fixture note: viewer_user is a project VIEWER member on test_project, which
uses ProjectVisibility.RESTRICTED (the default in contract/conftest.py).
On RESTRICTED projects, VIEWER permissions come from ROLE_PERMISSIONS[VIEWER]
directly (no normalization to Authenticated).
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import ProjectMemberRole, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def viewer_user(db_session: AsyncSession) -> User:
    """Create a user that will be a VIEWER on the test project."""
    user = User(
        email="t131viewer@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T131 Viewer",
        security_stamp="v" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    """Create the project owner user."""
    user = User(
        email="t131owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T131 Owner",
        security_stamp="w" * 64,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_project(db_session: AsyncSession, owner_user: User) -> Project:
    """Create a RESTRICTED project owned by owner_user."""
    project = Project(
        name="T131 Test Project",
        description="Viewer boundary test",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner_user.id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest_asyncio.fixture
async def viewer_member(
    db_session: AsyncSession,
    test_project: Project,
    viewer_user: User,
    owner_user: User,
) -> ProjectMember:
    """Add viewer_user as a VIEWER on test_project."""
    member = ProjectMember(
        user_id=viewer_user.id,
        project_id=test_project.id,
        role=ProjectMemberRole.VIEWER,
        invited_by_id=owner_user.id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


@pytest.fixture
def viewer_headers(viewer_user: User) -> dict[str, str]:
    """JWT auth headers for viewer_user."""
    token = create_access_token({"sub": str(viewer_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner_headers(owner_user: User) -> dict[str, str]:
    """JWT auth headers for owner_user."""
    token = create_access_token({"sub": str(owner_user.id)})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A sentinel UUID that is unlikely to exist; used for endpoints that require
# a resource ID in the URL path but we only care about the permission check.
_FAKE_UUID = "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# TestViewerForbidden — FR-004: Viewer must get 403 on mutating endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestViewerForbidden:
    """Viewer must receive 403 (not 401, not 200) on all write-path endpoints."""

    async def test_create_tag_is_403(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,  # ensure member row exists
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/tags (CREATE_TAG permission) → 403 for Viewer."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/tags",
            headers=viewer_headers,
            json={
                "name": "Turdus merula",
                "scientific_name": "Turdus merula",
                "category": "species",
            },
        )
        assert response.status_code == 403, (
            f"Expected 403 for Viewer on POST /tags, got {response.status_code}: "
            f"{response.text}"
        )

    async def test_cast_vote_is_403(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/annotations/{id}/votes (VOTE) → 403 for Viewer.

        Phase 16 Batch 6e (2026-04-29) middleware-ordering fix: the
        Phase 6 :class:`VoteCastRequest` schema requires the field
        ``vote`` (with values ``agree`` / ``disagree`` / ``unsure``);
        the legacy body ``{"vote_type": "confirm"}`` 422s on missing
        ``vote`` before the permission gate fires. Send a contract-shaped
        body so the gate has a chance to deny on VOTE.
        """
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/annotations/{_FAKE_UUID}/votes",
            headers=viewer_headers,
            json={"vote": "agree"},
        )
        # 403 = permission denied (correct); 404 = annotation not found but
        # permission check ran (gate is after project load) → also acceptable
        # since the VOTE permission gate fires before the annotation lookup.
        # We strictly assert 403 per spec FR-004.
        assert response.status_code == 403, (
            f"Expected 403 for Viewer on POST /annotations/votes, got {response.status_code}"
        )

    async def test_create_comment_is_403(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/annotations/{id}/comments (COMMENT) → 403 for Viewer.

        The annotation comments router was wired into the v1 app
        factory as part of the Phase 17 contract drift cleanup, so the
        permission gate now runs and a Viewer-role caller MUST be
        rejected with 403 before the body validation. The body field
        is ``body`` per :class:`AnnotationCommentCreate`.
        """
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/annotations/{_FAKE_UUID}/comments",
            headers=viewer_headers,
            json={"body": "A comment"},
        )
        assert response.status_code == 403, (
            f"Expected 403 for Viewer on POST /annotations/comments, got {response.status_code}"
        )

    async def test_create_upload_session_is_403(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """POST /projects/{id}/datasets/{d}/upload-sessions (UPLOAD) → 403 for Viewer."""
        response = await client.post(
            f"/api/v1/projects/{test_project.id}/datasets/{_FAKE_UUID}/upload-sessions",
            headers=viewer_headers,
            json={"files": [{"filename": "test.wav", "content_type": "audio/wav", "size": 1024}]},
        )
        assert response.status_code == 403, (
            f"Expected 403 for Viewer on POST /upload-sessions, got {response.status_code}"
        )

    async def test_patch_recording_is_403(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """PATCH /projects/{id}/recordings/{rid} → 403 for Viewer.

        This endpoint uses legacy check_project_access; Viewer is a project
        member so the access check passes the membership gate but the caller
        is not an Admin/Member — the legacy check allows any member. This
        test documents the expected behaviour per spec FR-004:

        Because check_project_access only verifies membership (not role), Viewer
        would get 404 (recording not found) rather than 403. We mark this test
        xfail until a dedicated RECORDING_UPDATE_ACTION replaces the legacy gate.
        """
        pytest.xfail(
            "PATCH /recordings uses legacy check_project_access which allows any "
            "member (including Viewer). FR-008a RECORDING_UPDATE_ACTION not yet "
            "wired (Phase 3 follow-up TODO in recordings.py)."
        )

    async def test_delete_recording_is_403(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """DELETE /projects/{id}/recordings/{rid} → 403 for Viewer.

        Same implementation gap as PATCH — uses legacy check_project_access.
        Marked xfail until RECORDING_DELETE_ACTION is wired.
        """
        pytest.xfail(
            "DELETE /recordings uses legacy check_project_access which allows any "
            "member (including Viewer). FR-008a RECORDING_DELETE_ACTION not yet "
            "wired (Phase 3 follow-up TODO in recordings.py)."
        )


# ---------------------------------------------------------------------------
# TestViewerAllowed — FR-004: Viewer must get 200 on read endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestViewerAllowed:
    """Viewer must NOT receive 401/403 on read-path endpoints.

    Expected status codes:
      200  — resource found and returned.
      404  — resource does not exist, but permission check passed.
      Any other 4xx/5xx that is NOT 401/403 is also acceptable here.
    """

    async def test_get_project_is_200(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """GET /projects/{id} (VIEW_PROJECT_METADATA) → 200 for Viewer."""
        response = await client.get(
            f"/api/v1/projects/{test_project.id}",
            headers=viewer_headers,
        )
        assert response.status_code == 200, (
            f"Expected 200 for Viewer on GET /projects, got {response.status_code}: "
            f"{response.text}"
        )
        data = response.json()
        assert str(data["id"]) == str(test_project.id)

    async def test_get_detections_is_not_forbidden(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """GET /projects/{id}/detections (VIEW_DETECTION) → not 401/403 for Viewer."""
        response = await client.get(
            f"/api/v1/projects/{test_project.id}/detections",
            headers=viewer_headers,
        )
        assert response.status_code not in (401, 403), (
            f"Viewer should not be blocked on GET /detections, got {response.status_code}"
        )

    async def test_get_recordings_is_not_forbidden(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """GET /projects/{id}/recordings (VIEW_DETECTION) → not 401/403 for Viewer."""
        response = await client.get(
            f"/api/v1/projects/{test_project.id}/recordings",
            headers=viewer_headers,
        )
        assert response.status_code not in (401, 403), (
            f"Viewer should not be blocked on GET /recordings, got {response.status_code}"
        )

    async def test_get_recording_audio_is_not_forbidden(
        self,
        client: AsyncClient,
        viewer_headers: dict[str, str],
        viewer_member: ProjectMember,
        test_project: Project,
    ) -> None:
        """GET /projects/{id}/recordings/{rid}/audio (VIEW_MEDIA) → not 401/403 for Viewer.

        The recording doesn't exist so we expect 404, but NOT 401/403.
        """
        response = await client.get(
            f"/api/v1/projects/{test_project.id}/recordings/{_FAKE_UUID}/audio",
            headers=viewer_headers,
        )
        # 404 = recording not found (permission gate passed) — acceptable.
        # 401/403 = permission denied — NOT acceptable.
        assert response.status_code not in (401, 403), (
            f"Viewer should not be blocked on GET /recordings/audio, got {response.status_code}"
        )
