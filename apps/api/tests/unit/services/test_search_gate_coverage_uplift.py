"""Phase 17 §C PR-D coverage uplift — ``echoroo.services.search_gate``.

Targets the three sub-surfaces of the SearchGate module that the
existing ``tests/security/search_leak`` suite intentionally bypasses
(those tests inject ``FakeResolver`` / ``FakeCandidateProvider`` so the
adapters' DI seams are exercised but the *default* resolver and the
SimilaritySearchService bridge remain untouched):

* :class:`_DefaultPermissionResolver` — the production resolver that
  derives :class:`Permission` sets from a real
  :class:`ProjectRepository` lookup. Covers the cache-miss → cache-hit
  short-circuit, the missing-project branch, the Guest fallback, and the
  member-with-user_id branch.
* :func:`project_allows_detection_view` — the FR-025a toggle helper,
  Public / Restricted-with-toggle-on / Restricted-with-toggle-off / no-
  visibility paths.
* :class:`SimilarityServiceCandidateProvider` — Phase 9 bridge from the
  pgvector ANN service into the SearchGate Protocol. Covers the FTS
  early-return stub, the pgvector ``embedding is None`` short-circuit,
  and the row-mapping path that fans :class:`SearchHit` instances out of
  a stubbed similarity service.

Pure unit tests; the ``ProjectRepository`` and ``SimilaritySearchService``
are stubbed via in-test doubles so no DB / Redis / Celery round-trip is
required.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import Permission, ProjectVisibility
from echoroo.services import search_gate as sg
from echoroo.services.search_gate import (
    SearchHit,
    SearchQuery,
    SimilarityServiceCandidateProvider,
    _DefaultPermissionResolver,
    project_allows_detection_view,
)

# Stand-in AsyncSession — every code-path under test stubs the I/O.
_NO_DB: AsyncSession = cast(AsyncSession, None)


# ---------------------------------------------------------------------------
# project_allows_detection_view — toggle helper (lines 449-455)
# ---------------------------------------------------------------------------


class _ProjectShape:
    """Minimal duck-type for the toggle helper — only attributes are read."""

    def __init__(
        self,
        *,
        visibility: Any = None,
        restricted_config: Any = None,
    ) -> None:
        self.visibility = visibility
        self.restricted_config = restricted_config


def test_project_allows_detection_view_public_returns_true() -> None:
    """PUBLIC visibility unconditionally allows detection view."""
    project = _ProjectShape(visibility=ProjectVisibility.PUBLIC)
    assert project_allows_detection_view(project) is True


def test_project_allows_detection_view_restricted_with_toggle_on() -> None:
    """RESTRICTED + ``allow_detection_view=True`` allows."""
    project = _ProjectShape(
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={"allow_detection_view": True},
    )
    assert project_allows_detection_view(project) is True


def test_project_allows_detection_view_restricted_with_toggle_off() -> None:
    """RESTRICTED + ``allow_detection_view=False`` denies (the FR-025a leak gate)."""
    project = _ProjectShape(
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={"allow_detection_view": False},
    )
    assert project_allows_detection_view(project) is False


def test_project_allows_detection_view_restricted_with_no_config() -> None:
    """RESTRICTED + ``restricted_config=None`` defaults to deny."""
    project = _ProjectShape(
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config=None,
    )
    assert project_allows_detection_view(project) is False


def test_project_allows_detection_view_unknown_visibility_is_denied() -> None:
    """Anything that is not PUBLIC / RESTRICTED falls through to ``False``."""
    project = _ProjectShape(visibility=None, restricted_config=None)
    assert project_allows_detection_view(project) is False


# ---------------------------------------------------------------------------
# _DefaultPermissionResolver — production resolver (lines 189, 198-226)
# ---------------------------------------------------------------------------


class _StubProject:
    """Minimal :class:`Project` duck-type for the default resolver."""

    def __init__(
        self,
        *,
        owner_id: UUID | None = None,
        visibility: Any = ProjectVisibility.PUBLIC,
        restricted_config: dict[str, Any] | None = None,
    ) -> None:
        self.id = uuid4()
        self.owner_id = owner_id
        self.visibility = visibility
        self.restricted_config = restricted_config or {}


class _StubProjectRepository:
    """Drop-in for :class:`ProjectRepository` with a single canned project."""

    def __init__(self, project: _StubProject | None) -> None:
        self._project = project
        self.calls: int = 0

    def __init_db__(self, db: Any) -> None:
        # Mirror the constructor's stored db reference but unused.
        del db

    async def get_by_id(self, project_id: UUID) -> _StubProject | None:
        # The default resolver caches per (principal, project_id), so a
        # repeat lookup MUST NOT hit this stub a second time.
        self.calls += 1
        del project_id
        return self._project


@pytest.fixture(autouse=True)
def _patch_project_repository(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``ProjectRepository`` for tests that exercise the resolver.

    The default resolver imports ``ProjectRepository`` lazily inside its
    method body, so the patch lives on ``echoroo.repositories.project``.
    Returns a mutable holder the tests update with the project to be
    served on the next call.
    """
    holder: dict[str, Any] = {"project": None}

    class _Factory:
        def __init__(self, db: Any) -> None:  # noqa: ARG002 - signature parity
            self._project = holder["project"]

        async def get_by_id(self, project_id: UUID) -> Any:
            holder.setdefault("calls", 0)
            holder["calls"] = int(holder.get("calls", 0)) + 1
            del project_id
            return self._project

    monkeypatch.setattr(
        "echoroo.repositories.project.ProjectRepository", _Factory, raising=True
    )
    return holder


