"""Real-DB regression test for detection voting (P2 — launch-unblocker).

This suite is the regression guard for the P2 annotation-consolidation fix.
The detection-vote endpoints key on a ``recording_annotations_DEFERRED`` id
(emitted by both the detection review grid and the search-results review
screen), but the BOLA guard previously probed the WRONG minimal ``annotations``
table and the ``annotation_votes`` FK pointed there too — so every real vote
404'd at the guard or failed the FK. Migration 0028 repoints the FK and the
guards now probe :class:`RecordingAnnotation`.

CRITICAL: unlike the transport-only smoke tests in
``test_projects_votes_smoke.py`` (which monkeypatch the legacy handler and the
gate), this suite uses NO monkeypatch of the guard / handler / gate. It seeds
real rows and drives the full DB-backed legacy ``/api/v1`` handler — the same
handler the ``/web-api/v1`` BFF delegates to — so the existence guard, the
``annotation_votes`` FK, and the consensus recompute are all exercised
end-to-end. The bug shipped precisely because the prior tests monkeypatched the
guard away; this test would have caught it.

Auth uses the integration ``client`` fixture's plain-JWT Bearer shim against
``/api/v1`` (the BFF cookie+CSRF transport is covered separately by the smoke
suite). The authorization gate, BOLA guard, vote service, and FK are identical
on both mounts.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionSource,
    DetectionStatus,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.site import Site
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio


_RESTRICTED_CONFIG = {
    "allow_media_playback": True,
    "allow_detection_view": True,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": True,
    "public_location_precision_h3_res": 5,
    "allow_precise_location_to_viewer": False,
}


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str, stamp: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=email.split("@", 1)[0],
        security_stamp=stamp,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_project(db: AsyncSession, owner: User, name: str) -> Project:
    project = Project(
        name=name,
        description="P2 vote real-DB test",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner.id,
        restricted_config=dict(_RESTRICTED_CONFIG),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _make_recording_annotation(
    db: AsyncSession, project: Project, owner: User
) -> RecordingAnnotation:
    """Seed a project -> dataset -> recording -> recording_annotation chain.

    Returns the RecordingAnnotation; its id is the value the detection-vote
    endpoints accept (the canonical ``recording_annotations_DEFERRED`` id-space).
    """
    site = Site(
        project_id=project.id,
        name=f"Site {project.name}",
        h3_index_member="8928308280fffff",
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)

    dataset = Dataset(
        project_id=project.id,
        site_id=site.id,
        created_by_id=owner.id,
        name=f"Dataset {project.name}",
        visibility=DatasetVisibility.PRIVATE,
        status=DatasetStatus.COMPLETED,
    )
    db.add(dataset)
    await db.commit()
    await db.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="vote_test.wav",
        path=f"recordings/{project.id}/{dataset.id}/vote_test.wav",
        duration=60.0,
        samplerate=44100,
        channels=1,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(recording)

    annotation = RecordingAnnotation(
        recording_id=recording.id,
        source=DetectionSource.HUMAN,
        status=DetectionStatus.UNREVIEWED,
        start_time=0.0,
        end_time=3.0,
        confidence=0.9,
    )
    db.add(annotation)
    await db.commit()
    await db.refresh(annotation)
    return annotation


async def _add_member(
    db: AsyncSession,
    project: Project,
    user: User,
    role: ProjectMemberRole,
    invited_by: User,
) -> None:
    db.add(
        ProjectMember(
            user_id=user.id,
            project_id=project.id,
            role=role,
            invited_by_id=invited_by.id,
        )
    )
    await db.commit()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "p2vote_owner@example.com", "o" * 64)


@pytest_asyncio.fixture
async def member(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "p2vote_member@example.com", "m" * 64)


@pytest_asyncio.fixture
async def viewer(db_session: AsyncSession) -> User:
    return await _make_user(db_session, "p2vote_viewer@example.com", "v" * 64)


@pytest_asyncio.fixture
async def project(db_session: AsyncSession, owner: User) -> Project:
    return await _make_project(db_session, owner, "P2 Vote Project")


@pytest_asyncio.fixture
async def annotation(
    db_session: AsyncSession, project: Project, owner: User
) -> RecordingAnnotation:
    return await _make_recording_annotation(db_session, project, owner)


@pytest_asyncio.fixture
async def member_in_project(
    db_session: AsyncSession, project: Project, member: User, owner: User
) -> User:
    await _add_member(db_session, project, member, ProjectMemberRole.MEMBER, owner)
    return member


@pytest_asyncio.fixture
async def viewer_in_project(
    db_session: AsyncSession, project: Project, viewer: User, owner: User
) -> User:
    await _add_member(db_session, project, viewer, ProjectMemberRole.VIEWER, owner)
    return viewer


def _votes_url(project_id: UUID, annotation_id: UUID) -> str:
    return f"/api/v1/projects/{project_id}/detections/{annotation_id}/votes"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_cast_get_delete_vote_real_db(
    client: AsyncClient,
    db_session: AsyncSession,
    project: Project,
    annotation: RecordingAnnotation,
    member_in_project: User,
) -> None:
    """Full happy path: POST persists a vote keyed on the recording_annotation id.

    Asserts the FK is satisfied (no IntegrityError), a row lands in
    ``annotation_votes`` with ``annotation_id == rad_id`` and ``project_id ==
    pid``, GET reflects the cast, and DELETE removes the row.
    """
    url = _votes_url(project.id, annotation.id)
    headers = _headers(member_in_project)

    # POST → 200 and a persisted vote row keyed on the recording_annotation id.
    resp = await client.post(url, headers=headers, json={"vote": "agree"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["annotation_id"] == str(annotation.id)
    assert body["agree_count"] == 1

    row = (
        await db_session.execute(
            select(AnnotationVote).where(
                AnnotationVote.annotation_id == annotation.id,
                AnnotationVote.voter_user_id == member_in_project.id,
            )
        )
    ).scalar_one_or_none()
    assert row is not None, "vote row must persist keyed on the recording_annotation id"
    assert row.annotation_id == annotation.id
    assert row.project_id == project.id

    # GET → summary reflects the cast.
    resp = await client.get(url, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["agree_count"] == 1

    # DELETE → 200 and the row is gone.
    resp = await client.delete(url, headers=headers)
    assert resp.status_code == 200, resp.text

    gone = (
        await db_session.execute(
            select(AnnotationVote).where(
                AnnotationVote.annotation_id == annotation.id,
                AnnotationVote.voter_user_id == member_in_project.id,
            )
        )
    ).scalar_one_or_none()
    assert gone is None, "vote row must be removed after DELETE"


async def test_cast_vote_cross_project_is_404_bola(
    client: AsyncClient,
    db_session: AsyncSession,
    owner: User,
    member_in_project: User,
    project: Project,
) -> None:
    """BOLA: a recording_annotation id from a DIFFERENT project → 404.

    The voter is a Member of ``project`` (so the VOTE gate passes), but supplies
    a recording_annotation id owned by ``other_project``. The repointed
    project-scoped guard must reject it (no IDOR).
    """
    other_owner = await _make_user(db_session, "p2vote_owner2@example.com", "z" * 64)
    other_project = await _make_project(db_session, other_owner, "P2 Other Project")
    other_annotation = await _make_recording_annotation(
        db_session, other_project, other_owner
    )

    # URL uses project (where the member has VOTE) but the cross-project id.
    url = _votes_url(project.id, other_annotation.id)
    resp = await client.post(
        url, headers=_headers(member_in_project), json={"vote": "agree"}
    )
    assert resp.status_code == 404, resp.text


async def test_cast_vote_viewer_is_403(
    client: AsyncClient,
    project: Project,
    annotation: RecordingAnnotation,
    viewer_in_project: User,
) -> None:
    """A VIEWER (no VOTE permission) is rejected at the gate with 403."""
    url = _votes_url(project.id, annotation.id)
    resp = await client.post(
        url, headers=_headers(viewer_in_project), json={"vote": "agree"}
    )
    assert resp.status_code == 403, resp.text


async def test_cast_vote_unknown_annotation_is_404(
    client: AsyncClient,
    project: Project,
    member_in_project: User,
) -> None:
    """An unknown recording_annotation id → 404 (guard miss)."""
    url = _votes_url(project.id, uuid4())
    resp = await client.post(
        url, headers=_headers(member_in_project), json={"vote": "agree"}
    )
    assert resp.status_code == 404, resp.text
