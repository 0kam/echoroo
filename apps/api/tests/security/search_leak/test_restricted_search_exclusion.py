"""Restricted ``allow_detection_view`` exclusion across search paths
(T413, FR-017 / FR-019 / FR-025 / FR-025a / FR-026 / SC-018).

This module locks the Phase 9 / US4 contract that flipping a Restricted
project's ``allow_detection_view`` toggle ``ON → OFF`` immediately drops
its detections from cross-project search results — across **all three**
search paths (PostgreSQL FTS, pgvector ANN, OpenSearch). The
sub-1-second leak guarantee (SC-018) is realised because the SQL filter
encoded in :meth:`SimilaritySearchService.search_by_vector` (called with
``respect_restricted_toggle=True``) reads the freshly-committed
``restricted_config`` JSONB column and excludes the project from the
candidate set on the *very next* query — no Celery / Redis round-trip
required.

Coverage matrix:

* **pgvector**: real DB query against an ``embeddings`` row in a
  Restricted project — toggle ON → species hit, toggle OFF → empty.
  Toggle is mutated via the ``restricted_config_service.update_restricted_config``
  service (the canonical FR-024 path) and the SQL filter then reads the
  freshly-committed value within the same transaction so leak
  prevention is sub-1-second by construction.
* **PostgreSQL FTS**: covered structurally via the SearchGate
  :class:`FtsSearchAdapter` exercising the same
  ``apply_visibility_filter`` post-filter — the ``allow_detection_view=OFF``
  case yields zero hits even when the candidate provider returns rows
  for the Restricted project.
* **OpenSearch**: the production OpenSearch adapter is reserved for
  Phase 11+; the test marks the path ``skip`` with the reason recorded
  so the FR-025 "all 3 search paths" guarantee remains visible at the
  test runner level.

Project meta visibility (FR-019) is asserted alongside the species hit
exclusion: regardless of the toggle, a Restricted project's *meta*
(``GET /web-api/v1/projects/``) MUST surface to outsiders. The two
contracts are intentionally tested side-by-side so a future regression
that conflates "no species hits" with "no project meta either" is
caught at the seam.
"""

from __future__ import annotations

import os
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from echoroo.core.jwt import create_access_token
from echoroo.core.permissions import Permission
from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
from echoroo.models.enums import (
    DatasetStatus,
    DatetimeParseStatus,
    ProjectLicense,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.models.user import User
from echoroo.schemas.project import RestrictedConfigUpdateRequest
from echoroo.services.restricted_config_service import update_restricted_config
from echoroo.services.search import SimilaritySearchService
from echoroo.services.search_gate import (
    CandidateProvider,
    FtsSearchAdapter,
    OpenSearchAdapter,
    PermissionResolver,
    PgvectorSearchAdapter,
    SearchHit,
    SearchQuery,
    SimilarityServiceCandidateProvider,
)

# Perch v2 storage embedding dimension (services/search.py:_STORAGE_EMBEDDING_DIM).
_EMBEDDING_DIM = 1536

# pgbench unit vector — picks the first element so cosine similarity
# behaves predictably (1.0 against an identical vector, 0.0 against an
# orthogonal one). Reuses the convention from
# ``tests/contract/test_search_smoke.py``.
_UNIT_VECTOR = [1.0] + [0.0] * (_EMBEDDING_DIM - 1)


# ---------------------------------------------------------------------------
# Fixtures — actors. Naming mirrors Phase 8 ``t400_*`` so the Phase 9 surface
# is immediately greppable in test reports.
# ---------------------------------------------------------------------------


@pytest.fixture
async def t413_owner(db_session: AsyncSession) -> User:
    """Owner of the Restricted project under test."""
    user = User(
        email="t413owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T413 Owner",
        security_stamp="t413" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t413_owner_headers(t413_owner: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t413_owner.id)})}"
        )
    }


