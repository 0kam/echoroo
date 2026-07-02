"""Guest-authenticated vote source contract (T310, FR-037 / FR-038).

Spec FR-037 mandates that every vote captures its ``source`` (one of
``member`` / ``guest_authenticated`` / ``trusted_user``) and a member-only
``project_role_at_vote`` snapshot at *creation time*. FR-037 further
requires the columns to be **immutable** — re-votes preserve the original
values even if the voter's relationship to the project has changed.

FR-038 mandates per-source aggregate counts in the vote summary response so
the UI can render the 3-source breakdown described in spec.md US2 #3.

Tests:

1. **Member vote** → ``source='member'``, ``project_role_at_vote`` = real
   role string from ``project_members``.
2. **Authenticated non-member vote on a Public project** →
   ``source='guest_authenticated'``, ``project_role_at_vote=None``.
3. **Mixed vote summary** → response carries the FR-038 per-source count
   fields with the right values.
4. **Re-vote immutability** → changing the vote value does NOT recompute
   ``source`` / ``project_role_at_vote`` (FR-037).

W2-3 PR-17 (2026-07-02): the ``/api/v1/.../detections/{id}/votes`` routes
were unmounted; the tests now target the surviving ``/web-api/v1`` BFF mount
(which delegates to the same legacy gate + service code), authenticating via
a CSRF-capable ``bff_session_headers`` session instead of a plain Bearer.
This module stays skip-marked under the Phase 14+ recording_annotations
deferral, so the migration is not exercised yet.
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
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    AnnotationVoteSource,
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
# Shared restricted_config (unused for Public but required by CHECK).
# ---------------------------------------------------------------------------

_PUBLIC_RESTRICTED_CONFIG: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Fixtures — actors
# ---------------------------------------------------------------------------


@pytest.fixture
async def t310_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t310owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T310 Owner",
        security_stamp="t310" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t310_member(db_session: AsyncSession) -> User:
    user = User(
        email="t310member@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T310 Member",
        security_stamp="t310" + "m" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def t310_guest_authenticated(db_session: AsyncSession) -> User:
    user = User(
        email="t310guestauth@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T310 Guest Authenticated",
        security_stamp="t310" + "g" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Fixtures — project / annotation graph
# ---------------------------------------------------------------------------


@pytest.fixture
async def t310_public_project(
    db_session: AsyncSession, t310_owner: User
) -> Project:
    project = Project(
        name="T310 Public Project",
        description="Phase 6 Guest-authenticated vote contract",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=t310_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_PUBLIC_RESTRICTED_CONFIG,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t310_member_membership(
    db_session: AsyncSession,
    t310_public_project: Project,
    t310_member: User,
    t310_owner: User,
) -> ProjectMember:
    membership = ProjectMember(
        user_id=t310_member.id,
        project_id=t310_public_project.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=t310_owner.id,
    )
    db_session.add(membership)
    await db_session.commit()
    await db_session.refresh(membership)
    return membership


@pytest.fixture
async def t310_site(
    db_session: AsyncSession, t310_public_project: Project
) -> Site:
    site = Site(
        project_id=t310_public_project.id,
        name="T310 Site",
        h3_index_member="89283082803ffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def t310_dataset(
    db_session: AsyncSession,
    t310_public_project: Project,
    t310_site: Site,
    t310_owner: User,
) -> Dataset:
    dataset = Dataset(
        project_id=t310_public_project.id,
        site_id=t310_site.id,
        created_by_id=t310_owner.id,
        name="T310 Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def t310_recording(
    db_session: AsyncSession, t310_dataset: Dataset
) -> Recording:
    rec = Recording(
        dataset_id=t310_dataset.id,
        filename="t310.wav",
        path="t310.wav",
        duration=10.0,
        samplerate=44100,
        channels=1,
    )
    db_session.add(rec)
    await db_session.commit()
    await db_session.refresh(rec)
    return rec


@pytest.fixture
async def t310_tag(
    db_session: AsyncSession, t310_public_project: Project
) -> Tag:
    tag = Tag(
        project_id=t310_public_project.id,
        name="Cardinalis cardinalis",
        category=TagCategory.SPECIES,
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def t310_annotation(
    db_session: AsyncSession, t310_recording: Recording, t310_tag: Tag
) -> Annotation:
    ann = Annotation(
        recording_id=t310_recording.id,
        tag_id=t310_tag.id,
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
# Fixtures — auth headers
# ---------------------------------------------------------------------------


async def _bff_headers(
    client: AsyncClient, db: AsyncSession, user: User
) -> dict[str, str]:
    """CSRF-capable ``/web-api/v1`` session headers for ``user``.

    ``bff_session_headers`` is imported locally (not at module scope) so the
    new W2-3 PR-17 dependency does not add an E402 module-level import after
    this suite's ``pytestmark`` skip block (matching the PR-16 precedent).
    """
    from tests.contract.conftest import bff_session_headers

    return await bff_session_headers(client, db, user)


@pytest.fixture
async def t310_member_headers(
    client: AsyncClient, db_session: AsyncSession, t310_member: User
) -> dict[str, str]:
    return await _bff_headers(client, db_session, t310_member)


@pytest.fixture
async def t310_guest_authenticated_headers(
    client: AsyncClient, db_session: AsyncSession, t310_guest_authenticated: User
) -> dict[str, str]:
    return await _bff_headers(client, db_session, t310_guest_authenticated)


@pytest.fixture
async def t310_owner_headers(
    client: AsyncClient, db_session: AsyncSession, t310_owner: User
) -> dict[str, str]:
    return await _bff_headers(client, db_session, t310_owner)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fetch_vote_row(
    db: AsyncSession, annotation_id: UUID, user_id: UUID
) -> AnnotationVote | None:
    result = await db.execute(
        sa.select(AnnotationVote).where(
            AnnotationVote.annotation_id == annotation_id,
            # Phase 13 P1.5 (T804): renamed from ``user_id``.
            AnnotationVote.voter_user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def _fetch_vote_columns(
    db: AsyncSession, annotation_id: UUID, user_id: UUID
) -> tuple[UUID, str, str, str | None] | None:
    """Fetch ``(id, vote, source, project_role_at_vote)`` via raw SQL.

    Sidesteps the ORM identity-map / lazy-load semantics so the test body
    can compare values across two API round-trips that committed in
    different sessions.
    """
    result = await db.execute(
        sa.text(
            "SELECT id, vote::text, source::text, project_role_at_vote::text "
            "FROM annotation_votes "
            # Phase 13 P1.5 (T804): renamed from ``user_id`` to ``voter_user_id``.
            "WHERE annotation_id = :ann AND voter_user_id = :uid"
        ),
        {"ann": annotation_id, "uid": user_id},
    )
    row = result.first()
    if row is None:
        return None
    return row[0], row[1], row[2], row[3]


def _vote_endpoint(project_id: UUID, detection_id: UUID) -> str:
    return f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes"


# ---------------------------------------------------------------------------
# Tests — FR-037 source classification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVoteSourceMember:
    """Members get ``source='member'`` and a non-null role snapshot."""

    async def test_member_vote_persists_member_source_and_role(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t310_public_project: Project,
        t310_member: User,
        t310_member_membership: ProjectMember,
        t310_annotation: Annotation,
        t310_member_headers: dict[str, str],
    ) -> None:
        response = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_member_headers,
            json={"vote": "agree"},
        )
        assert response.status_code in {200, 201}, response.text

        row = await _fetch_vote_row(
            db_session, t310_annotation.id, t310_member.id
        )
        assert row is not None
        assert row.source == AnnotationVoteSource.MEMBER, (
            f"Expected source='member', got {row.source!r}"
        )
        assert row.project_role_at_vote == ProjectMemberRole.MEMBER, (
            f"Expected project_role_at_vote='member', "
            f"got {row.project_role_at_vote!r}"
        )

    async def test_owner_vote_persists_member_source(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t310_public_project: Project,
        t310_owner: User,
        t310_annotation: Annotation,
        t310_owner_headers: dict[str, str],
    ) -> None:
        """Owners aren't in project_members but FR-037 still classifies them as member."""
        response = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_owner_headers,
            json={"vote": "agree"},
        )
        assert response.status_code in {200, 201}, response.text

        row = await _fetch_vote_row(
            db_session, t310_annotation.id, t310_owner.id
        )
        assert row is not None
        assert row.source == AnnotationVoteSource.MEMBER
        # Owner snapshot uses ADMIN as the closest persisted role enum
        # (Owner is derived from project.owner_id, not project_members).
        assert row.project_role_at_vote is not None


