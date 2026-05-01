"""Smoke tests for read-only search router endpoints.

Provides a safety net before the upcoming refactor of
``echoroo/api/v1/search/``.  Each covered route gets:
  - 200 happy path (valid auth + real session / dataset)
  - 401 unauthenticated
  - 403/404 cross-tenant (another user's session → whichever the code returns)
  - 404 not-found (syntactically valid but non-existent UUID)

Routes covered (all mounted under /api/v1/projects/{project_id}/search):
  1  GET  /embedding-stats
  2  GET  /sessions
  3  GET  /sessions/{session_id}
  4  PATCH /sessions/{session_id}  (rename — no S3/Celery)
  5  GET  /sessions/{session_id}/distribution
  6  GET  /sessions/{session_id}/time-distribution
  7  GET  /sessions/{session_id}/sample
  8  GET  /sessions/{session_id}/export-recordings
  9  GET  /sessions/{session_id}/export/csv
"""

from __future__ import annotations

import collections.abc
import csv
import io
import re

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
from echoroo.models.enums import DatasetStatus, DatetimeParseStatus, SearchSessionStatus
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.search_session import SearchSession
from echoroo.models.site import Site
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_UUID = "00000000-0000-0000-0000-000000000000"
# Perch v2 embedding dimension
_EMBEDDING_DIM = 1536


def _make_expiring_resolver() -> collections.abc.Callable[..., collections.abc.Awaitable[dict[str, str]]]:
    """Build a fake ``_resolve_locale_common_names`` that expires all ORM objects.

    Returns an async callable with the same (session, species_keys,
    species_labels, locale, db) signature as the real helper. The callable
    performs ``await db.rollback()`` as a side-effect — this is the exact
    state that production hits when ``_resolve_vernacular_via_gbif`` fails
    to insert a new Taxon (e.g. duplicate race), falls into its
    rollback-and-continue branch, and inadvertently expires every ORM
    instance the caller still holds (``rollback()`` expires all
    instance-tracked attributes regardless of the session's
    ``expire_on_commit`` setting).

    The returned dict is empty: we only care that the route does not 500
    when it continues accessing session attributes after this rollback.
    """

    async def _resolver(
        _session: object,
        _species_keys: list[str],
        _species_labels: dict[str, str],
        _locale: str,
        db: AsyncSession,
    ) -> dict[str, str]:
        await db.rollback()
        return {}

    return _resolver


# ---------------------------------------------------------------------------
# Local fixtures (search-specific infrastructure)
# ---------------------------------------------------------------------------


@pytest.fixture
async def search_site(
    db_session: AsyncSession,
    test_project: Project,
) -> Site:
    """Create a site for search smoke tests.

    Args:
        db_session: Database session
        test_project: Test project

    Returns:
        Test site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Search Smoke Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def search_dataset(
    db_session: AsyncSession,
    test_project: Project,
    search_site: Site,
) -> Dataset:
    """Create a completed dataset for search smoke tests.

    Args:
        db_session: Database session
        test_project: Test project
        search_site: Test site

    Returns:
        Test dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=search_site.id,
        created_by_id=test_project.owner_id,
        name="Search Smoke Dataset",
        audio_dir="/data/audio/search-smoke",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def search_recording(
    db_session: AsyncSession,
    search_dataset: Dataset,
) -> Recording:
    """Create a recording for search smoke tests.

    Args:
        db_session: Database session
        search_dataset: Test dataset

    Returns:
        Test recording instance
    """
    recording = Recording(
        dataset_id=search_dataset.id,
        filename="smoke_test_recording.wav",
        path="smoke_test_recording.wav",
        duration=30.0,
        samplerate=48000,
        channels=1,
        datetime_parse_status=DatetimeParseStatus.PENDING,
        time_expansion=1.0,
    )
    db_session.add(recording)
    await db_session.commit()
    await db_session.refresh(recording)
    return recording