class _FakePrincipal:
    """Structural :class:`Principal` for the resolver."""

    def __init__(self, *, user_id: UUID | None) -> None:
        self.user_id = user_id
        self.auth_kind = "session"


@pytest.mark.asyncio
async def test_default_resolver_returns_empty_when_project_missing(
    _patch_project_repository: dict[str, Any],
) -> None:
    """Missing project → empty permission set + cached so a repeat lookup
    does not re-issue the SELECT.
    """
    _patch_project_repository["project"] = None
    resolver = _DefaultPermissionResolver()
    project_id = uuid4()
    principal = _FakePrincipal(user_id=uuid4())

    first = await resolver.effective_permissions_for_project(_NO_DB, principal, project_id)
    assert first == frozenset()

    # Second call must hit the cache, not the repository.
    second = await resolver.effective_permissions_for_project(_NO_DB, principal, project_id)
    assert second == frozenset()
    assert _patch_project_repository.get("calls") == 1


@pytest.mark.asyncio
async def test_default_resolver_returns_guest_perms_for_anonymous_principal(
    _patch_project_repository: dict[str, Any],
) -> None:
    """``principal=None`` resolves to the Guest role baseline.

    A Public project grants Guests at least :attr:`Permission.VIEW_DETECTION`
    (the canonical "anyone can browse public detections" rule).
    """
    _patch_project_repository["project"] = _StubProject(
        visibility=ProjectVisibility.PUBLIC,
    )
    resolver = _DefaultPermissionResolver()
    perms = await resolver.effective_permissions_for_project(
        _NO_DB, principal=None, project_id=uuid4()
    )
    assert isinstance(perms, frozenset)
    assert Permission.VIEW_DETECTION in perms


@pytest.mark.asyncio
async def test_default_resolver_member_with_user_id_uses_resolve_role_branch(
    _patch_project_repository: dict[str, Any],
) -> None:
    """A real principal with ``user_id`` set walks the resolve_role branch.

    For a Public project the principal still ends up as a non-member
    (no ``ProjectMember`` row) so the resolver falls through to the
    Authenticated baseline; we just need to confirm the call shape works
    and produces a non-empty set covering at least VIEW_DETECTION.
    """
    _patch_project_repository["project"] = _StubProject(
        visibility=ProjectVisibility.PUBLIC,
    )
    resolver = _DefaultPermissionResolver()
    principal = _FakePrincipal(user_id=uuid4())
    perms = await resolver.effective_permissions_for_project(
        _NO_DB, principal=principal, project_id=uuid4()
    )
    assert Permission.VIEW_DETECTION in perms


@pytest.mark.asyncio
async def test_default_resolver_caches_result_per_principal(
    _patch_project_repository: dict[str, Any],
) -> None:
    """Two lookups with the same ``(principal, project_id)`` hit the cache."""
    _patch_project_repository["project"] = _StubProject(
        visibility=ProjectVisibility.PUBLIC,
    )
    resolver = _DefaultPermissionResolver()
    principal = _FakePrincipal(user_id=uuid4())
    project_id = uuid4()

    first = await resolver.effective_permissions_for_project(
        _NO_DB, principal=principal, project_id=project_id
    )
    second = await resolver.effective_permissions_for_project(
        _NO_DB, principal=principal, project_id=project_id
    )
    assert first == second
    assert _patch_project_repository.get("calls") == 1