@pytest.fixture
async def t413_outsider(db_session: AsyncSession) -> User:
    """An authenticated user with no relationship to the Restricted project."""
    user = User(
        email="t413outsider@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T413 Outsider",
        security_stamp="t413" + "x" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Fixtures — projects + dataset + recording + embedding seeded with toggle ON.
# Tests flip the toggle OFF inline so the ON→OFF immediate-exclusion path is
# exercised end-to-end against the real DB.
# ---------------------------------------------------------------------------


def _restricted_config_on() -> dict[str, Any]:
    """Eight-key restricted_config blob with ``allow_detection_view=True``."""
    return {
        "allow_media_playback": True,
        "allow_detection_view": True,
        "mask_species_in_detection": False,
        "allow_download": False,
        "allow_export": False,
        "allow_voting_and_comments": False,
        "public_location_precision_h3_res": 9,
        "allow_precise_location_to_viewer": False,
    }


@pytest.fixture
async def t413_restricted_project(
    db_session: AsyncSession, t413_owner: User
) -> Project:
    project = Project(
        name="T413 Restricted Project",
        description="Phase 9 search exclusion coverage",
        visibility=ProjectVisibility.RESTRICTED,
        license=ProjectLicense.CC_BY,
        owner_id=t413_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_restricted_config_on(),
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t413_public_project(
    db_session: AsyncSession, t413_owner: User
) -> Project:
    project = Project(
        name="T413 Public Project",
        description="FR-019 / FR-025 foil — Public always wins",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=t413_owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config={},
        restricted_config_version=1,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def t413_restricted_embedding(
    db_session: AsyncSession,
    t413_restricted_project: Project,
    t413_owner: User,
) -> Embedding:
    """Seed a dataset / recording / embedding inside the Restricted project."""
    site = Site(
        project_id=t413_restricted_project.id,
        name="T413 Restricted Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)

    dataset = Dataset(
        project_id=t413_restricted_project.id,
        site_id=site.id,
        created_by_id=t413_owner.id,
        name="T413 Restricted Dataset",
        audio_dir="/data/audio/t413-restricted",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="t413_restricted.wav",
        path="t413_restricted.wav",
        duration=30.0,
        samplerate=48000,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)

    embedding = Embedding(
        recording_id=recording.id,
        model_name="perch",
        start_time=0.0,
        end_time=5.0,
        vector=_UNIT_VECTOR,
    )
    db_session.add(embedding)
    await db_session.commit()
    await db_session.refresh(embedding)
    return embedding


@pytest.fixture
async def t413_public_embedding(
    db_session: AsyncSession,
    t413_public_project: Project,
    t413_owner: User,
) -> Embedding:
    """Seed an identical embedding inside a Public project."""
    site = Site(
        project_id=t413_public_project.id,
        name="T413 Public Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)

    dataset = Dataset(
        project_id=t413_public_project.id,
        site_id=site.id,
        created_by_id=t413_owner.id,
        name="T413 Public Dataset",
        audio_dir="/data/audio/t413-public",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)

    recording = Recording(
        dataset_id=dataset.id,
        filename="t413_public.wav",
        path="t413_public.wav",
        duration=30.0,
        samplerate=48000,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)

    embedding = Embedding(
        recording_id=recording.id,
        model_name="perch",
        start_time=0.0,
        end_time=5.0,
        vector=_UNIT_VECTOR,
    )
    db_session.add(embedding)
    await db_session.commit()
    await db_session.refresh(embedding)
    return embedding


# ---------------------------------------------------------------------------
# Helpers — toggle flip + SQL filter probe.
# ---------------------------------------------------------------------------


async def _flip_allow_detection_view(
    db: AsyncSession, project: Project, *, value: bool
) -> None:
    """Flip ``allow_detection_view`` on the seeded project via the
    canonical FR-024 service call + commit.

    Phase 9 polish round 2 Minor 3: the previous implementation mutated
    the JSONB blob inline with ``flag_modified`` which bypassed the
    production PATCH path (no row lock, no version bump audit, no
    Celery enqueue). We now delegate to
    :func:`echoroo.services.restricted_config_service.update_restricted_config`
    so the same code path that the Web UI hits is exercised end-to-end —
    if a future refactor breaks the version bump or the JSONB write, the
    Phase 9 leak-prevention test catches it instead of silently passing
    against an inline mutation.

    The session commit happens here (the production endpoint commits
    after the call); ``trigger_post_commit_side_effects`` is intentionally
    skipped because the audit + Celery side-effects need a fresh session
    pool that the test fixture does not provide. The security-critical
    path (the JSONB write + version bump) commits before the next
    search call so the SC-018 sub-1-second leak prevention is
    structurally enforced — see :class:`TestPgvectorRestrictedExclusion`
    for the timing assertion.
    """
    after_config: dict[str, Any] = dict(project.restricted_config or {})
    after_config["allow_detection_view"] = value
    payload = RestrictedConfigUpdateRequest(**after_config)
    await update_restricted_config(
        session=db,
        project_id=project.id,
        new_config=payload,
        actor_user_id=project.owner_id,
    )
    await db.commit()
    await db.refresh(project)


# ---------------------------------------------------------------------------
# Path 1 — pgvector (real SQL against the test DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPgvectorRestrictedExclusion:
    """pgvector candidate fetch honours ``allow_detection_view`` toggle."""

    async def test_toggle_on_returns_species_hit(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """Restricted + ``allow_detection_view=ON`` → species hits visible."""
        service = SimilaritySearchService(db_session)
        results = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(results) == 1, (
            "Restricted toggle ON should expose the seeded embedding to "
            f"a cross-project caller; got {len(results)} hits"
        )
        assert results[0].embedding_id == t413_restricted_embedding.id

    async def test_toggle_off_immediately_excludes_species(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """ON → OFF flip excludes hits on the very next query (FR-025a step 1)."""
        service = SimilaritySearchService(db_session)
        # Sanity — toggle starts ON, hits visible.
        before = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(before) == 1, (
            "pre-flip baseline: Restricted toggle ON must still return the seed"
        )

        # Flip the toggle OFF + commit (SC-018: leak gap measured as
        # "same transaction"). No async sleep is required between the
        # commit and the next search call — the SQL filter reads the
        # freshly-written JSONB column.
        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )

        after = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert after == [], (
            "FR-025a step 1: Restricted ``allow_detection_view`` flipping "
            "ON → OFF must immediately drop species hits from the "
            f"candidate set; got {len(after)} hits"
        )
        # Reference the embedding so the fixture isn't "unused".
        assert t413_restricted_embedding.id is not None

    async def test_public_project_unaffected_by_toggle(
        self,
        db_session: AsyncSession,
        t413_public_project: Project,
        t413_public_embedding: Embedding,
    ) -> None:
        """Public projects always pass — toggle is a Restricted concept (FR-016)."""
        service = SimilaritySearchService(db_session)
        results = await service.search_by_vector(
            project_id=t413_public_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(results) == 1, (
            "Public projects must always return embeddings under "
            "``respect_restricted_toggle=True`` — FR-016 baseline"
        )
        assert results[0].embedding_id == t413_public_embedding.id

    async def test_toggle_off_immediately_excludes_within_one_second(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """SC-018: ON → OFF flip + next search call < 1 second wall-clock.

        Phase 9 polish round 2 Minor 3 (clock test): the previous
        ``test_toggle_off_immediately_excludes_species`` documented the
        timing guarantee as "by construction" (same transaction). We
        additionally pin the spec FR-025a / SC-018 numeric ceiling
        (1 second) with a stopwatch around (commit + next query) so a
        future regression that adds a slow side-effect (e.g. blocking
        Celery enqueue inside the toggle path, or stalling pgvector
        candidate fetch with a huge ORM eager load) breaks loudly here.

        The stopwatch uses ``time.monotonic`` to avoid wall-clock skew
        on test runners.
        """
        service = SimilaritySearchService(db_session)
        # Sanity — toggle starts ON, hits visible.
        before = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(before) == 1, "pre-flip baseline must return the seed"

        # SC-018 stopwatch — flip the toggle OFF + run the very next
        # cross-project search. The total elapsed time MUST stay below
        # 1 second on the dev DB. We measure both legs together because
        # that is the contract a real Web UI flip + reload exercises.
        start = time.monotonic()
        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )
        after = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        elapsed = time.monotonic() - start

        assert after == [], (
            "FR-025a step 1: Restricted toggle ON->OFF must drop the "
            f"seed on the very next query; got {len(after)} hit(s)"
        )
        assert elapsed < 1.0, (
            f"SC-018 1-second leak prevention violated: toggle commit + "
            f"next search took {elapsed:.3f}s (cap = 1.0s)."
        )
        assert t413_restricted_embedding.id is not None

    async def test_toggle_off_then_on_restores_hits(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """OFF → ON re-exposes hits (FR-025b: index rebuild gates re-entry).

        At the SQL gate level the re-entry is immediate; the async index
        build is a stale-cache cleanup that does not block the
        permission gate. The contract here is that the SQL filter alone
        does not "remember" a previous OFF state — flipping back to ON
        re-exposes the seed.
        """
        service = SimilaritySearchService(db_session)
        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )
        zeroed = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert zeroed == [], "OFF interim state should produce zero hits"

        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=True
        )
        after = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=True,
        )
        assert len(after) == 1, (
            "OFF → ON must restore species hits on the next query (FR-025b "
            "permission gate immediate re-entry)"
        )
        assert after[0].embedding_id == t413_restricted_embedding.id

    async def test_explicit_respect_flag_false_passes_through(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """Explicit ``respect_restricted_toggle=False`` keeps existing
        SEARCH_WITHIN_PROJECT behaviour for project members.

        Phase 9 polish round 2 Major 1 inverted the default — ``True`` is
        now the default-safe value. In-project member routes
        (``search_by_embedding_id`` / ``search_by_audio_file`` /
        ``batch_search`` / the Celery batch worker) MUST opt out of the
        SQL gate by passing ``respect_restricted_toggle=False`` so the
        non-member ``allow_detection_view`` toggle does not blank
        members of the same project (FR-019 / FR-020). This test pins
        the explicit-False branch.
        """
        service = SimilaritySearchService(db_session)
        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )
        results = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
            respect_restricted_toggle=False,
        )
        assert len(results) == 1, (
            "Explicit ``respect_restricted_toggle=False`` (in-project "
            "member route) must keep returning the seed regardless of "
            "the non-member toggle"
        )
        assert results[0].embedding_id == t413_restricted_embedding.id

    async def test_default_respect_flag_excludes_restricted_off(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """Default ``respect_restricted_toggle=True`` excludes Restricted-OFF.

        Phase 9 polish round 2 Major 1: a new caller that forgets the
        parameter MUST inherit the safe behaviour (Restricted +
        ``allow_detection_view=OFF`` filtered out at SQL level). This
        test pins the default to ``True`` so a future regression that
        flips it back to ``False`` breaks loudly here.
        """
        service = SimilaritySearchService(db_session)
        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )
        # Intentionally omit ``respect_restricted_toggle`` — the default
        # MUST be the safe one (drop hits when the toggle is OFF on a
        # Restricted project). Cross-project callers thus inherit the
        # leak-prevention contract for free.
        results = await service.search_by_vector(
            project_id=t413_restricted_project.id,
            query_vector=_UNIT_VECTOR,
            model_name="perch",
            limit=10,
            min_similarity=0.0,
        )
        assert results == [], (
            "Default ``respect_restricted_toggle`` should now be True; "
            f"a Restricted-OFF project must return zero hits, got "
            f"{len(results)} hit(s)"
        )
        # Reference the embedding so the fixture isn't "unused".
        assert t413_restricted_embedding.id is not None


# ---------------------------------------------------------------------------
# Path 1b — pgvector via SearchGate adapter (FR-025 single-entrypoint
# guarantee). Wires :class:`SimilarityServiceCandidateProvider` into the
# :class:`PgvectorSearchAdapter` so the SQL filter and the post-filter
# work together.
# ---------------------------------------------------------------------------


class _AlwaysAllowResolver(PermissionResolver):
    """Resolver that grants ``VIEW_DETECTION`` to every project for tests."""

    async def effective_permissions_for_project(
        self,
        db: AsyncSession,  # noqa: ARG002 - protocol parity
        principal: Any,  # noqa: ARG002
        project_id: UUID,  # noqa: ARG002
    ) -> frozenset[Permission]:
        return frozenset({Permission.VIEW_DETECTION})


class _DenyAllResolver(PermissionResolver):
    """Resolver that grants nothing — proves the post-filter clamps as well."""

    async def effective_permissions_for_project(
        self,
        db: AsyncSession,  # noqa: ARG002
        principal: Any,  # noqa: ARG002
        project_id: UUID,  # noqa: ARG002
    ) -> frozenset[Permission]:
        return frozenset()


@pytest.mark.asyncio
class TestPgvectorAdapterRestrictedExclusion:
    """SearchGate ``PgvectorSearchAdapter`` honours the Restricted toggle."""

    async def test_adapter_excludes_restricted_when_toggle_off(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """``allow_detection_view=OFF`` → empty even with permissive resolver."""
        provider = SimilarityServiceCandidateProvider(
            service=SimilaritySearchService(db_session),
            project_id=t413_restricted_project.id,
            model_name="perch",
            min_similarity=0.0,
        )
        adapter = PgvectorSearchAdapter(
            resolver=_AlwaysAllowResolver(),
            candidate_provider=provider,
        )

        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )
        hits = await adapter.search(
            db=db_session,
            principal=None,
            query=SearchQuery(
                embedding=tuple(_UNIT_VECTOR),
                limit=5,
                project_id=t413_restricted_project.id,
            ),
        )
        assert hits == [], (
            "PgvectorSearchAdapter must drop Restricted projects with "
            f"``allow_detection_view=false``; got {hits!r}"
        )
        assert t413_restricted_embedding.id is not None

    async def test_adapter_returns_hit_when_toggle_on(
        self,
        db_session: AsyncSession,
        t413_restricted_project: Project,
        t413_restricted_embedding: Embedding,
    ) -> None:
        """``allow_detection_view=ON`` → SearchGate adapter returns the seed."""
        provider = SimilarityServiceCandidateProvider(
            service=SimilaritySearchService(db_session),
            project_id=t413_restricted_project.id,
            model_name="perch",
            min_similarity=0.0,
        )
        adapter = PgvectorSearchAdapter(
            resolver=_AlwaysAllowResolver(),
            candidate_provider=provider,
        )
        hits = await adapter.search(
            db=db_session,
            principal=None,
            query=SearchQuery(
                embedding=tuple(_UNIT_VECTOR),
                limit=5,
                project_id=t413_restricted_project.id,
            ),
        )
        assert len(hits) == 1, (
            "PgvectorSearchAdapter must return the seed when "
            f"``allow_detection_view=true``; got {hits!r}"
        )
        assert hits[0].detection_id == t413_restricted_embedding.id

    async def test_adapter_post_filter_overrides_sql_pass(
        self,
        db_session: AsyncSession,
        t413_public_project: Project,
        t413_public_embedding: Embedding,
    ) -> None:
        """Even when SQL passes (Public), a deny resolver clamps to empty.

        Belt-and-braces — the SearchGate post-filter MUST apply on top
        of the SQL filter. Anyone wiring a future cross-project router
        that forgets ``apply_visibility_filter`` would otherwise leak
        Public hits to denied principals.
        """
        provider = SimilarityServiceCandidateProvider(
            service=SimilaritySearchService(db_session),
            project_id=t413_public_project.id,
            model_name="perch",
            min_similarity=0.0,
        )
        adapter = PgvectorSearchAdapter(
            resolver=_DenyAllResolver(),
            candidate_provider=provider,
        )
        hits = await adapter.search(
            db=db_session,
            principal=None,
            query=SearchQuery(
                embedding=tuple(_UNIT_VECTOR),
                limit=5,
                project_id=t413_public_project.id,
            ),
        )
        assert hits == [], (
            "Deny-all resolver must clamp Public hits to empty "
            f"(post-filter belt-and-braces); got {hits!r}"
        )
        assert t413_public_embedding.id is not None


# ---------------------------------------------------------------------------
# Path 2 — PostgreSQL FTS via SearchGate (uses fake candidate provider —
# the production FTS adapter wiring is reserved for Phase 11 once the
# detection FTS index lands; the SearchGate post-filter contract is what
# we lock here, mirroring the pattern in
# ``test_search_gate_isolation.py``).
# ---------------------------------------------------------------------------


class _FtsFakeProvider(CandidateProvider):
    """Returns canned FTS hits regardless of query text."""

    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits

    async def fetch_fts(
        self,
        db: AsyncSession,  # noqa: ARG002
        query: SearchQuery,  # noqa: ARG002
    ) -> list[SearchHit]:
        return list(self._hits)

    async def fetch_pgvector(
        self,
        db: AsyncSession,  # noqa: ARG002
        query: SearchQuery,  # noqa: ARG002
    ) -> list[SearchHit]:
        return list(self._hits)


@pytest.mark.asyncio
class TestFtsRestrictedExclusion:
    """FTS adapter ``apply_visibility_filter`` enforces the toggle.

    The production FTS query (research §3 / FR-025a `WHERE
    projects.allow_detection_view=true`) is reserved for Phase 11; the
    contract we lock here is the SearchGate post-filter behaviour
    against a fake candidate provider, which is the same plumbing the
    production adapter will reuse.
    """

    async def test_fts_post_filter_excludes_restricted_when_resolver_denies(
        self, t413_restricted_project: Project
    ) -> None:
        """Resolver returning empty perms → no hits (mirrors toggle OFF)."""
        candidate_hits = [
            SearchHit(
                detection_id=uuid4(),
                recording_id=uuid4(),
                project_id=t413_restricted_project.id,
                score=0.9,
                payload={"species": "Strix occidentalis"},
            )
        ]
        adapter = FtsSearchAdapter(
            resolver=_DenyAllResolver(),
            candidate_provider=_FtsFakeProvider(candidate_hits),
        )
        results = await adapter.search(
            db=None,  # type: ignore[arg-type]
            principal=None,
            query=SearchQuery(query="strix", limit=10),
        )
        assert results == [], (
            "FTS post-filter must clamp candidate hits when "
            f"``allow_detection_view=OFF`` semantics apply; got {results!r}"
        )

    async def test_fts_post_filter_returns_hit_when_resolver_allows(
        self, t413_restricted_project: Project
    ) -> None:
        """Resolver granting VIEW_DETECTION → hit survives (toggle ON case)."""
        candidate_hits = [
            SearchHit(
                detection_id=uuid4(),
                recording_id=uuid4(),
                project_id=t413_restricted_project.id,
                score=0.9,
                payload={"species": "Strix occidentalis"},
            )
        ]
        adapter = FtsSearchAdapter(
            resolver=_AlwaysAllowResolver(),
            candidate_provider=_FtsFakeProvider(candidate_hits),
        )
        results = await adapter.search(
            db=None,  # type: ignore[arg-type]
            principal=None,
            query=SearchQuery(query="strix", limit=10),
        )
        assert len(results) == 1, (
            "FTS post-filter must let the hit through when the resolver "
            f"grants VIEW_DETECTION; got {results!r}"
        )
        assert results[0].project_id == t413_restricted_project.id


# ---------------------------------------------------------------------------
# Path 3 — OpenSearch (deferral; FR-025 explicit "all 3 paths" requirement).
# ---------------------------------------------------------------------------


@pytest.mark.skip(
    reason=(
        "OpenSearch path is reserved for Phase 11+ — the OpenSearchAdapter "
        "is a stub that raises NotImplementedError (services/search_gate.py:"
        "OpenSearchAdapter). Test placeholder kept here so the FR-025 "
        '"all 3 search paths" guarantee remains visible at the test runner '
        "level; the contract test against the stub itself lives in "
        "test_search_gate_isolation.py::test_opensearch_adapter_raises_not_implemented."
    )
)
@pytest.mark.asyncio
async def test_opensearch_path_restricted_exclusion() -> None:
    """Reserved for Phase 11 OpenSearch wiring."""
    adapter = OpenSearchAdapter()
    # When the adapter ships, it MUST honour the same Restricted toggle
    # filter at the index-pull level (research §3, FR-025a). For now we
    # document the contract at skip level so a future PR cannot land
    # without claiming this slot.
    await adapter.search(
        db=None,  # type: ignore[arg-type]
        principal=None,
        query=SearchQuery(query="any"),
    )


# ---------------------------------------------------------------------------
# FR-019 cross-cut — Restricted project meta still surfaces when toggle OFF.
# Locks the seam between "no species hits" (FR-025) and "still discoverable"
# (FR-019) so a future regression cannot collapse one into the other.
# ---------------------------------------------------------------------------


_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


@pytest.mark.asyncio
class TestRestrictedMetaStillVisibleWhenToggleOff:
    """FR-019: Restricted project meta MUST stay enumerable when
    ``allow_detection_view=OFF`` — the toggle gates *species* / detection
    rows, not project-level discovery.
    """

    async def test_guest_list_includes_restricted_when_toggle_off(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t413_restricted_project: Project,
    ) -> None:
        """Flip the toggle OFF, then GET /web-api/v1/projects/ as Guest."""
        await _flip_allow_detection_view(
            db_session, t413_restricted_project, value=False
        )
        response = await client.get("/web-api/v1/projects/")
        assert response.status_code == 200, response.text
        ids = {item["id"] for item in response.json()["items"]}
        assert str(t413_restricted_project.id) in ids, (
            "FR-019 violation: Restricted project meta MUST surface to "
            "Guest enumeration even when ``allow_detection_view=OFF``"
        )