@pytest.mark.asyncio
class TestVoteSourceGuestAuthenticated:
    """Authenticated non-members of a Public project → guest_authenticated."""

    async def test_guest_authenticated_vote_persists_guest_source(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t310_public_project: Project,
        t310_guest_authenticated: User,
        t310_annotation: Annotation,
        t310_guest_authenticated_headers: dict[str, str],
    ) -> None:
        response = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_guest_authenticated_headers,
            json={"vote": "agree"},
        )
        assert response.status_code in {200, 201}, response.text

        row = await _fetch_vote_row(
            db_session, t310_annotation.id, t310_guest_authenticated.id
        )
        assert row is not None
        assert row.source == AnnotationVoteSource.GUEST_AUTHENTICATED, (
            f"Expected source='guest_authenticated' for non-member voter, "
            f"got {row.source!r}"
        )
        assert row.project_role_at_vote is None, (
            f"Non-member votes must have project_role_at_vote=None, "
            f"got {row.project_role_at_vote!r}"
        )


# ---------------------------------------------------------------------------
# Tests — FR-038 per-source aggregate counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVoteSummaryPerSourceCounts:
    """Vote summary exposes member / guest_authenticated / trusted_user counts."""

    async def test_summary_includes_three_source_counts(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t310_public_project: Project,
        t310_member: User,
        t310_member_membership: ProjectMember,
        t310_guest_authenticated: User,
        t310_annotation: Annotation,
        t310_member_headers: dict[str, str],
        t310_guest_authenticated_headers: dict[str, str],
    ) -> None:
        # 1 member agree + 1 guest_authenticated disagree.
        member_resp = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_member_headers,
            json={"vote": "agree"},
        )
        assert member_resp.status_code in {200, 201}

        guest_resp = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_guest_authenticated_headers,
            json={"vote": "disagree"},
        )
        assert guest_resp.status_code in {200, 201}
        body = guest_resp.json()

        # FR-038: response surfaces per-source counts. The keys MUST be the
        # six fields below — anything else is a contract regression.
        for key in (
            "member_agree",
            "member_disagree",
            "guest_authenticated_agree",
            "guest_authenticated_disagree",
            "trusted_user_agree",
            "trusted_user_disagree",
        ):
            assert key in body, f"VoteSummaryResponse is missing FR-038 key {key!r}"

        assert body["member_agree"] == 1
        assert body["member_disagree"] == 0
        assert body["guest_authenticated_agree"] == 0
        assert body["guest_authenticated_disagree"] == 1
        # Trusted not exercised in Phase 6 (US5 lands the model).
        assert body["trusted_user_agree"] == 0
        assert body["trusted_user_disagree"] == 0