# ---------------------------------------------------------------------------
# SimilarityServiceCandidateProvider — Phase 9 bridge (lines 525, 539, 540-562)
# ---------------------------------------------------------------------------


class _SimilarityRow:
    """Minimal duck-type for a :class:`SimilaritySearchResult` row."""

    def __init__(
        self,
        *,
        embedding_id: UUID,
        recording_id: UUID,
        similarity: float,
        recording_filename: str = "rec.wav",
        start_time: float = 0.0,
        end_time: float = 1.0,
    ) -> None:
        self.embedding_id = embedding_id
        self.recording_id = recording_id
        self.similarity = similarity
        self.recording_filename = recording_filename
        self.start_time = start_time
        self.end_time = end_time


class _StubSimilarityService:
    """Capture ``search_by_vector`` invocations and return canned rows."""

    def __init__(self, rows: Iterable[_SimilarityRow]) -> None:
        self._rows = list(rows)
        self.last_kwargs: dict[str, Any] | None = None

    async def search_by_vector(self, **kwargs: Any) -> list[_SimilarityRow]:
        self.last_kwargs = kwargs
        return list(self._rows)


@pytest.mark.asyncio
async def test_similarity_provider_fetch_fts_returns_empty_stub() -> None:
    """The FTS path is reserved for Phase 11 and MUST return ``[]``."""
    provider = SimilarityServiceCandidateProvider(
        service=_StubSimilarityService(rows=[]),
        project_id=uuid4(),
        model_name="bird-net-v3",
    )
    out = await provider.fetch_fts(_NO_DB, SearchQuery(query="hello", limit=10))
    assert out == []


@pytest.mark.asyncio
async def test_similarity_provider_fetch_pgvector_returns_empty_when_no_embedding() -> None:
    """``embedding is None`` short-circuits before touching the service."""
    service = _StubSimilarityService(rows=[])
    provider = SimilarityServiceCandidateProvider(
        service=service,
        project_id=uuid4(),
        model_name="bird-net-v3",
    )
    out = await provider.fetch_pgvector(_NO_DB, SearchQuery(embedding=None, limit=10))
    assert out == []
    # The service must not have been invoked at all.
    assert service.last_kwargs is None


@pytest.mark.asyncio
async def test_similarity_provider_fetch_pgvector_maps_rows_to_search_hits() -> None:
    """The bridge wires every row into a :class:`SearchHit` with sanitised payload."""
    project_id = uuid4()
    rec_id = uuid4()
    emb_id = uuid4()
    service = _StubSimilarityService(
        rows=[
            _SimilarityRow(
                embedding_id=emb_id,
                recording_id=rec_id,
                similarity=0.92,
                recording_filename="bird.wav",
                start_time=0.5,
                end_time=2.5,
            )
        ]
    )
    provider = SimilarityServiceCandidateProvider(
        service=service,
        project_id=project_id,
        model_name="bird-net-v3",
        min_similarity=0.1,
    )
    hits = await provider.fetch_pgvector(
        _NO_DB,
        SearchQuery(embedding=(0.0, 1.0, 0.0), limit=5),
    )
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, SearchHit)
    assert hit.detection_id == emb_id
    assert hit.recording_id == rec_id
    assert hit.project_id == project_id
    assert hit.score == pytest.approx(0.92)
    # ``filename`` / ``start_time`` / ``end_time`` survive sanitization
    # because none of them are on the raw-coordinate denylist.
    assert hit.payload == {
        "filename": "bird.wav",
        "start_time": 0.5,
        "end_time": 2.5,
    }
    # The bridge MUST forward respect_restricted_toggle=True so the SQL
    # gate is engaged at the candidate-fetch layer.
    assert service.last_kwargs is not None
    assert service.last_kwargs["respect_restricted_toggle"] is True
    assert service.last_kwargs["min_similarity"] == pytest.approx(0.1)
    assert service.last_kwargs["limit"] == 5
    assert service.last_kwargs["model_name"] == "bird-net-v3"
    assert service.last_kwargs["project_id"] == project_id


# ---------------------------------------------------------------------------
# Sanity — sg module exports the expected symbols (lint guard, not coverage).
# ---------------------------------------------------------------------------


def test_module_exports_include_similarity_provider() -> None:
    assert "SimilarityServiceCandidateProvider" in sg.__all__
    assert "project_allows_detection_view" in sg.__all__
