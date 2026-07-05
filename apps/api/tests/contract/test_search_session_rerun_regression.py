"""Regression tests for SearchSession rerun against the real annotation schema.

Branch ``fix/ws-c-search-session-rerun`` (bug #6): "編集して再検索" (edit &
re-run) 500'd because :meth:`SearchSessionService.reset_for_rerun` ran a raw
``DELETE FROM annotations WHERE search_session_id = :sid``. At the time the
literal table name ``annotations`` was a minimal detection-based shape (id /
detection_id / user_id / source / taxon_id / label) with **no**
``search_session_id`` column, so PostgreSQL raised ``UndefinedColumnError`` →
500. (That minimal ``annotations`` table and its ORM were later removed in P4 of
the annotation-consolidation effort, migration ``0030``.)

The review-annotation rows that carry ``search_session_id`` live on the
ORM model :class:`echoroo.models.recording_annotation.RecordingAnnotation`,
which maps to the canonical ``recording_annotations`` table. Every other method
on :class:`SearchSessionService` already queries that model; only
``reset_for_rerun`` hardcoded the wrong table via raw SQL. The fix is to issue
the delete through the same ORM model so it targets ``recording_annotations``
and is scoped to this session's review annotations.

Most tests here run ``reset_for_rerun`` against a **real Postgres session**
(the ``db_session`` fixture) with seeded ``RecordingAnnotation`` rows, so they
execute the actual generated SQL. The scoping test fails against the original
raw ``DELETE FROM annotations`` (``UndefinedColumnError``) and passes with the
ORM-based delete.

In addition, :class:`TestRerunEndpointRegression` drives the **actual HTTP
endpoint** ``PUT /web-api/v1/projects/{project_id}/search/sessions/{session_id}/rerun``
(W2-3 PR-18: the legacy ``/api/v1`` route was unmounted; the BFF adapter
delegates to the same ``rerun_search_session`` handler). It is the active
end-to-end guard that
the previously-only endpoint-level coverage (``test_search_writes.py``) lacked:
that whole file is under a Phase-14 skip, so before this class there was no
running test exercising the real rerun endpoint. This one seeds a COMPLETED
session with a stale ``recording_annotations`` row and a stale
``search_query_embeddings`` row, mocks the S3 client + Celery dispatch, and
asserts the call returns **202** (not a 500 / ``UndefinedColumnError``) with
the session flipped to PENDING and the stale rows cleared — i.e. it fails
against the original raw ``DELETE FROM annotations`` and passes with the fix.
"""

from __future__ import annotations

import json
import struct
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatetimeParseStatus,
    DetectionSource,
    DetectionStatus,
    SearchSessionStatus,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.search_query_embedding import SearchQueryEmbedding
from echoroo.models.search_session import SearchSession
from echoroo.models.site import Site
from echoroo.models.user import User
from echoroo.services.search_session import SearchSessionService

pytestmark = pytest.mark.asyncio


def _completed_results_jsonb(species_key: str) -> dict[str, object]:
    """Build a minimal stored BatchSearchResponse-shaped results dict."""
    return {
        "results": {
            species_key: {
                "tag_id": species_key,
                "scientific_name": "Turdus merula",
                "common_name": "Common Blackbird",
                "matches": [
                    {
                        "embedding_id": "00000000-0000-0000-0000-0000000000aa",
                        "recording_id": "00000000-0000-0000-0000-0000000000bb",
                        "start_time": 1.5,
                        "end_time": 3.0,
                        "similarity": 0.85,
                    }
                ],
            }
        },
        "total_matches": 1,
        "search_duration_ms": 42,
    }