# ---------------------------------------------------------------------------
# Tests — FR-037 immutability of source / role on re-vote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestVoteSourceImmutableOnRevote:
    """Re-voting MUST NOT recompute source / project_role_at_vote (FR-037)."""

    async def test_revote_preserves_source_and_role(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t310_public_project: Project,
        t310_guest_authenticated: User,
        t310_annotation: Annotation,
        t310_guest_authenticated_headers: dict[str, str],
    ) -> None:
        # 1) First cast: guest_authenticated agree.
        first = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_guest_authenticated_headers,
            json={"vote": "agree"},
        )
        assert first.status_code in {200, 201}, first.text

        # Read source/role via raw SQL so the result is independent of the
        # ORM identity map (the endpoint committed in its own session).
        original = await _fetch_vote_columns(
            db_session, t310_annotation.id, t310_guest_authenticated.id
        )
        assert original is not None
        original_id, original_vote, original_source, original_role = original
        assert original_source == AnnotationVoteSource.GUEST_AUTHENTICATED.value
        assert original_role is None
        # Phase 13 P1.5 (T804): ``vote`` is now smallint at the DB layer.
        # ``::text`` cast renders the canonical mapping AGREE=1.
        assert original_vote == "1"

        # 2) Re-vote: change agree → disagree. Even if the upstream
        #    classification logic changed, FR-037 says source / role
        #    must remain frozen at first-cast values.
        second = await client.post(
            _vote_endpoint(t310_public_project.id, t310_annotation.id),
            headers=t310_guest_authenticated_headers,
            json={"vote": "disagree"},
        )
        assert second.status_code in {200, 201}, second.text

        revoted = await _fetch_vote_columns(
            db_session, t310_annotation.id, t310_guest_authenticated.id
        )
        assert revoted is not None
        revoted_id, revoted_vote, revoted_source, revoted_role = revoted
        # Same row — re-votes upsert in place per FR-037.
        assert revoted_id == original_id
        # vote value DID change ...
        # Phase 13 P1.5: DISAGREE = -1 (smallint canonical mapping).
        assert revoted_vote == "-1"
        # ... but source + role are FROZEN.
        assert revoted_source == original_source, (
            f"Re-vote leaked source mutation: was {original_source!r}, "
            f"now {revoted_source!r}"
        )
        assert revoted_role == original_role, (
            f"Re-vote leaked project_role_at_vote mutation: "
            f"was {original_role!r}, now {revoted_role!r}"
        )
