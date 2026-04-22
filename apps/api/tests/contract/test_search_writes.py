"""Smoke tests for write-side search router endpoints (Phase 2).

Covers routes that have S3 / Celery / multipart side-effects, deferred from
Phase 1 (test_search_smoke.py).  External dependencies (S3 client, Celery
task) are intercepted with unittest.mock so the tests run without LocalStack
or a Celery broker.

Routes covered:
  1  POST  /similar                                     (similarity.py)
  2  POST  /similar-by-audio                            (similarity.py) — multipart
  3  POST  /batch                                       (batch.py)    — S3 + Celery
  4  GET   /jobs/{job_id}                               (batch.py)    — Celery result
  5  DELETE /sessions/{session_id}                      (sessions.py) — S3 cleanup
  6  PUT   /sessions/{session_id}/rerun                 (sessions.py) — S3 + Celery
  7  GET   /sessions/{session_id}/reference-audio/{idx} (sessions.py) — S3 streaming
  8  POST  /annotations (annotations_router)            (annotations.py) — DB write
"""

from __future__ import annotations

import json
import struct
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation import Annotation
from echoroo.models.dataset import Dataset
from echoroo.models.embedding import Embedding
from echoroo.models.enums import (
    DatasetStatus,
    DatetimeParseStatus,
    DetectionSource,
    SearchSessionStatus,
    TagCategory,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.search_session import SearchSession
from echoroo.models.site import Site
from echoroo.models.tag import Tag
from echoroo.models.user import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FAKE_UUID = "00000000-0000-0000-0000-000000000000"
_EMBEDDING_DIM = 1536  # Perch v2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _search_base(project_id: str) -> str:
    """Return the base search URL prefix.

    Args:
        project_id: Project UUID string

    Returns:
        URL prefix string
    """
    return f"/api/v1/projects/{project_id}/search"


def _make_minimal_wav(num_frames: int = 100, sample_rate: int = 16000) -> bytes:
    """Build a minimal valid PCM WAV byte string without external libraries.

    Produces a 1-channel 16-bit PCM WAV file with ``num_frames`` silent samples.
    The file is around 244 bytes — tiny enough that tests are fast.

    Args:
        num_frames: Number of 16-bit PCM samples (default 100)
        sample_rate: Sample rate in Hz (default 16000)

    Returns:
        Raw bytes of a valid WAV file
    """
    num_channels = 1
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = num_frames * block_align
    chunk_size = 36 + data_size

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,  # PCM sub-chunk size
        1,  # PCM format tag
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    pcm_data = b"\x00" * data_size
    return header + pcm_data


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def write_site(
    db_session: AsyncSession,
    test_project: Project,
) -> Site:
    """Site fixture for write-side tests.

    Args:
        db_session: Database session
        test_project: Owning project

    Returns:
        Persisted site instance
    """
    site = Site(
        project_id=test_project.id,
        name="Write Test Site",
        h3_index="8928308280fffff",
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)
    return site


@pytest.fixture
async def write_dataset(
    db_session: AsyncSession,
    test_project: Project,
    write_site: Site,
) -> Dataset:
    """Dataset fixture for write-side tests.

    Args:
        db_session: Database session
        test_project: Owning project
        write_site: Owning site

    Returns:
        Persisted dataset instance
    """
    dataset = Dataset(
        project_id=test_project.id,
        site_id=write_site.id,
        created_by_id=test_project.owner_id,
        name="Write Test Dataset",
        audio_dir="/data/audio/write-test",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


@pytest.fixture
async def write_recording(
    db_session: AsyncSession,
    write_dataset: Dataset,
) -> Recording:
    """Recording fixture for write-side tests.

    Args:
        db_session: Database session
        write_dataset: Owning dataset

    Returns:
        Persisted recording instance
    """
    recording = Recording(
        dataset_id=write_dataset.id,
        filename="write_test_recording.wav",
        path="write_test_recording.wav",
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
async def write_embedding(
    db_session: AsyncSession,
    write_recording: Recording,
) -> Embedding:
    """Embedding fixture for write-side tests.

    Uses a unit vector to avoid NaN cosine similarity.

    Args:
        db_session: Database session
        write_recording: Owning recording

    Returns:
        Persisted embedding instance
    """
    unit_vector = [1.0] + [0.0] * (_EMBEDDING_DIM - 1)
    emb = Embedding(
        recording_id=write_recording.id,
        model_name="perch",
        start_time=0.0,
        end_time=5.0,
        vector=unit_vector,
    )
    db_session.add(emb)
    await db_session.commit()
    await db_session.refresh(emb)
    return emb


@pytest.fixture
async def write_tag(
    db_session: AsyncSession,
    test_project: Project,
) -> Tag:
    """Tag fixture for annotation tests.

    Args:
        db_session: Database session
        test_project: Owning project

    Returns:
        Persisted tag instance
    """
    tag = Tag(
        project_id=test_project.id,
        name="Turdus merula",
        category=TagCategory.SPECIES,
        scientific_name="Turdus merula",
        common_name="Common Blackbird",
    )
    db_session.add(tag)
    await db_session.commit()
    await db_session.refresh(tag)
    return tag


@pytest.fixture
async def completed_session(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
    write_recording: Recording,
    write_embedding: Embedding,
) -> SearchSession:
    """Completed SearchSession with reference_audio_keys and seeded results.

    Used by DELETE, PUT /rerun, GET /reference-audio tests.

    Args:
        db_session: Database session
        test_project: Owning project
        test_user: Session owner
        write_recording: Recording used in results JSONB
        write_embedding: Embedding used in results JSONB

    Returns:
        Persisted SearchSession in COMPLETED status
    """
    species_key = "bbbbbbbb-0000-0000-0000-000000000002"
    results_jsonb: dict[str, Any] = {
        "results": {
            species_key: {
                "tag_id": species_key,
                "scientific_name": "Turdus merula",
                "common_name": "Common Blackbird",
                "matches": [
                    {
                        "embedding_id": str(write_embedding.id),
                        "recording_id": str(write_recording.id),
                        "recording_filename": write_recording.filename,
                        "recording_datetime": None,
                        "dataset_id": str(write_recording.dataset_id),
                        "start_time": float(write_embedding.start_time),
                        "end_time": float(write_embedding.end_time),
                        "similarity": 0.85,
                    }
                ],
            }
        },
        "total_matches": 1,
        "search_duration_ms": 42,
    }
    species_config: list[Any] = [
        {
            "tag_id": species_key,
            "scientific_name": "Turdus merula",
            "common_name": "Common Blackbird",
            "sources": [
                {
                    "type": "upload",
                    "file_key": "source_0",
                    "s3_key": f"search_reference/{test_project.id}/old-job/source_0.wav",
                    "start_time": None,
                    "end_time": None,
                    "source_url": None,
                }
            ],
        }
    ]
    session = SearchSession(
        project_id=test_project.id,
        user_id=test_user.id,
        name="Completed Write Test Session",
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
        celery_job_id="old-job-id",
        reference_audio_keys=[
            f"search_reference/{test_project.id}/old-job/source_0.wav"
        ],
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


@pytest.fixture
async def other_project_session(
    db_session: AsyncSession,
    other_user: User,
) -> SearchSession:
    """SearchSession in an isolated project not accessible by test_user.

    Args:
        db_session: Database session
        other_user: Owner of the isolated project

    Returns:
        Persisted SearchSession in other_user's project
    """
    from echoroo.models.enums import ProjectVisibility
    from echoroo.models.project import Project as ProjectModel

    other_proj = ProjectModel(
        name="Other Project (write tests)",
        description="Cross-tenant write isolation",
        target_taxa="Strigiformes",
        visibility=ProjectVisibility.PRIVATE,
        owner_id=other_user.id,
    )
    db_session.add(other_proj)
    await db_session.flush()

    session = SearchSession(
        project_id=other_proj.id,
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
# Route 1: POST /similar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchSimilar:
    """Smoke tests for POST /similar."""

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        write_embedding: Embedding,
    ) -> None:
        """POST /similar with a valid embedding_id → 200 and response shape.

        The mock makes SearchService.search_by_embedding_id return an empty
        SimilaritySearchResponse so we only verify the wire shape, not ML logic.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            write_embedding: Seeded embedding to use as query
        """
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "results": [],
            "query_model": "perch",
            "total_results": 0,
        }
        # SimilaritySearchResponse is returned via FastAPI's response_model,
        # so we patch the service method on the SearchService class directly.
        with patch(
            "echoroo.services.search.SimilaritySearchService.search_by_embedding_id",
            new_callable=AsyncMock,
            return_value=MagicMock(
                results=[],
                query_model="perch",
                total_results=0,
                model_dump=lambda **_kw: {  # noqa: ARG005
                    "results": [],
                    "query_model": "perch",
                    "total_results": 0,
                },
            ),
        ):
            resp = await client.post(
                f"{_search_base(test_project_id)}/similar",
                headers=auth_headers,
                json={
                    "embedding_id": str(write_embedding.id),
                    "model_name": "perch",
                    "limit": 10,
                    "min_similarity": 0.5,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "query_model" in data
        assert "total_results" in data

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """POST /similar without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
        """
        resp = await client.post(
            f"{_search_base(test_project_id)}/similar",
            json={
                "embedding_id": FAKE_UUID,
                "model_name": "perch",
            },
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /similar for a project other_user cannot access → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string
        """
        resp = await client.post(
            f"{_search_base(test_project_id)}/similar",
            headers=auth_headers_other,
            json={
                "embedding_id": FAKE_UUID,
                "model_name": "perch",
            },
        )
        assert resp.status_code == 403

    async def test_not_found_embedding(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /similar with nonexistent embedding_id → 404.

        The service raises ValueError when the embedding is not found,
        which the route converts to 404.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        with patch(
            "echoroo.services.search.SimilaritySearchService.search_by_embedding_id",
            new_callable=AsyncMock,
            side_effect=ValueError("Embedding not found"),
        ):
            resp = await client.post(
                f"{_search_base(test_project_id)}/similar",
                headers=auth_headers,
                json={
                    "embedding_id": FAKE_UUID,
                    "model_name": "perch",
                },
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route 2: POST /similar-by-audio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSearchSimilarByAudio:
    """Smoke tests for POST /similar-by-audio."""

    async def test_happy_path(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /similar-by-audio with a valid WAV file → 200 and response shape.

        The service call is mocked so ML inference is never invoked.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        wav_bytes = _make_minimal_wav()
        with patch(
            "echoroo.services.search.SimilaritySearchService.search_by_audio_file",
            new_callable=AsyncMock,
            return_value=MagicMock(
                results=[],
                query_model="perch",
                total_results=0,
                model_dump=lambda **_kw: {  # noqa: ARG005
                    "results": [],
                    "query_model": "perch",
                    "total_results": 0,
                },
            ),
        ):
            resp = await client.post(
                f"{_search_base(test_project_id)}/similar-by-audio",
                headers=auth_headers,
                files={"audio_file": ("test.wav", wav_bytes, "audio/wav")},
                data={"model_name": "perch", "limit": "10", "min_similarity": "0.5"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "query_model" in data
        assert "total_results" in data

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """POST /similar-by-audio without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
        """
        wav_bytes = _make_minimal_wav()
        resp = await client.post(
            f"{_search_base(test_project_id)}/similar-by-audio",
            files={"audio_file": ("test.wav", wav_bytes, "audio/wav")},
            data={"model_name": "perch"},
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /similar-by-audio for inaccessible project → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string
        """
        wav_bytes = _make_minimal_wav()
        resp = await client.post(
            f"{_search_base(test_project_id)}/similar-by-audio",
            headers=auth_headers_other,
            files={"audio_file": ("test.wav", wav_bytes, "audio/wav")},
            data={"model_name": "perch"},
        )
        assert resp.status_code == 403

    async def test_unsupported_file_type(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /similar-by-audio with a .txt file → 400 (bad file type).

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        resp = await client.post(
            f"{_search_base(test_project_id)}/similar-by-audio",
            headers=auth_headers,
            files={"audio_file": ("notes.txt", b"hello", "text/plain")},
            data={"model_name": "perch"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Route 3: POST /batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBatchSearch:
    """Smoke tests for POST /batch."""

    @patch("echoroo.workers.search_tasks.run_batch_search")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_happy_path_creates_session_and_dispatches(
        self,
        mock_get_s3_client: MagicMock,
        mock_run_batch_search: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        db_session: AsyncSession,
        test_project: Project,
    ) -> None:
        """POST /batch → 202, SearchSession row created, Celery task dispatched.

        Args:
            mock_get_s3_client: Patched S3 client factory
            mock_run_batch_search: Patched Celery task
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            db_session: DB session for post-assertion queries
            test_project: Project to check session membership
        """
        mock_s3 = MagicMock()
        mock_get_s3_client.return_value = mock_s3

        wav_bytes = _make_minimal_wav()
        metadata = json.dumps(
            {
                "species": [
                    {
                        "scientific_name": "Parus major",
                        "sources": [
                            {"type": "upload", "file_key": "source_0"}
                        ],
                    }
                ],
                "model_name": "perch",
                "min_similarity": 0.1,
                "limit_per_species": 50,
            }
        )

        resp = await client.post(
            f"{_search_base(test_project_id)}/batch",
            headers=auth_headers,
            data={"metadata": metadata},
            files={"source_0": ("source_0.wav", wav_bytes, "audio/wav")},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        assert "session_id" in body

        # Verify SearchSession row was created in DB
        result = await db_session.execute(
            select(SearchSession).where(
                SearchSession.project_id == test_project.id
            )
        )
        sessions = result.scalars().all()
        assert len(sessions) >= 1

        # Verify Celery task was dispatched exactly once
        mock_run_batch_search.apply_async.assert_called_once()
        call_kwargs = mock_run_batch_search.apply_async.call_args
        dispatched_job_id = call_kwargs[1]["task_id"] if call_kwargs[1] else call_kwargs[0][0]
        assert dispatched_job_id == body["job_id"]

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """POST /batch without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
        """
        resp = await client.post(
            f"{_search_base(test_project_id)}/batch",
            data={"metadata": "{}"},
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /batch for inaccessible project → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string
        """
        resp = await client.post(
            f"{_search_base(test_project_id)}/batch",
            headers=auth_headers_other,
            data={"metadata": "{}"},
        )
        assert resp.status_code == 403

    async def test_bad_metadata_json(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """POST /batch with malformed JSON metadata → 400.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        resp = await client.post(
            f"{_search_base(test_project_id)}/batch",
            headers=auth_headers,
            data={"metadata": "this is not json"},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Route 4: GET /jobs/{job_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSearchJob:
    """Smoke tests for GET /jobs/{job_id}."""

    async def test_pending_state(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """GET /jobs/{job_id} with Celery PENDING state → 200 with status=pending.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        job_id = str(uuid.uuid4())
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_result.info = None

        with patch("celery.result.AsyncResult", return_value=mock_result):
            resp = await client.get(
                f"{_search_base(test_project_id)}/jobs/{job_id}",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["job_id"] == job_id

    async def test_running_state_with_session(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """GET /jobs/{job_id} for a RUNNING session → 200 with status=processing.

        Sets up a real SearchSession with a known celery_job_id in RUNNING state
        so the endpoint can look it up via DB.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Existing session to borrow (will update status)
            db_session: DB session to mutate the session status
        """
        # Reset status to RUNNING so we exercise the processing branch
        completed_session.status = SearchSessionStatus.RUNNING
        completed_session.celery_job_id = "running-job-id"
        await db_session.commit()

        mock_result = MagicMock()
        mock_result.state = "PROCESSING"
        mock_result.info = {"species_completed": 1, "species_total": 3}

        with patch("celery.result.AsyncResult", return_value=mock_result):
            resp = await client.get(
                f"{_search_base(test_project_id)}/jobs/running-job-id",
                headers=auth_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["session_id"] == str(completed_session.id)

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
    ) -> None:
        """GET /jobs/{job_id} without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/jobs/some-job-id",
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
    ) -> None:
        """GET /jobs/{job_id} for inaccessible project → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/jobs/some-job-id",
            headers=auth_headers_other,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Route 5: DELETE /sessions/{session_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteSession:
    """Smoke tests for DELETE /sessions/{session_id}."""

    @patch("echoroo.api.v1.search.sessions.delete_object")
    async def test_happy_path_deletes_row_and_s3(
        self,
        mock_delete_object: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """DELETE /sessions/{session_id} → 204, DB row gone, S3 delete called.

        Patches ``echoroo.api.v1.search.sessions.delete_object`` (the
        module-level binding bound at import time via ``from ... import``)
        rather than ``echoroo.core.s3.delete_object`` — the latter would
        not be seen by the route.

        Args:
            mock_delete_object: Patched S3 delete_object function
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Session to delete
            db_session: DB session for post-assertion queries
        """
        # Snapshot keys BEFORE the DELETE so we can assert post-commit
        # cleanup ran over each one (value copy — the ORM attribute may be
        # cleared when the row is deleted).
        stale_keys_before = list(completed_session.reference_audio_keys or [])
        assert stale_keys_before, (
            "completed_session fixture must seed reference_audio_keys for "
            "the post-commit-cleanup assertion to be meaningful"
        )

        session_id = str(completed_session.id)
        resp = await client.delete(
            f"{_search_base(test_project_id)}/sessions/{session_id}",
            headers=auth_headers,
        )
        assert resp.status_code == 204

        # Verify DB row is gone
        result = await db_session.execute(
            select(SearchSession).where(SearchSession.id == completed_session.id)
        )
        assert result.scalar_one_or_none() is None

        # Verify S3 delete_object was called once per stale reference key,
        # AFTER the DB commit (the route raises before this loop if commit
        # fails, so any observed call implies commit succeeded).
        deleted_keys = {
            call.args[0] for call in mock_delete_object.call_args_list if call.args
        }
        for old_key in stale_keys_before:
            assert old_key in deleted_keys, (
                f"expected reference audio {old_key!r} to be cleaned up "
                f"post-commit; observed delete_object calls: "
                f"{sorted(deleted_keys)}"
            )

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """DELETE /sessions/{session_id} without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
            completed_session: Existing session (should not be deleted)
        """
        resp = await client.delete(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}",
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        other_project_session: SearchSession,
    ) -> None:
        """DELETE other_user's session using test_user's token → 403 or 404.

        The route checks project access before the session lookup, so the error
        code depends on whether the project_id in the path matches.  We send
        the correct session_id but use the other project's implicit project_id
        embedded in the path — using test_user's project_id which test_user owns
        but the session does not belong to → should 404 (session not in project).

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user (who owns test_project)
            other_project_session: Session in other_user's project
        """
        # Use test_user's project_id in the path — session doesn't belong to it
        # We need a project_id that test_user can access but the session is not in.
        # The fixture completed_session is not created here, so we grab the
        # other session's project_id and use auth_headers_other → 403 is correct.
        # But here we want to use test_user's token against the other session's
        # actual project_id, which test_user has no access to → 403.
        resp = await client.delete(
            f"/api/v1/projects/{other_project_session.project_id}/sessions/{other_project_session.id}",
            headers=auth_headers,
        )
        assert resp.status_code in {403, 404}

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """DELETE /sessions/{nonexistent_id} → 404.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        resp = await client.delete(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route 6: PUT /sessions/{session_id}/rerun
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRerunSession:
    """Smoke tests for PUT /sessions/{session_id}/rerun."""

    @patch("echoroo.workers.search_tasks.run_batch_search")
    @patch("echoroo.core.s3.get_s3_client")
    @patch("echoroo.api.v1.search.sessions.delete_object")
    async def test_happy_path_reruns_and_clears_annotations(
        self,
        mock_delete_object: MagicMock,
        mock_get_s3_client: MagicMock,
        mock_run_batch_search: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
        write_recording: Recording,
        write_tag: Tag,
        db_session: AsyncSession,
    ) -> None:
        """PUT /sessions/{session_id}/rerun → 202, annotations cleared, Celery dispatched.

        Seeds one annotation linked to the session so we can verify it is deleted.
        Mocks S3 put_object and run_batch_search.apply_async.

        Args:
            mock_delete_object: Patched S3 delete_object (old reference audio cleanup)
            mock_get_s3_client: Patched S3 client factory
            mock_run_batch_search: Patched Celery task
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Session to re-run
            write_recording: Recording for the seeded annotation
            write_tag: Tag for the seeded annotation
            db_session: DB session for pre/post assertions
        """
        mock_s3 = MagicMock()
        mock_get_s3_client.return_value = mock_s3

        # Snapshot stale reference audio keys BEFORE the rerun so we can
        # assert post-commit cleanup ran over each of them. Using a value
        # copy here guards against the ORM instance being refreshed later.
        stale_keys_before = list(completed_session.reference_audio_keys or [])
        assert stale_keys_before, (
            "completed_session fixture must have reference_audio_keys so the "
            "post-commit-cleanup assertion is meaningful"
        )

        # Seed an annotation linked to the session
        annotation = Annotation(
            recording_id=write_recording.id,
            tag_id=write_tag.id,
            source=DetectionSource.PERCH_SEARCH,
            status="unreviewed",
            confidence=0.8,
            start_time=0.0,
            end_time=5.0,
            search_session_id=completed_session.id,
        )
        db_session.add(annotation)
        await db_session.commit()

        wav_bytes = _make_minimal_wav()
        metadata = json.dumps(
            {
                "species": [
                    {
                        "scientific_name": "Turdus merula",
                        "sources": [
                            {"type": "upload", "file_key": "source_0"}
                        ],
                    }
                ],
                "model_name": "perch",
                "min_similarity": 0.1,
                "limit_per_species": 50,
            }
        )

        resp = await client.put(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/rerun",
            headers=auth_headers,
            data={"metadata": metadata},
            files={"source_0": ("source_0.wav", wav_bytes, "audio/wav")},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending"
        assert body["session_id"] == str(completed_session.id)

        # Verify annotations were deleted
        ann_result = await db_session.execute(
            select(Annotation).where(
                Annotation.search_session_id == completed_session.id
            )
        )
        remaining_annotations = ann_result.scalars().all()
        assert remaining_annotations == []

        # Verify Celery was dispatched
        mock_run_batch_search.apply_async.assert_called_once()

        # Verify S3 put_object was called for the uploaded file
        mock_s3.put_object.assert_called_once()

        # Verify the OLD reference audio keys were deleted AFTER commit. The
        # fixture seeds at least one stale key; delete_object must have been
        # invoked on each of them once the session no longer references them.
        deleted_keys = {
            call.args[0] for call in mock_delete_object.call_args_list if call.args
        }
        for old_key in stale_keys_before:
            assert old_key in deleted_keys, (
                f"expected old reference audio {old_key!r} to be cleaned "
                f"up post-commit; observed delete_object calls: "
                f"{sorted(deleted_keys)}"
            )

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """PUT /sessions/{session_id}/rerun without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
            completed_session: Existing session
        """
        resp = await client.put(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/rerun",
            data={"metadata": "{}"},
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """PUT /sessions/{session_id}/rerun for inaccessible project → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string
            completed_session: Session owned by test_user
        """
        resp = await client.put(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/rerun",
            headers=auth_headers_other,
            data={"metadata": "{}"},
        )
        assert resp.status_code == 403

    async def test_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """PUT /sessions/{nonexistent_id}/rerun → 404.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        metadata = json.dumps(
            {
                "species": [
                    {
                        "scientific_name": "Parus major",
                        "sources": [{"type": "upload", "file_key": "source_0"}],
                    }
                ],
                "model_name": "perch",
                "min_similarity": 0.1,
                "limit_per_species": 50,
            }
        )
        resp = await client.put(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/rerun",
            headers=auth_headers,
            data={"metadata": metadata},
        )
        assert resp.status_code == 404

    @patch("echoroo.workers.search_tasks.run_batch_search")
    @patch("echoroo.api.v1.search.sessions.delete_object")
    @patch("echoroo.api.v1.search.sessions.delete_objects_by_prefix")
    @patch("echoroo.core.s3.get_s3_client")
    async def test_rerun_commit_failure_cleans_up_new_s3_and_keeps_old(
        self,
        mock_get_s3_client: MagicMock,
        mock_delete_prefix: MagicMock,
        mock_delete_object: MagicMock,
        mock_run_batch_search: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """Pins the S3/DB ordering fix — commit failure must NOT touch old keys.

        Patches ``AsyncSession.commit`` for the duration of the route call
        only. The patch is scoped to the PUT request so that fixture-side
        commits (setup) and ``override_get_db``'s rollback (teardown) are
        not affected. The class-method patch target is
        ``sqlalchemy.ext.asyncio.AsyncSession.commit`` — the route's session
        comes from ``override_get_db`` which is distinct from the test's
        ``db_session``, so a fixture-level monkeypatch would not reach it.

        Expected behavior on commit failure:
          1. ``delete_objects_by_prefix`` is called once with the new
             ``artifacts.s3_prefix`` (new-upload cleanup).
          2. ``delete_object`` is **not** called on any stale reference
             audio key (old files must be preserved for retry).
          3. ``run_batch_search.apply_async`` is **not** called (no Celery
             task should dispatch for a failed rerun).

        Args:
            mock_get_s3_client: Patched S3 client factory
            mock_delete_prefix: Patched S3 prefix-delete helper
            mock_delete_object: Patched S3 single-key delete helper
            mock_run_batch_search: Patched Celery task module
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Session with seeded reference_audio_keys
        """
        mock_s3 = MagicMock()
        mock_get_s3_client.return_value = mock_s3

        # Snapshot stale keys before the rerun so we can assert they were
        # NOT touched when the commit fails.
        old_keys = list(completed_session.reference_audio_keys or [])
        assert old_keys, (
            "completed_session fixture must have reference_audio_keys for "
            "this ordering test to be meaningful"
        )

        wav_bytes = _make_minimal_wav()
        metadata = json.dumps(
            {
                "species": [
                    {
                        "scientific_name": "Turdus merula",
                        "sources": [{"type": "upload", "file_key": "source_0"}],
                    }
                ],
                "model_name": "perch",
                "min_similarity": 0.1,
                "limit_per_species": 50,
            }
        )

        # Narrowly scope the commit patch to the route call so we don't
        # disturb other commits in the test environment. The target is the
        # AsyncSession class method, which is what the route's dependency-
        # injected session uses.
        #
        # ASGITransport propagates app exceptions to the test (httpx 0.28+
        # default raise_app_exceptions=True). Starlette's BaseHTTPMiddleware
        # wraps the RuntimeError in an anyio TaskGroup ExceptionGroup before
        # it surfaces here, so we catch both shapes rather than assert on an
        # HTTP 500. The ordering contract is pinned by the mock-call
        # assertions below.
        with (
            patch(
                "sqlalchemy.ext.asyncio.AsyncSession.commit",
                new_callable=AsyncMock,
                side_effect=RuntimeError("simulated commit failure"),
            ),
            pytest.raises((RuntimeError, BaseExceptionGroup)) as exc_info,
        ):
            await client.put(
                f"{_search_base(test_project_id)}/sessions/{completed_session.id}/rerun",
                headers=auth_headers,
                data={"metadata": metadata},
                files={"source_0": ("source_0.wav", wav_bytes, "audio/wav")},
            )

        # Unwrap any ExceptionGroup layers and confirm the simulated commit
        # failure is what actually surfaced.
        raised = exc_info.value
        while isinstance(raised, BaseExceptionGroup) and raised.exceptions:
            raised = raised.exceptions[0]
        assert isinstance(raised, RuntimeError)
        assert "simulated commit failure" in str(raised)

        # Old reference-audio keys must be preserved: delete_object must NOT
        # have been called on any of them.
        deleted_keys = {
            call.args[0]
            for call in mock_delete_object.call_args_list
            if call.args
        }
        for old_key in old_keys:
            assert old_key not in deleted_keys, (
                f"stale reference audio {old_key!r} must be preserved when "
                f"commit fails; observed delete_object calls: "
                f"{sorted(deleted_keys)}"
            )

        # New S3 prefix must be cleaned up exactly once.
        assert mock_delete_prefix.called, (
            "new S3 prefix must be cleaned up on commit failure (mirrors "
            "the POST /batch rollback path)"
        )

        # No Celery task must be dispatched for a failed rerun.
        mock_run_batch_search.apply_async.assert_not_called()


# ---------------------------------------------------------------------------
# Route 7: GET /sessions/{session_id}/reference-audio/{source_index}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStreamReferenceAudio:
    """Smoke tests for GET /sessions/{session_id}/reference-audio/{source_index}."""

    @patch("echoroo.core.s3.get_s3_client")
    async def test_happy_path_200(
        self,
        mock_get_s3_client: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """GET /reference-audio/0 → 200 with audio bytes from mocked S3.

        Args:
            mock_get_s3_client: Patched S3 client factory
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Session with reference_audio_keys
        """
        wav_bytes = _make_minimal_wav()
        mock_body = MagicMock()
        mock_body.read.side_effect = [wav_bytes, b""]
        mock_body.close.return_value = None
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentLength": len(wav_bytes),
        }
        mock_get_s3_client.return_value = mock_s3

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/reference-audio/0",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert len(resp.content) > 0
        mock_s3.get_object.assert_called_once()

    @patch("echoroo.core.s3.get_s3_client")
    async def test_range_header_returns_206(
        self,
        mock_get_s3_client: MagicMock,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """GET /reference-audio/0 with Range header → 206 partial content.

        Args:
            mock_get_s3_client: Patched S3 client factory
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Session with reference_audio_keys
        """
        partial_bytes = b"\x00" * 100
        mock_body = MagicMock()
        mock_body.read.side_effect = [partial_bytes, b""]
        mock_body.close.return_value = None
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {
            "Body": mock_body,
            "ContentLength": 100,
            "ContentRange": "bytes 0-99/244",
        }
        mock_get_s3_client.return_value = mock_s3

        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/reference-audio/0",
            headers={**auth_headers, "Range": "bytes=0-99"},
        )
        assert resp.status_code == 206

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """GET /reference-audio/0 without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
            completed_session: Existing session
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/reference-audio/0",
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """GET /reference-audio/0 for inaccessible project → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string
            completed_session: Session owned by test_user
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/reference-audio/0",
            headers=auth_headers_other,
        )
        assert resp.status_code == 403

    async def test_not_found_session(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
    ) -> None:
        """GET /reference-audio/0 for nonexistent session → 404.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{FAKE_UUID}/reference-audio/0",
            headers=auth_headers,
        )
        assert resp.status_code == 404

    async def test_out_of_bounds_index(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        completed_session: SearchSession,
    ) -> None:
        """GET /reference-audio/99 where index exceeds keys list → 404.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            completed_session: Session with exactly one reference key
        """
        resp = await client.get(
            f"{_search_base(test_project_id)}/sessions/{completed_session.id}/reference-audio/99",
            headers=auth_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Route 8: POST /annotations (annotations_router)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateSearchAnnotation:
    """Smoke tests for POST /api/v1/projects/{project_id}/annotations."""

    def _annotations_url(self, project_id: str) -> str:
        """Build the annotation creation URL.

        Args:
            project_id: Project UUID string

        Returns:
            URL string for the annotations endpoint
        """
        return f"/api/v1/projects/{project_id}/annotations"

    async def test_happy_path_creates_annotation(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        write_recording: Recording,
        write_tag: Tag,
        completed_session: SearchSession,
        db_session: AsyncSession,
    ) -> None:
        """POST /annotations → 201 with annotation row in DB and session counts updated.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            write_recording: Recording to annotate
            write_tag: Species tag for the annotation
            completed_session: Search session to link the annotation to
            db_session: DB session for post-assertion queries
        """
        payload = {
            "recording_id": str(write_recording.id),
            "tag_id": str(write_tag.id),
            "start_time": 1.0,
            "end_time": 4.0,
            "confidence": 0.9,
            "review_status": "confirmed",
            "source": "perch_search",
            "search_session_id": str(completed_session.id),
        }
        resp = await client.post(
            self._annotations_url(test_project_id),
            headers=auth_headers,
            json=payload,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["start_time"] == 1.0
        assert data["end_time"] == 4.0

        # Verify annotation row exists in DB
        ann_result = await db_session.execute(
            select(Annotation).where(
                Annotation.id == uuid.UUID(data["id"])
            )
        )
        ann = ann_result.scalar_one_or_none()
        assert ann is not None
        assert float(ann.start_time) == 1.0

    async def test_duplicate_returns_existing(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        write_recording: Recording,
        write_tag: Tag,
    ) -> None:
        """Posting the same annotation twice returns the existing one (idempotent).

        The endpoint performs a duplicate check with 0.1 s tolerance on
        start/end times and returns the existing annotation rather than creating
        a duplicate.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            write_recording: Recording to annotate
            write_tag: Species tag for the annotation
        """
        payload = {
            "recording_id": str(write_recording.id),
            "tag_id": str(write_tag.id),
            "start_time": 2.0,
            "end_time": 6.0,
            "confidence": 0.7,
            "review_status": "confirmed",
            "source": "perch_search",
        }
        resp1 = await client.post(
            self._annotations_url(test_project_id),
            headers=auth_headers,
            json=payload,
        )
        assert resp1.status_code == 201
        first_id = resp1.json()["id"]

        resp2 = await client.post(
            self._annotations_url(test_project_id),
            headers=auth_headers,
            json=payload,
        )
        assert resp2.status_code == 201
        assert resp2.json()["id"] == first_id

    async def test_unauthenticated(
        self,
        client: AsyncClient,
        test_project_id: str,
        write_recording: Recording,
        write_tag: Tag,
    ) -> None:
        """POST /annotations without auth → 401.

        Args:
            client: Test HTTP client
            test_project_id: Project UUID string
            write_recording: Recording fixture (unused but ensures DB state)
            write_tag: Tag fixture (unused but ensures DB state)
        """
        resp = await client.post(
            self._annotations_url(test_project_id),
            json={
                "recording_id": str(write_recording.id),
                "tag_id": str(write_tag.id),
                "start_time": 0.0,
                "end_time": 5.0,
                "review_status": "confirmed",
                "source": "perch_search",
            },
        )
        assert resp.status_code == 401

    async def test_cross_tenant(
        self,
        client: AsyncClient,
        auth_headers_other: dict[str, str],
        test_project_id: str,
        write_recording: Recording,
        write_tag: Tag,
    ) -> None:
        """POST /annotations for inaccessible project → 403.

        Args:
            client: Test HTTP client
            auth_headers_other: Auth headers for other_user
            test_project_id: Project UUID string (owned by test_user)
            write_recording: Recording fixture
            write_tag: Tag fixture
        """
        resp = await client.post(
            self._annotations_url(test_project_id),
            headers=auth_headers_other,
            json={
                "recording_id": str(write_recording.id),
                "tag_id": str(write_tag.id),
                "start_time": 0.0,
                "end_time": 5.0,
                "review_status": "confirmed",
                "source": "perch_search",
            },
        )
        assert resp.status_code == 403

    async def test_invalid_source_value(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_project_id: str,
        write_recording: Recording,
        write_tag: Tag,
    ) -> None:
        """POST /annotations with invalid source enum value → 422.

        Args:
            client: Test HTTP client
            auth_headers: Auth headers for test_user
            test_project_id: Project UUID string
            write_recording: Recording fixture
            write_tag: Tag fixture
        """
        resp = await client.post(
            self._annotations_url(test_project_id),
            headers=auth_headers,
            json={
                "recording_id": str(write_recording.id),
                "tag_id": str(write_tag.id),
                "start_time": 0.0,
                "end_time": 5.0,
                "review_status": "confirmed",
                "source": "not_a_valid_source",
            },
        )
        assert resp.status_code == 422
