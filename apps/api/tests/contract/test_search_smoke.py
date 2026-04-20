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
        h3_index="8928308280fffff",
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
    from echoroo.models.enums import ProjectVisibility
    from echoroo.models.project import Project

    other_project = Project(
        name="Other Project",
        description="Cross-tenant isolation project",
        target_taxa="Strigiformes",
        visibility=ProjectVisibility.PRIVATE,
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
        """Returns 200 streaming CSV with Content-Disposition header."""
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