async def _make_completed_session(
    db_session: AsyncSession,
    project: Project,
    user: User,
    *,
    name: str = "Rerun Regression Session",
) -> SearchSession:
    """Persist a COMPLETED SearchSession with stored results + non-zero counts."""
    session = SearchSession(
        project_id=project.id,
        user_id=user.id,
        name=name,
        status=SearchSessionStatus.COMPLETED,
        model_name="perch",
        parameters={"min_similarity": 0.1, "limit_per_species": 100, "dataset_id": None},
        species_config=[{"tag_id": "abc", "scientific_name": "Turdus merula"}],
        results=_completed_results_jsonb("abc"),
        result_count=1,
        confirmed_count=3,
        rejected_count=2,
        # ``celery_job_id`` is uniquely constrained; derive a per-session value so
        # the scoping test can persist two sessions.
        celery_job_id=f"job-original-{uuid.uuid4()}",
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _make_recording(
    db_session: AsyncSession,
    project: Project,
) -> Recording:
    """Persist a Site → Dataset → Recording chain for annotation FK targets."""
    site = Site(
        project_id=project.id,
        name="Rerun Regression Site",
        h3_index_member="8928308280fffff",
    )
    db_session.add(site)
    await db_session.flush()

    dataset = Dataset(
        project_id=project.id,
        site_id=site.id,
        created_by_id=project.owner_id,
        name="Rerun Regression Dataset",
        audio_dir="/data/audio/rerun-regression",
        status=DatasetStatus.COMPLETED,
    )
    db_session.add(dataset)
    await db_session.flush()

    recording = Recording(
        dataset_id=dataset.id,
        filename="rerun_regression.wav",
        path="rerun_regression.wav",
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


async def _make_review_annotation(
    db_session: AsyncSession,
    recording: Recording,
    search_session: SearchSession,
    *,
    status: DetectionStatus = DetectionStatus.UNREVIEWED,
) -> RecordingAnnotation:
    """Persist a RecordingAnnotation (→ recording_annotations_DEFERRED) for a session."""
    annotation = RecordingAnnotation(
        recording_id=recording.id,
        search_session_id=search_session.id,
        source=DetectionSource.PERCH_SEARCH,
        status=status,
        start_time=1.5,
        end_time=3.0,
    )
    db_session.add(annotation)
    await db_session.commit()
    await db_session.refresh(annotation)
    return annotation


async def _count_annotations_for_session(
    db_session: AsyncSession,
    search_session_id: object,
) -> int:
    result = await db_session.execute(
        select(func.count())
        .select_from(RecordingAnnotation)
        .where(RecordingAnnotation.search_session_id == search_session_id)
    )
    return int(result.scalar_one())


async def _make_query_embedding(
    db_session: AsyncSession,
    search_session: SearchSession,
    *,
    species_key: str = "abc",
    source_label: str = "stale reference",
) -> SearchQueryEmbedding:
    """Persist a SearchQueryEmbedding (reference-audio query vector) for a session."""
    embedding = SearchQueryEmbedding(
        search_session_id=search_session.id,
        species_key=species_key,
        source_label=source_label,
        # 1536-dim vector to match the column definition.
        vector=[0.0] * 1536,
    )
    db_session.add(embedding)
    await db_session.commit()
    await db_session.refresh(embedding)
    return embedding


async def _count_query_embeddings_for_session(
    db_session: AsyncSession,
    search_session_id: object,
) -> int:
    result = await db_session.execute(
        select(func.count())
        .select_from(SearchQueryEmbedding)
        .where(SearchQueryEmbedding.search_session_id == search_session_id)
    )
    return int(result.scalar_one())


async def test_reset_for_rerun_deletes_only_this_sessions_annotations(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> None:
    """reset_for_rerun deletes THIS session's review annotations and nothing else.

    Direct regression for bug #6. The original raw
    ``DELETE FROM annotations WHERE search_session_id = :sid`` raised
    ``UndefinedColumnError`` because the literal ``annotations`` table has no
    ``search_session_id`` column. The fix routes the delete through the ORM
    ``RecordingAnnotation`` model (table ``recording_annotations_DEFERRED``),
    which does carry that column.

    Non-vacuous: a ``RecordingAnnotation`` linked to the rerun session is seeded
    and asserted DELETED, while one linked to a *different* session is asserted
    to SURVIVE — proving both that the correct table is hit and that the delete
    is scoped to this session.
    """
    recording = await _make_recording(db_session, test_project)

    target_session = await _make_completed_session(
        db_session, test_project, test_user, name="Rerun Target"
    )
    other_session = await _make_completed_session(
        db_session, test_project, test_user, name="Rerun Other"
    )

    await _make_review_annotation(db_session, recording, target_session)
    await _make_review_annotation(db_session, recording, other_session)

    assert await _count_annotations_for_session(db_session, target_session.id) == 1
    assert await _count_annotations_for_session(db_session, other_session.id) == 1

    service = SearchSessionService(db_session)
    await service.reset_for_rerun(
        session=target_session,
        job_id="job-rerun",
        model_name="perch",
        parameters={"min_similarity": 0.2, "limit_per_species": 50, "dataset_id": None},
        species_config=[{"tag_id": "abc", "scientific_name": "Turdus merula"}],
        reference_audio_keys=None,
    )
    await db_session.commit()

    # The rerun session's review annotation is gone; the other session's is intact.
    assert await _count_annotations_for_session(db_session, target_session.id) == 0
    assert await _count_annotations_for_session(db_session, other_session.id) == 1


async def test_reset_for_rerun_deletes_only_this_sessions_query_embeddings(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> None:
    """reset_for_rerun clears THIS session's stored query embeddings, scoped.

    Data-integrity regression (Codex finding). The ``search_sessions`` row is
    reused across re-runs and the re-run task (``workers/search_tasks.py``) only
    *appends* fresh ``SearchQueryEmbedding`` rows on completion — it never deletes
    the old ones. Downstream readers load **every** embedding for a
    ``search_session_id`` (+ species_key): seed sampling in
    ``api/v1/custom_models.py`` and classifier training in
    ``workers/classifier_tasks.py``. Without clearing the stale vectors before a
    re-run, old + new reference vectors accumulate and get mixed into search and
    training inputs.

    Non-vacuous: stale embeddings are seeded for the rerun session and asserted
    DELETED, while an embedding linked to a *different* session is asserted to
    SURVIVE — proving the delete runs and is scoped to this session only. This
    test fails before the ``delete(SearchQueryEmbedding)`` is added to
    ``reset_for_rerun`` (the stale rows persist) and passes with it.
    """
    target_session = await _make_completed_session(
        db_session, test_project, test_user, name="Rerun Embed Target"
    )
    other_session = await _make_completed_session(
        db_session, test_project, test_user, name="Rerun Embed Other"
    )

    # Two stale query vectors on the rerun session, one on the other session.
    await _make_query_embedding(db_session, target_session, source_label="stale-1")
    await _make_query_embedding(db_session, target_session, source_label="stale-2")
    await _make_query_embedding(db_session, other_session, source_label="other-1")

    assert await _count_query_embeddings_for_session(db_session, target_session.id) == 2
    assert await _count_query_embeddings_for_session(db_session, other_session.id) == 1

    service = SearchSessionService(db_session)
    await service.reset_for_rerun(
        session=target_session,
        job_id="job-rerun-embed",
        model_name="perch",
        parameters={"min_similarity": 0.2, "limit_per_species": 50, "dataset_id": None},
        species_config=[{"tag_id": "abc", "scientific_name": "Turdus merula"}],
        reference_audio_keys=None,
    )
    await db_session.commit()

    # The rerun session's stale embeddings are gone; the other session's survives.
    assert await _count_query_embeddings_for_session(db_session, target_session.id) == 0
    assert await _count_query_embeddings_for_session(db_session, other_session.id) == 1


async def test_reset_for_rerun_resets_session_fields(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> None:
    """reset_for_rerun clears results/counters/error state and applies the new run."""
    session = await _make_completed_session(db_session, test_project, test_user)
    service = SearchSessionService(db_session)

    updated = await service.reset_for_rerun(
        session=session,
        job_id="job-rerun",
        model_name="perch",
        parameters={"min_similarity": 0.2, "limit_per_species": 50, "dataset_id": None},
        species_config=[{"tag_id": "abc", "scientific_name": "Turdus merula"}],
        reference_audio_keys=None,
    )
    await db_session.commit()

    assert updated.status == SearchSessionStatus.PENDING
    assert updated.results is None
    assert updated.result_count == 0
    assert updated.confirmed_count == 0
    assert updated.rejected_count == 0
    assert updated.error_message is None
    assert updated.started_at is None
    assert updated.completed_at is None
    assert updated.celery_job_id == "job-rerun"
    assert updated.model_name == "perch"
    assert updated.parameters == {
        "min_similarity": 0.2,
        "limit_per_species": 50,
        "dataset_id": None,
    }


async def test_view_completed_session_merges_review_status_from_orm(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> None:
    """get_session_results_with_review_status reads live status from the ORM table.

    Non-vacuous: a CONFIRMED ``RecordingAnnotation`` is seeded whose
    (recording_id, tag_id, start_time) key matches the stored match, and the
    merged view is asserted to surface ``review_status == "confirmed"`` plus the
    annotation id — proving the method really queries
    ``recording_annotations_DEFERRED`` rather than blindly returning
    ``"unreviewed"``.
    """
    recording = await _make_recording(db_session, test_project)
    session = await _make_completed_session(db_session, test_project, test_user)

    # Align the stored match's recording_id/start_time with the seeded annotation
    # so the (recording_id, tag_id, start_time) lookup key hits.
    results = _completed_results_jsonb("abc")
    species = results["results"]["abc"]  # type: ignore[index]
    species["tag_id"] = None  # match the annotation's NULL tag_id
    species["matches"][0]["recording_id"] = str(recording.id)
    species["matches"][0]["start_time"] = 1.5
    session.results = results
    await db_session.commit()
    await db_session.refresh(session)

    annotation = await _make_review_annotation(
        db_session, recording, session, status=DetectionStatus.CONFIRMED
    )

    service = SearchSessionService(db_session)
    merged = await service.get_session_results_with_review_status(
        session_id=session.id,
        project_id=test_project.id,
        session=session,
    )

    assert merged is not None
    inner = merged["results"]
    assert isinstance(inner, dict)
    match = inner["abc"]["matches"][0]  # type: ignore[index]
    assert match["review_status"] == "confirmed"
    assert match["annotation_id"] == str(annotation.id)


async def test_view_session_without_results_returns_none(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> None:
    """A reset (results=None) session yields None from the results view (no crash)."""
    session = await _make_completed_session(db_session, test_project, test_user)
    service = SearchSessionService(db_session)

    await service.reset_for_rerun(
        session=session,
        job_id="job-rerun",
        model_name="perch",
        parameters={"min_similarity": 0.2, "limit_per_species": 50, "dataset_id": None},
        species_config=[{"tag_id": "abc", "scientific_name": "Turdus merula"}],
        reference_audio_keys=None,
    )
    await db_session.commit()

    merged = await service.get_session_results_with_review_status(
        session_id=session.id,
        project_id=test_project.id,
        session=session,
    )
    assert merged is None


async def test_update_review_counts_aggregates_from_orm(
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
) -> None:
    """update_review_counts recomputes confirmed/rejected from the ORM table.

    Non-vacuous: two CONFIRMED and one REJECTED ``RecordingAnnotation`` rows are
    seeded for this session (plus an UNREVIEWED one that must NOT be counted),
    and the persisted counters are asserted to equal 2 / 1 — proving the method
    aggregates from ``recording_annotations_DEFERRED`` rather than forcing 0/0.
    """
    recording = await _make_recording(db_session, test_project)
    session = await _make_completed_session(db_session, test_project, test_user)

    await _make_review_annotation(
        db_session, recording, session, status=DetectionStatus.CONFIRMED
    )
    await _make_review_annotation(
        db_session, recording, session, status=DetectionStatus.CONFIRMED
    )
    await _make_review_annotation(
        db_session, recording, session, status=DetectionStatus.REJECTED
    )
    await _make_review_annotation(
        db_session, recording, session, status=DetectionStatus.UNREVIEWED
    )

    service = SearchSessionService(db_session)
    await service.update_review_counts(session.id)
    await db_session.commit()
    await db_session.refresh(session)

    assert session.confirmed_count == 2
    assert session.rejected_count == 1


# ---------------------------------------------------------------------------
# Active endpoint-level regression — the "why it shipped" gap
# ---------------------------------------------------------------------------
#
# ``test_search_writes.py`` already declares a ``PUT .../rerun → 202`` endpoint
# test, but that *whole file* is under a Phase-14 ``pytest.mark.skip`` (it was
# written against the rich-shape ``Annotation`` ORM that is deferred), so there
# was NO active test exercising the real rerun ENDPOINT — only direct service
# calls. The bug therefore reached production through the HTTP path untested.
# This class closes that gap by driving the live route end-to-end.


def _make_minimal_wav(num_frames: int = 100, sample_rate: int = 16000) -> bytes:
    """Build a minimal valid 1-channel 16-bit PCM WAV byte string (no deps)."""
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
        16,
        1,
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + b"\x00" * data_size


# Production hard-codes the reference-audio staging directory as
# ``/data/search_tmp/{job_id}`` (``echoroo.api.v1.search.batch._prepare_batch_job``
# does ``Path(f"/data/search_tmp/{job_id}").mkdir(...)`` and then writes the
# uploaded WAV + ``manifest.json`` into it). ``/data`` happens to be writable in
# the dev container, so the endpoint test passed locally — but on CI runners
# ``/data`` is read-only, so that ``mkdir`` raised
# ``PermissionError: [Errno 13] Permission denied: '/data'`` and the rerun
# endpoint 500'd before ``reset_for_rerun`` ever ran. This mirrors how the suite
# already redirects the S3 audio cache off ``/data`` (see ``tests/conftest.py``
# ``override_get_audio_service`` and the ``S3_AUDIO_CACHE_DIR`` setting comment):
# we point the staging directory at a pytest ``tmp_path`` so the test never
# depends on a writable ``/data``.
_SEARCH_TMP_PREFIX = "/data/search_tmp"


@pytest.fixture
def redirect_search_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Path:
    """Redirect the hard-coded ``/data/search_tmp`` staging dir to ``tmp_path``.

    ``_prepare_batch_job`` builds the staging path inline via the module-level
    ``Path`` symbol in ``echoroo.api.v1.search.batch``. Patching that symbol with
    a thin shim that rewrites any ``/data/search_tmp[...]`` path under ``tmp_path``
    (and passes every other path straight through) makes the reference-audio
    ``mkdir`` / ``write_bytes`` / ``manifest.json`` writes land in a writable
    location without touching production code. Proves the endpoint no longer
    needs a writable ``/data``.
    """
    staging_root = tmp_path / "search_tmp"

    def _redirected_path(*args: object) -> Path:
        if len(args) == 1 and isinstance(args[0], str):
            raw = args[0]
            if raw == _SEARCH_TMP_PREFIX or raw.startswith(_SEARCH_TMP_PREFIX + "/"):
                suffix = raw[len(_SEARCH_TMP_PREFIX) :].lstrip("/")
                return staging_root / suffix if suffix else staging_root
        return Path(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "echoroo.api.v1.search.batch.Path", _redirected_path, raising=True
    )
    return staging_root


@pytest.mark.asyncio
class TestRerunEndpointRegression:
    """Active end-to-end guard for ``PUT .../search/sessions/{id}/rerun``."""

    @staticmethod
    def _rerun_url(project_id: object, session_id: object) -> str:
        # W2-3 PR-18: the legacy ``PUT /api/v1/.../rerun`` route was unmounted;
        # the BFF adapter at ``/web-api/v1`` delegates to the same
        # ``rerun_search_session`` handler. Repointed for source correctness.
        return (
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}/rerun"
        )

    @patch("echoroo.workers.search_tasks.run_batch_search")
    @patch("echoroo.core.s3.get_s3_client")
    @patch("echoroo.api.v1.search.sessions.crud.delete_object")
    async def test_rerun_endpoint_succeeds_and_clears_stale_session_state(
        self,
        mock_delete_object: MagicMock,
        mock_get_s3_client: MagicMock,
        mock_run_batch_search: MagicMock,
        client: AsyncClient,
        csrf_headers: dict[str, str],
        db_session: AsyncSession,
        test_project: Project,
        test_user: User,
        redirect_search_tmp: Path,
    ) -> None:
        """The real rerun endpoint returns 202 (not 500) and clears stale rows.

        Drives the actual HTTP route the frontend uses (the BFF adapter at
        ``PUT /web-api/v1/.../rerun`` delegates to this same
        ``rerun_search_session`` handler). This is the regression that
        ``reset_for_rerun``'s original raw ``DELETE FROM annotations`` broke:
        the literal ``annotations`` table has no ``search_session_id`` column,
        so PostgreSQL raised ``UndefinedColumnError`` → the endpoint 500'd.

        Setup:
          * COMPLETED ``SearchSession`` with stored ``results`` and a seeded
            reference-audio key.
          * A stale ``recording_annotations_DEFERRED`` row for the session
            (the row the buggy DELETE tried — and failed — to remove).
          * A stale ``search_query_embeddings`` row for the session.

        The Celery dispatch (``run_batch_search.apply_async``) and the S3
        client are mocked so the test needs neither a worker nor LocalStack.

        Asserts (the key regression signals):
          * HTTP 202 — the endpoint succeeds end-to-end, i.e. NO 500 and NO
            ``UndefinedColumnError`` bubbled up from ``reset_for_rerun``.
          * ``apply_async`` was called exactly once (the re-run was dispatched).
          * the session flipped to PENDING.
          * the stale annotation + embedding rows for the session are gone.

        Non-vacuous: this test FAILS against the original broken code (the raw
        ``DELETE FROM annotations`` → 500, so the status is 500 not 202 and
        ``apply_async`` is never reached) and PASSES with the ORM-based delete.
        """
        mock_s3 = MagicMock()
        mock_get_s3_client.return_value = mock_s3

        recording = await _make_recording(db_session, test_project)
        session = await _make_completed_session(
            db_session, test_project, test_user, name="Rerun Endpoint Session"
        )
        # Seed a reference-audio key so the post-commit cleanup path runs.
        session.reference_audio_keys = [
            f"search_reference/{test_project.id}/old-job/source_0.wav"
        ]
        await db_session.commit()

        # Stale rows the rerun must clear (the exact shapes bug #6 corrupted).
        await _make_review_annotation(db_session, recording, session)
        await _make_query_embedding(db_session, session, source_label="stale")

        assert await _count_annotations_for_session(db_session, session.id) == 1
        assert await _count_query_embeddings_for_session(db_session, session.id) == 1

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

        resp = await client.put(
            self._rerun_url(test_project.id, session.id),
            headers=csrf_headers,
            data={"metadata": metadata},
            files={"source_0": ("source_0.wav", wav_bytes, "audio/wav")},
        )

        # The core regression assertion: the endpoint succeeds (202), it does
        # NOT 500 with an UndefinedColumnError from the broken raw DELETE.
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "pending"
        assert body["session_id"] == str(session.id)

        # The reference-audio staging landed in the redirected tmp dir, proving
        # the endpoint did NOT touch the real (CI: read-only) ``/data/search_tmp``.
        staged_jobs = (
            [p for p in redirect_search_tmp.iterdir() if p.is_dir()]
            if redirect_search_tmp.exists()
            else []
        )
        assert staged_jobs, (
            "expected the uploaded reference audio to be staged under the "
            f"redirected tmp dir {redirect_search_tmp}, but it was empty — the "
            "handler may still be writing to the real /data/search_tmp"
        )

        # The re-run was dispatched exactly once.
        mock_run_batch_search.apply_async.assert_called_once()

        # The session flipped to PENDING. Expire first so we read the route's
        # committed state from a fresh DB round-trip rather than the stale
        # identity-map copy.
        db_session.expire(session)
        await db_session.refresh(session)
        assert session.status == SearchSessionStatus.PENDING

        # The stale annotation + embedding rows for this session were cleared.
        assert await _count_annotations_for_session(db_session, session.id) == 0
        assert await _count_query_embeddings_for_session(db_session, session.id) == 0

    async def test_rerun_endpoint_unauthenticated_returns_401(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_project: Project,
        test_user: User,
    ) -> None:
        """Sanity guard: the rerun endpoint requires authentication (401)."""
        session = await _make_completed_session(
            db_session, test_project, test_user, name="Rerun Auth Session"
        )
        resp = await client.put(
            self._rerun_url(test_project.id, session.id),
            data={"metadata": "{}"},
        )
        assert resp.status_code == 401