@pytest.fixture
async def search_embedding(
    db_session: AsyncSession,
    search_recording: Recording,
) -> Embedding:
    """Create an embedding row so distribution/sample/export-recordings can compute similarity.

    Uses a 1536-dim unit vector (first element = 1.0, rest = 0.0).  A zero
    vector would produce NaN cosine similarity (division by zero), which
    triggers a ValueError in the distribution service.

    Args:
        db_session: Database session
        search_recording: Test recording

    Returns:
        Test embedding instance
    """
    unit_vector = [1.0] + [0.0] * (_EMBEDDING_DIM - 1)
    embedding = Embedding(
        recording_id=search_recording.id,
        model_name="perch",
        start_time=0.0,
        end_time=5.0,
        vector=unit_vector,
    )
    db_session.add(embedding)
    await db_session.commit()
    await db_session.refresh(embedding)
    return embedding


@pytest.fixture
async def test_search_session(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
    search_recording: Recording,
    search_embedding: Embedding,
) -> SearchSession:
    """Create a completed SearchSession with seeded results JSONB.

    The ``results`` field is populated so that ``_get_query_vectors_from_session``
    can resolve a real embedding vector from the DB.  This allows
    distribution/time-distribution/sample/export-recordings endpoints to return
    200 rather than 404.

    The species key matches the fake tag_id used in ``species_config``.

    Args:
        db_session: Database session
        test_project: Test project (owner)
        test_user: Authenticated test user
        search_recording: Seeded recording (for result shape)
        search_embedding: Seeded embedding (provides a real embedding_id)

    Returns:
        SearchSession ORM instance (committed)
    """
    species_key = "aaaaaaaa-0000-0000-0000-000000000001"
    # Results JSONB mirrors BatchSearchResponse wire format so
    # _get_query_vectors_from_session can find embedding_id → vector.
    results_jsonb: dict[str, object] = {
        "results": {
            species_key: {
                "tag_id": species_key,
                "scientific_name": "Turdus merula",
                "common_name": "Common Blackbird",
                "matches": [
                    {
                        "embedding_id": str(search_embedding.id),
                        "recording_id": str(search_recording.id),
                        "recording_filename": search_recording.filename,
                        "recording_datetime": None,
                        "dataset_id": str(search_recording.dataset_id),
                        "start_time": float(search_embedding.start_time),
                        "end_time": float(search_embedding.end_time),
                        "similarity": 0.85,
                    }
                ],
            }
        },
        "total_matches": 1,
        "search_duration_ms": 42,
    }
    species_config: list[object] = [
        {
            "tag_id": species_key,
            "scientific_name": "Turdus merula",
            "common_name": "Common Blackbird",
            "sources": [],
        }
    ]
    session = SearchSession(
        project_id=test_project.id,
        user_id=test_user.id,
        name="Smoke Test Session",
        status=SearchSessionStatus.COMPLETED,
        model_name="perch",
        parameters={
            "min_similarity": 0.1,
            "limit_per_species": 100,
            "dataset_id": None,
        },
        species_config=species_config,
        results=results_jsonb,
        result_count=1,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest.fixture
async def test_search_session_other_project(
    db_session: AsyncSession,
    other_user: User,
) -> SearchSession:
    """Create a SearchSession belonging to a separate project (not shared with test_user).

    Used to test cross-tenant isolation: test_user should not be able to access
    sessions belonging to other_user's project.

    Args:
        db_session: Database session
        other_user: The other (non-owner) user

    Returns:
        SearchSession in an isolated project owned by other_user
    """
    # Phase 16 Batch 6e (2026-04-29) downstream drift fix: ``ProjectVisibility``
    # no longer carries a ``PRIVATE`` member (Public / Restricted only),
    # ``Project.target_taxa`` was removed by Phase 7, and ``license`` is
    # NOT NULL (FR-085). Use ``PUBLIC`` so ``restricted_config`` does not
    # need to satisfy the eight-toggle ``ck_projects_restricted_config_shape``
    # CHECK.
    from echoroo.models.enums import ProjectLicense, ProjectVisibility
    from echoroo.models.project import Project

    other_project = Project(
        name="Other Project",
        description="Cross-tenant isolation project",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=other_user.id,
    )
    db_session.add(other_project)
    await db_session.flush()

    session = SearchSession(
        project_id=other_project.id,
        user_id=other_user.id,
        name="Other Session",
        status=SearchSessionStatus.COMPLETED,
        model_name="perch",
        result_count=0,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _search_base(project_id: str) -> str:
    """Return the base URL prefix for the search router.

    Args:
        project_id: Project UUID string

    Returns:
        URL prefix string
    """
    return f"/api/v1/projects/{project_id}/search"


# ---------------------------------------------------------------------------
# Route 1: GET /embedding-stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmbeddingStats:
    """Smoke tests for GET /embedding-stats."""

    async def test_happy_path_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Returns 200 with empty-state shape when no embeddings exist.

        Asserting the empty state here because creating real embeddings is
        expensive and the endpoint handles 0 embeddings gracefully.
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/embedding-stats",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_count" in data
        assert "by_model" in data
        assert "by_dataset" in data
        assert isinstance(data["total_count"], int)
        assert isinstance(data["by_model"], dict)
        assert isinstance(data["by_dataset"], dict)

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /embedding-stats without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/embedding-stats",
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """GET /embedding-stats for a project that other_user cannot access → 403."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/embedding-stats",
            headers=auth_headers_other,
        )
        assert resp.status_code == 403

    async def test_with_real_embedding(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        search_embedding: Embedding,  # noqa: ARG002  # side-effect: seeds one embedding row
    ) -> None:
        """Seeding one embedding row → total_count == 1."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/embedding-stats",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] >= 1
        assert "perch" in data["by_model"]


# ---------------------------------------------------------------------------
# Route 2: GET /sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListSessions:
    """Smoke tests for GET /sessions."""

    async def test_happy_path_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Returns 200 with empty list when no sessions exist."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert "total" in data
        assert isinstance(data["sessions"], list)
        assert isinstance(data["total"], int)

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /sessions without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions",
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """GET /sessions for a project other_user cannot access → 403."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions",
            headers=auth_headers_other,
        )
        assert resp.status_code == 403

    async def test_pagination_limit(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
        test_project: Project,
        test_user: User,
    ) -> None:
        """With 2 sessions and limit=1, response contains exactly 1 item and total >= 2."""
        for i in range(2):
            s = SearchSession(
                project_id=test_project.id,
                user_id=test_user.id,
                name=f"Pagination Session {i}",
                status=SearchSessionStatus.COMPLETED,
                model_name="perch",
                result_count=0,
            )
            db_session.add(s)
        await db_session.commit()

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions",
            headers=auth_headers,
            params={"limit": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) == 1
        assert data["total"] >= 2

    async def test_locale_ja_no_500(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """locale=ja parameter does not cause a 500 (enrichment is best-effort)."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Route 3: GET /sessions/{session_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSession:
    """Smoke tests for GET /sessions/{session_id}."""

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Returns 200 with full session fields."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(test_search_session.id)
        assert data["status"] == "completed"
        assert "result_count" in data
        assert "model_name" in data

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /sessions/{session_id} without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}",
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Non-existent session UUID → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """Session belonging to another project → 404 (scoped query returns nothing)."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}",
            headers=auth_headers,
        )
        # The service scopes by project_id so another project's session returns 404
        assert resp.status_code == 404

    async def test_locale_ja_no_500(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """locale=ja does not cause a 500."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Route 4: PATCH /sessions/{session_id}  (rename)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateSession:
    """Smoke tests for PATCH /sessions/{session_id} (name update)."""

    async def test_happy_path_rename(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Renaming succeeds and is reflected in a follow-up GET."""
        new_name = "Renamed Smoke Session"
        resp = await client.patch(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}",
            headers=auth_headers,
            json={"name": new_name},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == new_name

        # Follow-up GET must reflect the new name
        get_resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}",
            headers=auth_headers,
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == new_name

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """PATCH without credentials → 401."""
        resp = await client.patch(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}",
            json={"name": "x"},
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """PATCH on non-existent session UUID → 404."""
        resp = await client.patch(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}",
            headers=auth_headers,
            json={"name": "ghost"},
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """PATCH session from another project → 404 (scoped query)."""
        resp = await client.patch(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}",
            headers=auth_headers,
            json={"name": "should-not-rename"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route 5: GET /sessions/{session_id}/distribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionDistribution:
    """Smoke tests for GET /sessions/{session_id}/distribution."""

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Returns 200 with expected distribution shape."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == str(test_search_session.id)
        assert "bins" in data
        assert "total_count" in data
        assert isinstance(data["bins"], list)
        assert isinstance(data["total_count"], int)

    async def test_explicit_bin_width(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Explicit bin_width param is accepted and response shape is correct."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/distribution",
            headers=auth_headers,
            params={"bin_width": 0.1},
        )
        assert resp.status_code == 200
        assert "bins" in resp.json()

    async def test_species_key_filter(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """species_key param filters to a single species; response shape is correct."""
        species_key = "aaaaaaaa-0000-0000-0000-000000000001"
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/distribution",
            headers=auth_headers,
            params={"species_key": species_key},
        )
        assert resp.status_code == 200

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /distribution without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/distribution",
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Non-existent session UUID → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """Distribution for another project's session → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}/distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_zero_vector_embedding_does_not_crash(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
        search_recording: Recording,
        test_search_session: SearchSession,
    ) -> None:
        """Regression: a zero-vector embedding row must not crash /distribution.

        Cosine distance against a zero vector is mathematically undefined and
        pgvector returns NaN. ``int(NaN)`` previously raised ``ValueError`` from
        the histogram bin assignment loop, producing a 500. The service now
        filters NaN at the SQL level, so the zero-vector row is silently
        skipped and the response is 200 with a sensible bin shape.
        """
        # Seed a degenerate zero-vector embedding alongside the existing unit
        # vector embedding (already created by ``test_search_session`` fixture
        # via its dependency on ``search_embedding``).
        zero_vector = [0.0] * _EMBEDDING_DIM
        zero_emb = Embedding(
            recording_id=search_recording.id,
            model_name="perch",
            start_time=5.0,
            end_time=10.0,
            vector=zero_vector,
        )
        db_session.add(zero_emb)
        await db_session.commit()

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "bins" in data
        assert "total_count" in data
        # Zero-vector row was skipped (not crashed). The non-zero embedding
        # still contributes, so total_count is at least 1 but never includes
        # the NaN row.
        assert isinstance(data["total_count"], int)
        assert data["total_count"] >= 1


