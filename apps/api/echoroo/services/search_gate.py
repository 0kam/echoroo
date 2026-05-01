"""SearchGate abstraction layer (T090, FR-025 / FR-025a, research §3).

Every detection / annotation search path in Echoroo MUST traverse the
:class:`SearchGate` Protocol so that the permission engine and project
visibility toggles get a chance to filter the result set BEFORE rows
reach the caller. Direct ``select(Detection)`` or ``select(Annotation)``
calls outside :mod:`echoroo.services.search_gate` and
``echoroo.repositories.detection`` are forbidden — the
``scripts/lint_search_gate.py`` AST scanner enforces this rule (research
§18-C).

Three adapters are defined:

    * :class:`FtsSearchAdapter`         — PostgreSQL ``tsvector @@ tsquery``
    * :class:`PgvectorSearchAdapter`    — pgvector ANN with ``k*3`` fetch
    * :class:`OpenSearchAdapter`        — stub raising ``NotImplementedError``

All three share a single permission post-filter
(:func:`apply_visibility_filter`) so the leak-prevention rule lives in
exactly one place. The post-filter consults
:func:`echoroo.core.permissions.compute_effective_permissions` and asks
"does the principal hold :attr:`Permission.VIEW_DETECTION` for this
project?" on a per-project basis. Per-request memoisation avoids N+1.

Phase rollout (Phase 9 polish round 2 Minor 2 — refresh the deferral
ladder so the comment stays in sync with the code):

* **Phase 3** introduces the SearchGate Protocol + in-memory post-filter
  contract. The SQL adapters are stubs raising ``NotImplementedError``
  when invoked without a candidate provider, mirroring the OpenSearch
  adapter. Tests inject :class:`CandidateProvider` fakes.
* **Phase 9** wires :class:`SimilaritySearchService` into the
  :class:`PgvectorSearchAdapter` via
  :class:`SimilarityServiceCandidateProvider` so a Restricted project
  with ``allow_detection_view=OFF`` is dropped from the candidate set
  at the SQL layer (FR-025a step 1, sub-1-second leak prevention). The
  per-project SQL gate is the canonical truth source for cross-project
  search; the per-call post-filter
  (:func:`apply_visibility_filter`) layered on top is defence-in-depth
  for principal-specific deny rules.
* **Phase 11** lands the dedicated cross-project search HTTP route(s)
  (``SEARCH_CROSS_PROJECT`` action). The router will be wired through
  the existing :class:`PgvectorSearchAdapter` so the SQL gate + post-
  filter come along for free; no further changes to this module are
  required at that point.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import (
    Permission,
    ProjectVisibility,
    active_trusted_capabilities,
    compute_effective_permissions,
    normalize_role,
    resolve_role,
)
from echoroo.workers._celery_payload import _is_forbidden_key

# ---------------------------------------------------------------------------
# Public DTOs
# ---------------------------------------------------------------------------


class SearchQuery(BaseModel):
    """Caller-supplied search parameters, common to all adapters.

    The same DTO works for full-text queries (``query`` set, ``embedding``
    None) and pgvector ANN queries (``embedding`` set, ``query`` may be
    free-text for hybrid scoring).
    """

    model_config = ConfigDict(frozen=True)

    query: str | None = None
    """Free-text query string (FTS adapter mandatory, pgvector optional)."""

    embedding: tuple[float, ...] | None = None
    """Pre-computed query vector (pgvector adapter mandatory)."""

    limit: int = Field(default=50, ge=1, le=500)
    """Maximum hits to return AFTER post-filtering (final ``k``)."""

    project_id: UUID | None = None
    """Restrict candidates to a single project, if provided."""

    species_id: UUID | None = None
    """Restrict candidates to a single taxon, if provided."""


class SearchHit(BaseModel):
    """A single search result with the minimum sanitized payload.

    Raw coordinates are NEVER permitted — :class:`SearchHit` enforces the
    same denylist as the Celery payload validator (FR-028b/c) at construction
    time so the rule is structurally guaranteed for every adapter.
    """

    model_config = ConfigDict(frozen=True)

    detection_id: UUID
    recording_id: UUID
    project_id: UUID
    score: float
    payload: Mapping[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Principal protocol (structural)
# ---------------------------------------------------------------------------


@runtime_checkable
class _PrincipalLike(Protocol):
    """Structural protocol matching :class:`echoroo.middleware.auth_router.Principal`.

    Defined locally so this module does NOT depend on the middleware. The
    real ``Principal`` (a frozen dataclass) and any test stub with the
    same attribute names satisfy this shape; the ``@property`` accessors
    make the contract read-only so frozen dataclasses match.
    """

    @property
    def user_id(self) -> UUID | None: ...

    @property
    def auth_kind(self) -> str: ...


# ---------------------------------------------------------------------------
# SearchGate Protocol + shared post-filter
# ---------------------------------------------------------------------------


class SearchGate(Protocol):
    """Contract every search adapter MUST implement (research §3).

    The implementation receives an authenticated principal plus the query
    DTO and returns at most ``query.limit`` hits, all of which the
    principal is permitted to see (i.e. holds ``VIEW_DETECTION`` for the
    hit's project, with the project's ``allow_detection_view`` toggle ON
    when applicable).
    """

    async def search(
        self,
        db: AsyncSession,
        principal: _PrincipalLike | None,
        query: SearchQuery,
    ) -> list[SearchHit]: ...


# ---------------------------------------------------------------------------
# Permission resolver (DI'd into adapters for tests)
# ---------------------------------------------------------------------------


class PermissionResolver(Protocol):
    """Look up effective permissions for ``(principal, project_id)``.

    The default implementation queries the DB for the project + member
    rows and calls :func:`compute_effective_permissions`. Tests inject a
    fake to avoid spinning up a database.
    """

    async def effective_permissions_for_project(
        self,
        db: AsyncSession,
        principal: _PrincipalLike | None,
        project_id: UUID,
    ) -> frozenset[Permission]: ...


class _DefaultPermissionResolver:
    """Concrete resolver that derives permissions from ORM lookups.

    Phase 2 status: the resolver exists for type / lint coverage and is
    fully covered by Phase 3 integration tests. The Phase 2 unit tests
    inject a fake (see ``tests/security/search_leak``).
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[UUID | None, UUID], frozenset[Permission]] = {}

    async def effective_permissions_for_project(
        self,
        db: AsyncSession,
        principal: _PrincipalLike | None,
        project_id: UUID,
    ) -> frozenset[Permission]:
        # Local import to avoid a heavy import cycle at module load.
        from echoroo.repositories.project import ProjectRepository

        cache_key = (
            principal.user_id if principal is not None else None,
            project_id,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        repo = ProjectRepository(db)
        project = await repo.get_by_id(project_id)
        if project is None:
            self._cache[cache_key] = frozenset()
            return frozenset()

        # Phase 3 supplies the real role lookup; here we model the
        # "no ProjectMember row" case (Guest / Authenticated).
        user = principal if principal is not None and getattr(principal, "user_id", None) else None
        raw = resolve_role(user, project) if user is not None else "Guest"
        normalized = normalize_role(raw, project)
        effective = compute_effective_permissions(
            normalized_role=normalized,
            project=project,
            trusted_capabilities=active_trusted_capabilities(None),
            api_key_granted_permissions=None,
        )
        self._cache[cache_key] = effective
        return effective


# ---------------------------------------------------------------------------
# Shared post-filter — the single source of truth for the leak rule
# ---------------------------------------------------------------------------


async def apply_visibility_filter(
    db: AsyncSession,
    principal: _PrincipalLike | None,
    hits: Iterable[SearchHit],
    *,
    resolver: PermissionResolver,
    limit: int,
) -> list[SearchHit]:
    """Drop every hit the principal cannot ``VIEW_DETECTION`` on.

    Caches per ``project_id`` for the duration of the call so a result
    set spanning the same project does not pay N permission lookups.
    Returns at most ``limit`` survivors, in input order.
    """
    survivors: list[SearchHit] = []
    project_decision: dict[UUID, bool] = {}

    for hit in hits:
        decision = project_decision.get(hit.project_id)
        if decision is None:
            effective = await resolver.effective_permissions_for_project(
                db, principal, hit.project_id
            )
            decision = Permission.VIEW_DETECTION in effective
            project_decision[hit.project_id] = decision
        if decision:
            survivors.append(hit)
            if len(survivors) >= limit:
                break
    return survivors


def sanitize_payload(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Strip raw coordinate keys from a search hit payload.

    Reuses the Celery payload denylist (:func:`_is_forbidden_key`) so the
    rule is defined exactly once in the codebase.
    """
    if raw is None:
        return {}
    safe: dict[str, Any] = {}
    for key, value in raw.items():
        if _is_forbidden_key(str(key)):
            continue
        safe[str(key)] = value
    return safe


# ---------------------------------------------------------------------------
# FTS adapter
# ---------------------------------------------------------------------------


class FtsSearchAdapter:
    """PostgreSQL full-text search adapter.

    Implementation hook: :meth:`_fetch_candidates` is intentionally left
    as a thin wrapper that Phase 3 fills in when ``repositories/detection.py``
    lands. Phase 2 unit tests inject candidates directly.
    """

    def __init__(
        self,
        *,
        resolver: PermissionResolver | None = None,
        candidate_provider: CandidateProvider | None = None,
    ) -> None:
        self._resolver: PermissionResolver = resolver or _DefaultPermissionResolver()
        self._candidate_provider = candidate_provider

    async def search(
        self,
        db: AsyncSession,
        principal: _PrincipalLike | None,
        query: SearchQuery,
    ) -> list[SearchHit]:
        if query.query is None or not query.query.strip():
            return []
        candidates = await self._fetch_candidates(db, query)
        return await apply_visibility_filter(
            db,
            principal,
            candidates,
            resolver=self._resolver,
            limit=query.limit,
        )

    async def _fetch_candidates(
        self, db: AsyncSession, query: SearchQuery
    ) -> list[SearchHit]:
        if self._candidate_provider is not None:
            return await self._candidate_provider.fetch_fts(db, query)
        # Phase 3 wires this to ``repositories.detection.fts_search``.
        raise NotImplementedError(
            "FtsSearchAdapter requires a candidate_provider until Phase 3"
        )


# ---------------------------------------------------------------------------
# pgvector adapter
# ---------------------------------------------------------------------------


class PgvectorSearchAdapter:
    """pgvector ANN adapter.

    Fetches ``k*3`` candidates from the vector index and post-filters by
    permission, returning at most ``k`` hits. The 3x over-fetch absorbs
    approximate-NN drop-off (research §3).
    """

    OVER_FETCH_FACTOR: int = 3

    def __init__(
        self,
        *,
        resolver: PermissionResolver | None = None,
        candidate_provider: CandidateProvider | None = None,
    ) -> None:
        self._resolver: PermissionResolver = resolver or _DefaultPermissionResolver()
        self._candidate_provider = candidate_provider

    async def search(
        self,
        db: AsyncSession,
        principal: _PrincipalLike | None,
        query: SearchQuery,
    ) -> list[SearchHit]:
        if query.embedding is None:
            return []
        over_fetch_limit = query.limit * self.OVER_FETCH_FACTOR
        # Build a temporary query that asks for the larger candidate set.
        # We construct via ``model_copy`` to keep the original frozen.
        candidate_query = query.model_copy(update={"limit": over_fetch_limit})
        candidates = await self._fetch_candidates(db, candidate_query)
        return await apply_visibility_filter(
            db,
            principal,
            candidates,
            resolver=self._resolver,
            limit=query.limit,
        )

    async def _fetch_candidates(
        self, db: AsyncSession, query: SearchQuery
    ) -> list[SearchHit]:
        if self._candidate_provider is not None:
            return await self._candidate_provider.fetch_pgvector(db, query)
        raise NotImplementedError(
            "PgvectorSearchAdapter requires a candidate_provider until Phase 3"
        )


# ---------------------------------------------------------------------------
# OpenSearch adapter (stub)
# ---------------------------------------------------------------------------


class OpenSearchAdapter:
    """Reserved for v1.1 — every method raises ``NotImplementedError``.

    The contract test in :mod:`tests.security.search_leak` calls
    :meth:`search` and asserts the raise so spec FR-025's "3 search
    paths" guarantee remains structurally enforced even though the
    adapter is not wired (research §3).
    """

    async def search(
        self,
        db: AsyncSession,  # noqa: ARG002 - signature parity
        principal: _PrincipalLike | None,  # noqa: ARG002
        query: SearchQuery,  # noqa: ARG002
    ) -> list[SearchHit]:
        raise NotImplementedError(
            "OpenSearch adapter is reserved for Phase 4+"
        )


# ---------------------------------------------------------------------------
# Candidate-provider Protocol (DI seam for Phase 3 + tests)
# ---------------------------------------------------------------------------


class CandidateProvider(Protocol):
    """Phase-3 swap-in for the actual ``select(Detection)`` queries.

    Adapters never speak SQL directly: they accept a ``CandidateProvider``
    and call ``fetch_fts`` / ``fetch_pgvector`` on it. The provider lives
    in ``repositories/detection.py`` (Phase 3), keeping
    :mod:`echoroo.services.search_gate` free of ORM imports.
    """

    async def fetch_fts(
        self, db: AsyncSession, query: SearchQuery
    ) -> list[SearchHit]: ...

    async def fetch_pgvector(
        self, db: AsyncSession, query: SearchQuery
    ) -> list[SearchHit]: ...


# ---------------------------------------------------------------------------
# Project-toggle helper (FR-025a / Restricted toggle)
# ---------------------------------------------------------------------------


def project_allows_detection_view(project: Any) -> bool:
    """True iff the project's visibility + ``allow_detection_view`` toggle
    grant baseline detection visibility to non-members.

    PUBLIC projects always allow detection view. RESTRICTED projects
    require ``restricted_config['allow_detection_view'] == True``. Used
    by Phase 3 SQL adapters as an additional ``WHERE`` clause; the post-
    filter handles per-principal cases.
    """
    visibility = getattr(project, "visibility", None)
    if visibility == ProjectVisibility.PUBLIC:
        return True
    if visibility == ProjectVisibility.RESTRICTED:
        cfg = getattr(project, "restricted_config", None) or {}
        return bool(cfg.get("allow_detection_view", False))
    return False


# ---------------------------------------------------------------------------
# SimilaritySearchService bridge — Phase 9 / T412 wiring (FR-025 / FR-025a)
# ---------------------------------------------------------------------------


class SimilarityServiceCandidateProvider:
    """Bridge :class:`SimilaritySearchService` into the SearchGate Protocol.

    Phase 8's deferral note (``services/restricted_config_service.py`` line
    55-66) flagged that the actual wiring of
    :class:`echoroo.services.search.SimilaritySearchService` into the
    SearchGate adapters was reserved for Phase 11. T412 brings that
    forward: Restricted ``allow_detection_view=OFF`` projects must
    physically drop out of the candidate set within 1 second of the
    toggle flip (FR-025a step 1, SC-018), and the only honest way to
    test that without a Redis/Celery round-trip is to wire the SQL
    filter (``respect_restricted_toggle=True``) into the production
    similarity service.

    The provider exposes a single ``project_id`` parameter (mirroring the
    underlying SQL contract) and delegates the candidate fetch to
    :meth:`SimilaritySearchService.search_by_vector`. Cross-project
    aggregation (FR-026) is layered on top of this provider by the
    Phase 11 cross-project router; for now we cover the per-project
    Restricted-toggle gate which is what FR-025a step 1 mandates.

    Phase rollout summary (Phase 9 polish round 2 Minor 2):

    * **Phase 3** — SearchGate Protocol + in-memory post-filter only.
    * **Phase 9** — this provider wires the SQL gate
      (``respect_restricted_toggle=True`` is now also the default on
      ``search_by_vector`` after Major 1; we keep the explicit ``True``
      here as a belt-and-braces signal at the call site).
    * **Phase 11** — cross-project HTTP route reuses this provider
      unchanged.
    """

    def __init__(
        self,
        service: Any,
        *,
        project_id: UUID,
        model_name: str,
        min_similarity: float = 0.0,
    ) -> None:
        """Pin the bridge to a concrete project + model + min-similarity.

        ``service`` is intentionally typed as ``Any`` so this module does
        not import :class:`SimilaritySearchService` at module load
        (avoids a heavy dependency cycle with ``services/search.py``).
        """
        self._service = service
        self._project_id = project_id
        self._model_name = model_name
        self._min_similarity = min_similarity

    async def fetch_fts(
        self,
        db: AsyncSession,  # noqa: ARG002 - bridged service owns the session
        query: SearchQuery,  # noqa: ARG002 - reserved for Phase 11 FTS wiring
    ) -> list[SearchHit]:
        """FTS path is reserved for Phase 11 — return empty for now.

        The SearchGate test suite covers the FTS adapter via a
        :class:`FakeCandidateProvider`; the production FTS surface is
        not yet wired.
        """
        return []

    async def fetch_pgvector(
        self,
        db: AsyncSession,  # noqa: ARG002 - service uses its own session
        query: SearchQuery,
    ) -> list[SearchHit]:
        """Run the pgvector similarity query under the Restricted toggle.

        ``respect_restricted_toggle=True`` adds the SQL filter that
        excludes Restricted projects with ``allow_detection_view=OFF``
        — the canonical FR-025a step 1 immediate exclusion.
        """
        if query.embedding is None:
            return []
        results = await self._service.search_by_vector(
            project_id=self._project_id,
            query_vector=list(query.embedding),
            model_name=self._model_name,
            limit=query.limit,
            min_similarity=self._min_similarity,
            respect_restricted_toggle=True,
        )
        return [
            SearchHit(
                detection_id=row.embedding_id,
                recording_id=row.recording_id,
                project_id=self._project_id,
                score=row.similarity,
                payload=sanitize_payload(
                    {
                        "filename": row.recording_filename,
                        "start_time": row.start_time,
                        "end_time": row.end_time,
                    }
                ),
            )
            for row in results
        ]


__all__ = [
    "CandidateProvider",
    "FtsSearchAdapter",
    "OpenSearchAdapter",
    "PermissionResolver",
    "PgvectorSearchAdapter",
    "SearchGate",
    "SearchHit",
    "SearchQuery",
    "SimilarityServiceCandidateProvider",
    "apply_visibility_filter",
    "project_allows_detection_view",
    "sanitize_payload",
]
