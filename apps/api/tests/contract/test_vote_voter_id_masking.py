"""Voter-id masking contract (T313, FR-039).

FR-039 requires that the response from the vote summary endpoint always
emits the ``voters`` array (vote visibility is preserved) but masks the
``user_id`` of *non-member* and *trusted_user* votes for every viewer
except Owner / Admin. Member votes are visible to everyone.

The viewer roles tested:

* **Owner** — sees raw UUIDs for member, guest_authenticated, and
  trusted_user votes. (Trusted not exercised — Phase 10.)
* **Admin** — same visibility as Owner per FR-039.
* **Member** — sees member ``user_id``s, but guest_authenticated /
  trusted_user ``user_id`` is masked to ``None``.
* **Viewer** — same masking as Member.
* **Guest authenticated (non-member)** — same masking as Member.

Also asserts each ``voters[]`` element carries ``source`` and
``project_role_at_vote`` (so the UI can render the FR-038 breakdown).
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

pytestmark = _pytest_phase14_skip.mark.skip(
    reason=(
        "Phase 14+ deferred — rich-shape Annotation columns (recording_id /"
        " tag_id / status / start_time / end_time / etc) live on the future"
        " ``recording_annotations`` table; see ``apps/api/echoroo/models/"
        "annotation.py`` and ``apps/api/echoroo/models/recording_annotation.py``"
        " module docstrings."
    ),
)
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionSource,
    DetectionStatus,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
    TagCategory,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation as Annotation
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Restricted config (unused for Public)
# ---------------------------------------------------------------------------

_PUBLIC_RESTRICTED_CONFIG: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Fixtures — actors
# ---------------------------------------------------------------------------


@pytest.fixture
async def t313_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t313owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T313 Owner",
        security_stamp="t313" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t313_admin(db_session: AsyncSession) -> User:
    user = User(
        email="t313admin@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T313 Admin",
        security_stamp="t313" + "a" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t313_member(db_session: AsyncSession) -> User:
    user = User(
        email="t313member@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T313 Member",
        security_stamp="t313" + "m" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t313_viewer(db_session: AsyncSession) -> User:
    user = User(
        email="t313viewer@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T313 Viewer",
        security_stamp="t313" + "v" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t313_guest_voter(db_session: AsyncSession) -> User:
    """The voter whose vote will be the masked / unmasked subject."""
    user = User(
        email="t313guestvoter@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T313 Guest Voter",
        security_stamp="t313" + "g" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t313_other_guest_viewer(db_session: AsyncSession) -> User:
    """Authenticated non-member viewer (separate from the voter)."""
    user = User(
        email="t313othguestviewer@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T313 Other Guest Viewer",
        security_stamp="t313" + "h" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Fixtures — project / membership / annotation
# ---------------------------------------------------------------------------


@pytest.fixture
async def t313_public_project(
    db_session: AsyncSession, t313_owner: User
) -> Project:
    project = Project(
        name="T313 Public Project",
        description="Phase 6 voter_id masking contract",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=t313_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_PUBLIC_RESTRICTED_CONFIG,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t313_admin_membership(
    db_session: AsyncSession,
    t313_public_project: Project,
    t313_admin: User,
    t313_owner: User,
) -> ProjectMember:
    membership = ProjectMember(
        user_id=t313_admin.id,
        project_id=t313_public_project.id,
        role=ProjectMemberRole.ADMIN,
        invited_by_id=t313_owner.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
async def t313_member_membership(
    db_session: AsyncSession,
    t313_public_project: Project,
    t313_member: User,
    t313_owner: User,
) -> ProjectMember:
    membership = ProjectMember(
        user_id=t313_member.id,
        project_id=t313_public_project.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=t313_owner.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
async def t313_viewer_membership(
    db_session: AsyncSession,
    t313_public_project: Project,
    t313_viewer: User,
    t313_owner: User,
) -> ProjectMember:
    membership = ProjectMember(
        user_id=t313_viewer.id,
        project_id=t313_public_project.id,
        role=ProjectMemberRole.VIEWER,
        invited_by_id=t313_owner.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
async def t313_site(
    db_session: AsyncSession, t313_public_project: Project
) -> Site:
    site = Site(
        project_id=t313_public_project.id,
        name="T313 Site",
        h3_index_member="89283082803ffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def t313_dataset(
    db_session: AsyncSession,
    t313_public_project: Project,
    t313_site: Site,
    t313_owner: User,
) -> Dataset:
    dataset = Dataset(
        project_id=t313_public_project.id,
        site_id=t313_site.id,
        created_by_id=t313_owner.id,
        name="T313 Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def t313_recording(
    db_session: AsyncSession, t313_dataset: Dataset
) -> Recording:
    rec = Recording(
        dataset_id=t313_dataset.id,
        filename="t313.wav",
        path="t313.wav",
        duration=10.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(rec)
    await db_session.commit()
    await db_session.refresh(rec)
    return rec


@pytest.fixture
async def t313_tag(
    db_session: AsyncSession, t313_public_project: Project
) -> Tag:
    tag = Tag(
        project_id=t313_public_project.id,
        name="Cardinalis cardinalis",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def t313_annotation(
    db_session: AsyncSession, t313_recording: Recording, t313_tag: Tag
) -> Annotation:
    ann = Annotation(
        recording_id=t313_recording.id,
        tag_id=t313_tag.id,
        source=DetectionSource.BIRDNET,
        status=DetectionStatus.UNREVIEWED,
        confidence=0.81,
        start_time=1.0,
        end_time=4.0,
    )
    db_session.add(ann)
    await db_session.commit()
    await db_session.refresh(ann)
    return ann


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


def _bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
def t313_owner_headers(t313_owner: User) -> dict[str, str]:
    return _bearer(t313_owner)


@pytest.fixture
def t313_admin_headers(t313_admin: User) -> dict[str, str]:
    return _bearer(t313_admin)


@pytest.fixture
def t313_member_headers(t313_member: User) -> dict[str, str]:
    return _bearer(t313_member)


@pytest.fixture
def t313_viewer_headers(t313_viewer: User) -> dict[str, str]:
    return _bearer(t313_viewer)


@pytest.fixture
def t313_guest_voter_headers(t313_guest_voter: User) -> dict[str, str]:
    return _bearer(t313_guest_voter)


@pytest.fixture
def t313_other_guest_viewer_headers(
    t313_other_guest_viewer: User,
) -> dict[str, str]:
    return _bearer(t313_other_guest_viewer)


# ---------------------------------------------------------------------------
# Mixed-vote setup fixture — exercises member + guest_authenticated voters
# ---------------------------------------------------------------------------


@pytest.fixture
async def t313_mixed_votes(
    client: AsyncClient,
    db_session: AsyncSession,
    t313_public_project: Project,
    t313_annotation: Annotation,
    t313_member: User,
    t313_member_membership: ProjectMember,
    t313_guest_voter: User,
    t313_member_headers: dict[str, str],
    t313_guest_voter_headers: dict[str, str],
) -> dict[str, UUID]:
    """Cast 1 member agree + 1 guest_authenticated disagree on the annotation."""
    member_resp = await client.post(
        f"/api/v1/projects/{t313_public_project.id}/detections/"
        f"{t313_annotation.id}/votes",
        headers=t313_member_headers,
        json={"vote": "agree"},
    )
    assert member_resp.status_code in {200, 201}, member_resp.text

    guest_resp = await client.post(
        f"/api/v1/projects/{t313_public_project.id}/detections/"
        f"{t313_annotation.id}/votes",
        headers=t313_guest_voter_headers,
        json={"vote": "disagree"},
    )
    assert guest_resp.status_code in {200, 201}, guest_resp.text

    return {
        "member_voter_id": t313_member.id,
        "guest_voter_id": t313_guest_voter.id,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _votes_endpoint(project_id: UUID, detection_id: UUID) -> str:
    return f"/api/v1/projects/{project_id}/detections/{detection_id}/votes"


def _find_vote_for_user(
    body: dict[str, Any], voter_id: UUID
) -> dict[str, Any] | None:
    """Find a single vote entry by *expected* voter UUID even if it's masked.

    Returns the entry whose ``user_id`` matches the UUID; if none match, falls
    back to filtering by the source field. The caller decides how to interpret
    a missing match.
    """
    for v in body.get("voters", []):
        uid = v.get("user_id")
        if uid is not None and str(uid) == str(voter_id):
            return v
    return None


def _filter_by_source(
    body: dict[str, Any], source: str
) -> list[dict[str, Any]]:
    return [v for v in body.get("voters", []) if v.get("source") == source]


# ---------------------------------------------------------------------------
# Tests — Owner / Admin see UUIDs for non-member votes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOwnerAdminSeeAllVoterIds:
    """Owner / Admin see raw ``user_id`` for every vote, regardless of source."""

    async def test_owner_sees_guest_authenticated_voter_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_owner_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_owner_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        # voters[] array MUST be present (vote visibility preserved).
        assert "voters" in body
        assert len(body["voters"]) == 2

        guest_votes = _filter_by_source(body, "guest_authenticated")
        assert len(guest_votes) == 1
        # FR-039: Owner sees the raw UUID.
        assert guest_votes[0]["user_id"] == str(t313_mixed_votes["guest_voter_id"]), (
            f"Owner should see raw guest_authenticated voter UUID, "
            f"got {guest_votes[0]['user_id']!r}"
        )

    async def test_admin_sees_guest_authenticated_voter_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_admin_headers: dict[str, str],
        t313_admin_membership: ProjectMember,
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_admin_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        guest_votes = _filter_by_source(body, "guest_authenticated")
        assert len(guest_votes) == 1
        assert guest_votes[0]["user_id"] == str(t313_mixed_votes["guest_voter_id"])


# ---------------------------------------------------------------------------
# Tests — Member / Viewer / non-member viewers see masked guest_authenticated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestNonAdminViewersSeeMaskedGuestVotes:
    """Member / Viewer / guest viewer see ``user_id=None`` for guest votes."""

    async def test_member_viewer_sees_masked_guest_authenticated_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_member_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_member_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        # voters[] is still returned (vote visibility preserved).
        assert "voters" in body
        assert len(body["voters"]) == 2

        guest_votes = _filter_by_source(body, "guest_authenticated")
        assert len(guest_votes) == 1
        assert guest_votes[0]["user_id"] is None, (
            f"Member viewer should see masked guest_authenticated user_id, "
            f"got {guest_votes[0]['user_id']!r}"
        )
        # Embedded ``user`` info is also stripped to avoid leaking display name.
        assert guest_votes[0].get("user") in (None, {}), (
            f"Embedded user info must be hidden when user_id is masked, "
            f"got {guest_votes[0].get('user')!r}"
        )

    async def test_viewer_role_sees_masked_guest_authenticated_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_viewer_headers: dict[str, str],
        t313_viewer_membership: ProjectMember,
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_viewer_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        guest_votes = _filter_by_source(body, "guest_authenticated")
        assert len(guest_votes) == 1
        assert guest_votes[0]["user_id"] is None, (
            "Viewer-role viewer must see masked guest user_id (FR-039)"
        )

    async def test_authenticated_non_member_sees_masked_guest_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_other_guest_viewer_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_other_guest_viewer_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()

        guest_votes = _filter_by_source(body, "guest_authenticated")
        assert len(guest_votes) == 1
        assert guest_votes[0]["user_id"] is None, (
            "Authenticated non-member viewer must see masked guest user_id"
        )


# ---------------------------------------------------------------------------
# Tests — Member votes ARE visible to all viewer roles (FR-039 narrow scope)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMemberVotesVisibleToAllViewers:
    """FR-039 only masks non-member / Trusted votes — member votes always visible."""

    async def test_member_role_viewer_sees_member_voter_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_member_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_member_headers,
        )
        body = response.json()

        member_votes = _filter_by_source(body, "member")
        assert len(member_votes) == 1
        assert member_votes[0]["user_id"] == str(t313_mixed_votes["member_voter_id"]), (
            f"Member votes must NOT be masked for any viewer role (FR-039 only "
            f"masks non-member / Trusted), got {member_votes[0]['user_id']!r}"
        )

    async def test_authenticated_non_member_sees_member_voter_uuid(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_other_guest_viewer_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_other_guest_viewer_headers,
        )
        body = response.json()

        member_votes = _filter_by_source(body, "member")
        assert len(member_votes) == 1
        assert member_votes[0]["user_id"] == str(t313_mixed_votes["member_voter_id"])


# ---------------------------------------------------------------------------
# Tests — every vote element carries source + project_role_at_vote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVoteFieldsCompleteness:
    """Each ``voters[]`` element exposes FR-037 source + role snapshot."""

    async def test_each_vote_has_source_and_project_role_at_vote(
        self,
        client: AsyncClient,
        t313_public_project: Project,
        t313_annotation: Annotation,
        t313_mixed_votes: dict[str, UUID],
        t313_owner_headers: dict[str, str],
    ) -> None:
        response = await client.get(
            _votes_endpoint(t313_public_project.id, t313_annotation.id),
            headers=t313_owner_headers,
        )
        body = response.json()

        assert len(body["voters"]) == 2
        for entry in body["voters"]:
            assert "source" in entry, f"vote element missing 'source' key: {entry}"
            assert entry["source"] in {
                "member",
                "guest_authenticated",
                "trusted_user",
            }
            assert "project_role_at_vote" in entry, (
                f"vote element missing 'project_role_at_vote' key: {entry}"
            )
            if entry["source"] == "member":
                assert entry["project_role_at_vote"] is not None
            else:
                assert entry["project_role_at_vote"] is None