# ---------------------------------------------------------------------------
# Route 6: GET /sessions/{session_id}/time-distribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionTimeDistribution:
    """Smoke tests for GET /sessions/{session_id}/time-distribution."""

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Returns 200 with expected time-distribution shape."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/time-distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == str(test_search_session.id)
        assert "cells" in data
        assert "timezone" in data
        assert isinstance(data["cells"], list)

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /time-distribution without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/time-distribution",
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Non-existent session UUID → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/time-distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """Time-distribution for another project's session → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}/time-distribution",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route 7: GET /sessions/{session_id}/sample
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionSample:
    """Smoke tests for GET /sessions/{session_id}/sample."""

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Returns 200 with expected sample response shape."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/sample",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == str(test_search_session.id)
        assert "results" in data
        assert "total_in_range" in data
        assert isinstance(data["results"], list)
        assert isinstance(data["total_in_range"], int)

    async def test_with_similarity_range_and_limit(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """min_similarity / max_similarity / limit params are accepted."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/sample",
            headers=auth_headers,
            params={"min_similarity": 0.0, "max_similarity": 0.5, "limit": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 5

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /sample without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/sample",
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Non-existent session UUID → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/sample",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """Sample from another project's session → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}/sample",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route 8: GET /sessions/{session_id}/export-recordings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportRecordings:
    """Smoke tests for GET /sessions/{session_id}/export-recordings.

    The endpoint returns a CSV of all recordings × species similarities.
    Happy path: session has results + project has at least one recording.
    The route requires session.results to be non-null (returns 404 otherwise).
    """

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Returns 200 streaming CSV with Content-Disposition header.

        Strengthened to guard the behavioural contract during the refactor:
        - Header row is the exact 7-column list (parsed via csv.reader, not substring match).
        - Content-Disposition filename matches the documented
          ``search_summary_{safe_name}_{YYYYMMDD}.csv`` shape.
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "attachment" in resp.headers.get("content-disposition", "")
        # CSV must at minimum contain the header row
        content = resp.text
        assert "recording_filename" in content
        # Header row is an exact, ordered column list. Parsing via csv.reader
        # avoids brittle substring matches and catches column-order regressions.
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert rows, "CSV must contain at least the header row"
        assert rows[0] == [
            "recording_filename",
            "recording_datetime",
            "scientific_name",
            "common_name",
            "max_similarity",
            "min_similarity",
            "avg_similarity",
        ]
        # Content-Disposition filename shape is part of the FE blob-download
        # contract (apps/web/src/lib/api/search.ts) and must not drift.
        cd = resp.headers.get("content-disposition", "")
        assert re.search(
            r'^attachment; filename="search_summary_.+_\d{8}\.csv"$', cd
        ), f"unexpected Content-Disposition: {cd!r}"

    async def test_locale_en_explicit_no_500(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """locale=en (explicit) returns 200 CSV."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
            params={"locale": "en"},
        )
        assert resp.status_code == 200

    async def test_locale_ja_no_500_with_gbif_mocked(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: locale=ja must not 500 even when GBIF lookup raises.

        Previously the export route called ``_enrich_species_config_with_locale``
        without an exception guard. A failure inside the GBIF resolution path
        (e.g. ``MissingGreenlet`` from misuse of the async DB session) bubbled
        up and produced a 500 to the API caller. The route now catches the
        failure and degrades to scientific names. We force the failure by
        patching ``_resolve_vernacular_via_gbif`` to raise.
        """
        from echoroo.api.v1.search import utils as search_utils

        async def _boom(*_args: object, **_kwargs: object) -> str | None:
            raise RuntimeError("simulated GBIF / greenlet failure")

        monkeypatch.setattr(search_utils, "_resolve_vernacular_via_gbif", _boom)

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        # The header row must still be present even though enrichment failed
        assert "recording_filename" in resp.text
        # Degrade-to-raw behaviour: when GBIF lookup raises, the route falls
        # back to the raw species_config. The raw config for this fixture has
        # common_name="Common Blackbird", so it MUST still appear in the CSV
        # even though ja-locale enrichment failed.  This is the key regression
        # guarded for the upcoming helper extraction of locale enrichment.
        assert "Common Blackbird" in resp.text

    async def test_locale_ja_no_500_when_enrichment_expires_session(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: export must not 500 when enrichment expires ORM objects.

        In production, ``_enrich_species_config_with_locale`` delegates to
        ``_resolve_vernacular_via_gbif`` for species not yet cached locally.
        That helper inserts a Taxon row, may hit a duplicate-key race, and
        on failure runs ``await db.rollback()`` before returning None
        (best-effort caching, continue-on-error).

        ``rollback()`` EXPIRES every ORM-tracked attribute on every
        instance in the session — regardless of ``expire_on_commit``. Any
        later access to ``session.parameters`` / ``session.name`` triggers
        an implicit lazy-load outside the async context and raises
        ``MissingGreenlet``.

        The previous unit smoke (``test_locale_ja_no_500_with_gbif_mocked``)
        forced the GBIF call to raise BEFORE rollback — so the route's
        ``try/except`` caught it and never exercised the
        rollback-then-access path. This test simulates the "enrichment
        returned successfully after rolling back internally" path by
        monkey-patching ``_resolve_locale_common_names`` to perform
        ``await db.rollback()`` and return an empty mapping.

        If the route continues to access raw ORM attributes after this
        rollback, the response is 500 with ``MissingGreenlet`` in the
        log.  The fix snapshots every needed session attribute to a
        plain-old-data proxy before any expiration-capable helper is
        invoked, making the helper chain immune to post-rollback
        expiration.
        """
        from echoroo.api.v1.search import sessions as search_sessions

        monkeypatch.setattr(
            search_sessions,
            "_resolve_locale_common_names",
            _make_expiring_resolver(),
        )

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
            params={"locale": "ja"},
        )
        # Must NOT be 500. If the route still holds the ORM session and
        # accesses session.parameters / session.name after the rollback,
        # this would be 500 with MissingGreenlet in the stack trace.
        assert resp.status_code == 200, (
            f"export must not 500 when enrichment rolls back; got {resp.status_code}: "
            f"{resp.text[:500]}"
        )
        assert "text/csv" in resp.headers.get("content-type", "")
        # Header row still emitted (route ran to completion)
        assert "recording_filename" in resp.text
        # Content-Disposition filename relies on session.name / session.id;
        # those attrs must still be accessible post-rollback via the snapshot.
        cd = resp.headers.get("content-disposition", "")
        assert re.search(
            r'^attachment; filename="search_summary_.+_\d{8}\.csv"$', cd
        ), f"unexpected Content-Disposition (snapshot of session.name failed?): {cd!r}"

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /export-recordings without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/export-recordings",
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Non-existent session UUID → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """Export-recordings for another project's session → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_dataset_id_filter(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_project: Project,
        search_site: Site,
        search_dataset: Dataset,
        test_search_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """When session.parameters.dataset_id is set, recordings from other datasets must not appear in the CSV.

        Creates a second dataset + recording in the same project, then updates the
        session to filter on the original dataset. The "other" filename must be
        absent from the CSV body.  Guards the dataset_id branch that is otherwise
        unreachable by the default fixtures (which set dataset_id=None).
        """
        # Seed a second dataset + recording in a different dataset within the
        # same project. Its filename must be absent from the filtered CSV.
        other_dataset = Dataset(
            project_id=test_project.id,
            site_id=search_site.id,
            created_by_id=test_project.owner_id,
            name="Other Dataset",
            audio_dir="/data/audio/other-dataset",
            status=DatasetStatus.COMPLETED,
        )
        db_session.add(other_dataset)
        await db_session.commit()
        await db_session.refresh(other_dataset)

        other_recording = Recording(
            dataset_id=other_dataset.id,
            filename="should_not_appear.wav",
            path="should_not_appear.wav",
            duration=30.0,
            samplerate=48000,
            channels=1,
            datetime_parse_status=DatetimeParseStatus.PENDING,
            time_expansion=1.0,
        )
        db_session.add(other_recording)

        # Pin the session to the original dataset only.
        test_search_session.parameters = {
            "min_similarity": 0.1,
            "limit_per_species": 100,
            "dataset_id": str(search_dataset.id),
        }
        db_session.add(test_search_session)
        await db_session.commit()
        await db_session.refresh(test_search_session)

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.text
        # Original dataset's recording (from the test_search_session fixture)
        # must still be present; the other-dataset filename must NOT leak in.
        assert "smoke_test_recording.wav" in body
        assert "should_not_appear.wav" not in body

    async def test_no_recordings_empty_csv(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_project: Project,
        search_site: Site,
        test_search_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """Session pinned to an empty dataset → 200 + header-only CSV + filename preserved.

        Covers the ``all_recordings == []`` branch (Block F) which produces a
        header-only CSV and still emits a well-formed Content-Disposition
        filename.
        """
        empty_dataset = Dataset(
            project_id=test_project.id,
            site_id=search_site.id,
            created_by_id=test_project.owner_id,
            name="Empty Dataset",
            audio_dir="/data/audio/empty-dataset",
            status=DatasetStatus.COMPLETED,
        )
        db_session.add(empty_dataset)
        await db_session.commit()
        await db_session.refresh(empty_dataset)

        test_search_session.parameters = {
            "min_similarity": 0.1,
            "limit_per_species": 100,
            "dataset_id": str(empty_dataset.id),
        }
        db_session.add(test_search_session)
        await db_session.commit()
        await db_session.refresh(test_search_session)

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        rows = list(csv.reader(io.StringIO(resp.text)))
        assert len(rows) == 1, f"expected header-only CSV, got {len(rows)} rows"
        assert rows[0] == [
            "recording_filename",
            "recording_datetime",
            "scientific_name",
            "common_name",
            "max_similarity",
            "min_similarity",
            "avg_similarity",
        ]
        cd = resp.headers.get("content-disposition", "")
        assert re.search(
            r'^attachment; filename="search_summary_.+_\d{8}\.csv"$', cd
        ), f"unexpected Content-Disposition: {cd!r}"

    async def test_results_malformed_404(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """session.results["results"] is not a dict → 404 with documented detail.

        Regression guard for the H1 ``_build_species_labels`` extraction: the
        helper must keep raising the same 404 + detail when ``results`` is
        malformed (e.g. a stringified payload from a legacy run).
        """
        test_search_session.results = {"results": "not-a-dict"}
        db_session.add(test_search_session)
        await db_session.commit()
        await db_session.refresh(test_search_session)

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert resp.json().get("detail") == "Session has no results to export"

    async def test_empty_species_results_404(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """session.results["results"] is an empty dict → 404 with species-specific detail.

        Regression guard for the H1 extraction: the "no species" 404 must use
        the dedicated detail string to stay distinguishable from the generic
        no-results case.
        """
        test_search_session.results = {"results": {}}
        db_session.add(test_search_session)
        await db_session.commit()
        await db_session.refresh(test_search_session)

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export-recordings",
            headers=auth_headers,
        )
        assert resp.status_code == 404
        assert (
            resp.json().get("detail") == "Session has no species results to export"
        )


# ---------------------------------------------------------------------------
# Route 9: GET /sessions/{session_id}/export/csv
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExportCsv:
    """Smoke tests for GET /sessions/{session_id}/export/csv.

    The endpoint exports session annotations as a CamtrapDP CSV.
    With no annotations, it returns 200 with just the header row — the
    empty-200 case is intentional and is the cheapest valid state to assert.
    """

    async def test_happy_path_no_annotations(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session: SearchSession,
    ) -> None:
        """Returns 200 CSV with header row even when there are no annotations.

        Asserting empty-200 is intentional: seeding full annotation rows is
        expensive and the real-world zero-annotation state is valid.
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session.id}/export/csv",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "attachment" in resp.headers.get("content-disposition", "")
        # CamtrapDP header must be present
        content = resp.text
        assert "observationID" in content

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /export/csv without credentials → 401."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/export/csv",
        )
        assert resp.status_code == 401

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """Non-existent session UUID → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/export/csv",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        test_search_session_other_project: SearchSession,
    ) -> None:
        """Export/csv for another project's session → 404."""
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{test_search_session_other_project.id}/export/csv",
            headers=auth_headers,
        )
        assert resp.status_code == 404
