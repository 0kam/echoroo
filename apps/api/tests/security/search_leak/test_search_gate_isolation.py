"""SearchGate isolation matrix (T091, FR-025 / FR-025a, SC-018).

The 3 adapters (FTS, pgvector, OpenSearch stub) MUST share the same
permission post-filter so that:

    * Anonymous principals only see Public project hits where
      ``allow_detection_view`` is implicitly ON.
    * Members of a project where ``allow_detection_view`` is OFF see
      NOTHING from that project even though they hold project membership
      — the toggle gates the leak (Rev.3.2 §Restricted Toggle).
    * Members of a Restricted project they belong to see their own hits.
    * The OpenSearch adapter is a stub raising ``NotImplementedError``.

The tests deliberately mock the SQL candidate provider and the
permission resolver so the unit test exercises the gate's *logic* in
isolation. Phase 3 lays the SQL on top.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import Permission
from echoroo.services.search_gate import (
    CandidateProvider,
    FtsSearchAdapter,
    OpenSearchAdapter,
    PermissionResolver,
    PgvectorSearchAdapter,
    SearchHit,
    SearchQuery,
    sanitize_payload,
)

# Mypy-friendly placeholder for the AsyncSession argument: the tests stub
# every code path that would touch the DB, so a cast None is fine.
_NO_DB: AsyncSession = cast(AsyncSession, None)

# ---------------------------------------------------------------------------
# Fixtures: 3-project topology
# ---------------------------------------------------------------------------

# Project A — Public (allow_detection_view implicitly ON).
PROJECT_A: UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
# Project B — Public on paper but the toggle is OFF (Restricted with
# allow_detection_view=False covers the same isolation rule).
PROJECT_B: UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
# Project C — Restricted. Only members can view detections.
PROJECT_C: UUID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@dataclass(frozen=True)
class FakePrincipal:
    """Structural ``Principal`` for tests (mirrors auth_router.Principal)."""

    user_id: UUID | None
    auth_kind: str = "session"
    security_stamp: str | None = None
    api_key_id: UUID | None = None
    scopes: tuple[str, ...] = ()


@dataclass
class FakeResolver(PermissionResolver):
    """Returns canned permission sets keyed on ``(user_id, project_id)``.

    Anonymous (``user_id=None``) gets the per-project anon set.
    """

    # (user_id, project_id) -> permissions
    member_perms: dict[tuple[UUID | None, UUID], frozenset[Permission]] = field(default_factory=dict)
    # project_id -> permissions for unauthenticated principals
    anon_perms: dict[UUID, frozenset[Permission]] = field(default_factory=dict)

    async def effective_permissions_for_project(
        self,
        db: Any,
        principal: Any,
        project_id: UUID,
    ) -> frozenset[Permission]:
        if principal is None or getattr(principal, "user_id", None) is None:
            return self.anon_perms.get(project_id, frozenset())
        key = (principal.user_id, project_id)
        return self.member_perms.get(key, self.anon_perms.get(project_id, frozenset()))


@dataclass
class FakeCandidateProvider(CandidateProvider):
    """Returns the same canned hit list for FTS and pgvector calls."""

    hits: list[SearchHit]

    async def fetch_fts(self, db: Any, query: SearchQuery) -> list[SearchHit]:
        return list(self.hits)

    async def fetch_pgvector(self, db: Any, query: SearchQuery) -> list[SearchHit]:
        return list(self.hits)


def _hit(project_id: UUID, score: float = 0.8) -> SearchHit:
    return SearchHit(
        detection_id=uuid4(),
        recording_id=uuid4(),
        project_id=project_id,
        score=score,
        payload={"species": "Cyanocitta cristata"},
    )


@pytest.fixture()
def populated_hits() -> list[SearchHit]:
    """3 candidates per project — 9 total, mixed in source order."""
    return [
        _hit(PROJECT_A),
        _hit(PROJECT_B),
        _hit(PROJECT_C),
        _hit(PROJECT_A),
        _hit(PROJECT_B),
        _hit(PROJECT_C),
        _hit(PROJECT_A),
        _hit(PROJECT_B),
        _hit(PROJECT_C),
    ]


@pytest.fixture()
def anonymous_resolver() -> FakeResolver:
    """Anon: A allows VIEW_DETECTION; B (toggle OFF) and C (Restricted) do not."""
    return FakeResolver(
        anon_perms={
            PROJECT_A: frozenset({Permission.VIEW_DETECTION}),
            PROJECT_B: frozenset(),  # toggle off
            PROJECT_C: frozenset(),  # restricted, no public access
        },
        member_perms={},
    )


@pytest.fixture()
def member_a_resolver() -> tuple[FakeResolver, UUID]:
    user = uuid4()
    return FakeResolver(
        anon_perms={
            PROJECT_A: frozenset({Permission.VIEW_DETECTION}),
            PROJECT_B: frozenset(),
            PROJECT_C: frozenset(),
        },
        member_perms={
            (user, PROJECT_A): frozenset({Permission.VIEW_DETECTION}),
        },
    ), user


@pytest.fixture()
def member_b_toggle_off_resolver() -> tuple[FakeResolver, UUID]:
    """Member of B but toggle OFF — VIEW_DETECTION must be empty.

    The fact that they are a "member" of B in some other system is
    irrelevant: the resolver only returns permissions the gate cares
    about, and ``compute_effective_permissions`` for a Restricted
    project with the toggle off does NOT yield VIEW_DETECTION even for
    members. We model that by leaving VIEW_DETECTION out of the set.
    """
    user = uuid4()
    return FakeResolver(
        anon_perms={PROJECT_A: frozenset(), PROJECT_B: frozenset(), PROJECT_C: frozenset()},
        member_perms={
            # Project B membership grants other perms, but NOT
            # VIEW_DETECTION while ``allow_detection_view`` is OFF for the
            # configured project.
            (user, PROJECT_B): frozenset(
                {Permission.VIEW_PROJECT_METADATA, Permission.VIEW_DATASET_LIST}
            ),
        },
    ), user


@pytest.fixture()
def member_c_resolver() -> tuple[FakeResolver, UUID]:
    user = uuid4()
    return FakeResolver(
        anon_perms={PROJECT_A: frozenset(), PROJECT_B: frozenset(), PROJECT_C: frozenset()},
        member_perms={
            (user, PROJECT_C): frozenset(
                {Permission.VIEW_DETECTION, Permission.VIEW_PROJECT_METADATA}
            ),
        },
    ), user


# ---------------------------------------------------------------------------
# Anonymous principal — sees only Project A
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_anonymous_sees_only_project_a(
    populated_hits: list[SearchHit],
    anonymous_resolver: FakeResolver,
) -> None:
    adapter = FtsSearchAdapter(
        resolver=anonymous_resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=None,
        query=SearchQuery(query="jay", limit=50),
    )
    assert results, "Anon should see at least one Project A hit"
    assert all(h.project_id == PROJECT_A for h in results)


@pytest.mark.asyncio
async def test_pgvector_anonymous_sees_only_project_a(
    populated_hits: list[SearchHit],
    anonymous_resolver: FakeResolver,
) -> None:
    adapter = PgvectorSearchAdapter(
        resolver=anonymous_resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=None,
        query=SearchQuery(embedding=(0.1, 0.2, 0.3), limit=50),
    )
    assert results
    assert all(h.project_id == PROJECT_A for h in results)


# ---------------------------------------------------------------------------
# Member of A — still sees only A
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_member_a_sees_only_project_a(
    populated_hits: list[SearchHit],
    member_a_resolver: tuple[FakeResolver, UUID],
) -> None:
    resolver, user_id = member_a_resolver
    adapter = FtsSearchAdapter(
        resolver=resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    principal = FakePrincipal(user_id=user_id)
    results = await adapter.search(
        db=_NO_DB,
        principal=principal,
        query=SearchQuery(query="jay", limit=50),
    )
    assert results
    assert all(h.project_id == PROJECT_A for h in results)


@pytest.mark.asyncio
async def test_pgvector_member_a_sees_only_project_a(
    populated_hits: list[SearchHit],
    member_a_resolver: tuple[FakeResolver, UUID],
) -> None:
    resolver, user_id = member_a_resolver
    adapter = PgvectorSearchAdapter(
        resolver=resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=FakePrincipal(user_id=user_id),
        query=SearchQuery(embedding=(0.1,), limit=50),
    )
    assert all(h.project_id == PROJECT_A for h in results)


# ---------------------------------------------------------------------------
# Member of B with allow_detection_view=OFF — toggle gates the leak
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_member_b_toggle_off_sees_nothing_from_b(
    populated_hits: list[SearchHit],
    member_b_toggle_off_resolver: tuple[FakeResolver, UUID],
) -> None:
    resolver, user_id = member_b_toggle_off_resolver
    adapter = FtsSearchAdapter(
        resolver=resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=FakePrincipal(user_id=user_id),
        query=SearchQuery(query="jay", limit=50),
    )
    # Toggle OFF for project B + no anon access to A or C → no hits at all.
    assert results == []


@pytest.mark.asyncio
async def test_pgvector_member_b_toggle_off_sees_nothing_from_b(
    populated_hits: list[SearchHit],
    member_b_toggle_off_resolver: tuple[FakeResolver, UUID],
) -> None:
    resolver, user_id = member_b_toggle_off_resolver
    adapter = PgvectorSearchAdapter(
        resolver=resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=FakePrincipal(user_id=user_id),
        query=SearchQuery(embedding=(0.1,), limit=50),
    )
    assert results == []


# ---------------------------------------------------------------------------
# Member of C — sees only C
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_member_c_sees_only_project_c(
    populated_hits: list[SearchHit],
    member_c_resolver: tuple[FakeResolver, UUID],
) -> None:
    resolver, user_id = member_c_resolver
    adapter = FtsSearchAdapter(
        resolver=resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=FakePrincipal(user_id=user_id),
        query=SearchQuery(query="jay", limit=50),
    )
    assert results
    assert all(h.project_id == PROJECT_C for h in results)


@pytest.mark.asyncio
async def test_pgvector_member_c_sees_only_project_c(
    populated_hits: list[SearchHit],
    member_c_resolver: tuple[FakeResolver, UUID],
) -> None:
    resolver, user_id = member_c_resolver
    adapter = PgvectorSearchAdapter(
        resolver=resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=FakePrincipal(user_id=user_id),
        query=SearchQuery(embedding=(0.1,), limit=50),
    )
    assert results
    assert all(h.project_id == PROJECT_C for h in results)


# ---------------------------------------------------------------------------
# pgvector over-fetch (k*3) is honoured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pgvector_over_fetches_3x_then_returns_k(
    anonymous_resolver: FakeResolver,
) -> None:
    """k=2 should call the provider with limit=6 then return ≤ 2."""
    captured_limits: list[int] = []

    class CapturingProvider:
        async def fetch_fts(self, db: Any, query: SearchQuery) -> list[SearchHit]:
            captured_limits.append(query.limit)
            return []

        async def fetch_pgvector(self, db: Any, query: SearchQuery) -> list[SearchHit]:
            captured_limits.append(query.limit)
            # Return 6 candidates from project A (which the anon resolver allows).
            return [_hit(PROJECT_A) for _ in range(6)]

    adapter = PgvectorSearchAdapter(
        resolver=anonymous_resolver,
        candidate_provider=CapturingProvider(),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=None,
        query=SearchQuery(embedding=(0.0,), limit=2),
    )
    assert captured_limits == [6], "pgvector should fetch k*3=6 candidates"
    assert len(results) == 2


# ---------------------------------------------------------------------------
# OpenSearch stub
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opensearch_adapter_raises_not_implemented() -> None:
    adapter = OpenSearchAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.search(
            db=_NO_DB,
            principal=None,
            query=SearchQuery(query="any"),
        )


# ---------------------------------------------------------------------------
# Payload sanitiser strips raw coordinates
# ---------------------------------------------------------------------------


def test_sanitize_payload_strips_raw_coordinates() -> None:
    raw = {
        "species": "Strix occidentalis",
        "lat": 37.7,
        "lng": -122.4,
        "latitude": 37.7,
        "longitude": -122.4,
        "h3_index": "8a283082837ffff",
    }
    cleaned = sanitize_payload(raw)
    for forbidden in ("lat", "lng", "latitude", "longitude"):
        assert forbidden not in cleaned
    assert cleaned["species"] == "Strix occidentalis"
    assert cleaned["h3_index"] == "8a283082837ffff"


def test_sanitize_payload_handles_none() -> None:
    assert sanitize_payload(None) == {}


# ---------------------------------------------------------------------------
# Empty query short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fts_empty_query_returns_empty(
    populated_hits: list[SearchHit],
    anonymous_resolver: FakeResolver,
) -> None:
    adapter = FtsSearchAdapter(
        resolver=anonymous_resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=None,
        query=SearchQuery(query="", limit=50),
    )
    assert results == []


@pytest.mark.asyncio
async def test_pgvector_no_embedding_returns_empty(
    populated_hits: list[SearchHit],
    anonymous_resolver: FakeResolver,
) -> None:
    adapter = PgvectorSearchAdapter(
        resolver=anonymous_resolver,
        candidate_provider=FakeCandidateProvider(populated_hits),
    )
    results = await adapter.search(
        db=_NO_DB,
        principal=None,
        query=SearchQuery(query="ignored", limit=50),
    )
    assert results == []
