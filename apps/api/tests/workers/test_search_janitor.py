"""Unit tests for the S3 orphan janitor for search_reference/ prefix.

Tests cover:
  T1  dry-run blocks deletion
  T2  age filter excludes recent objects
  T3  DB-referenced key is preserved
  T4  Case A prefix bulk delete (no session for job)
  T5  Case B individual delete (mixed-state prefix)
  T6  legacy non-UUID job_id tolerated
  T7  invalid project_id skipped
  T8  partial batch failure logged
  T9  _extract_species_config_s3_keys handles malformed inputs

All tests use in-memory fake S3 client; no real LocalStack connection is made.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.s3 import BatchDeleteResult, S3DeletionError, S3ObjectMeta
from echoroo.models.enums import SearchSessionStatus
from echoroo.models.project import Project
from echoroo.models.search_session import SearchSession
from echoroo.models.user import User
from echoroo.workers.search_tasks import (
    _collect_db_reference_state,
    _extract_species_config_s3_keys,
    _run_orphan_search_reference_cleanup,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)
_FRESH = _NOW - timedelta(hours=23)   # within 24h cutoff — should NOT be aged
_STALE = _NOW - timedelta(hours=25)   # beyond 24h cutoff — should be aged


def _make_meta(key: str, age: datetime = _STALE, size: int = 100) -> S3ObjectMeta:
    """Build an S3ObjectMeta with the given key and last_modified time."""
    return S3ObjectMeta(key=key, last_modified=age, size=size)


class FakeS3Client:
    """In-memory S3 client that supports list_objects_v2 / delete_objects / delete_object.

    The store maps key -> {"LastModified": datetime, "Size": int}.
    """

    def __init__(self, objects: dict[str, dict[str, Any]] | None = None) -> None:
        self._store: dict[str, dict[str, Any]] = objects or {}
        # Track calls for assertions
        self.delete_objects_calls: list[dict[str, Any]] = []
        self.delete_object_calls: list[str] = []

    def put(self, key: str, last_modified: datetime, size: int = 100) -> None:
        """Insert an object into the fake store."""
        self._store[key] = {"LastModified": last_modified, "Size": size}

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        """Simulate list_objects_v2 with prefix filtering (no pagination)."""
        prefix: str = kwargs.get("Prefix", "")
        contents = [
            {"Key": k, "LastModified": v["LastModified"], "Size": v["Size"]}
            for k, v in self._store.items()
            if k.startswith(prefix)
        ]
        return {
            "Contents": contents,
            "IsTruncated": False,
        }

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        """Simulate s3:DeleteObjects and record the call."""
        self.delete_objects_calls.append(kwargs)
        keys = [obj["Key"] for obj in kwargs["Delete"]["Objects"]]
        deleted = []
        for k in keys:
            if k in self._store:
                del self._store[k]
                deleted.append({"Key": k})
        return {"Deleted": deleted, "Errors": []}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        """Simulate s3:DeleteObject and record the call."""
        key = kwargs.get("Key", "")
        self.delete_object_calls.append(key)
        self._store.pop(key, None)
        return {}

    def get_paginator(self, operation: str) -> FakePaginator:
        """Return a FakePaginator bound to this client."""
        return FakePaginator(self, operation)


class FakePaginator:
    """Minimal paginator for delete_objects_by_prefix."""

    def __init__(self, client: FakeS3Client, operation: str) -> None:
        self._client = client
        self._operation = operation

    def paginate(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Yield one page of results matching the given prefix."""
        prefix = kwargs.get("Prefix", "")
        keys = [k for k in self._client._store if k.startswith(prefix)]
        if not keys:
            return [{"Contents": [], "IsTruncated": False}]
        return [
            {
                "Contents": [{"Key": k} for k in keys],
                "IsTruncated": False,
            }
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Minimal test user for project ownership."""
    user = User(
        email="janitor_test@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Janitor Test User",
        security_stamp="janitor-stamp",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_project(db_session: AsyncSession, test_user: User) -> Project:
    """Minimal test project.

    Phase 11 schema constraints: ``ProjectVisibility.PRIVATE`` was removed
    in favour of ``RESTRICTED``; ``license`` is NOT NULL; ``target_taxa``
    column was removed; ``restricted_config`` must satisfy
    ``ck_projects_restricted_config_shape`` whenever
    ``visibility='restricted'``.
    """
    from echoroo.models.enums import (
        ProjectVisibility,
    )

    project = Project(
        name="Janitor Test Project",
        description="For janitor tests",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=test_user.id,
        restricted_config={
            "allow_media_playback": False,
            "allow_detection_view": False,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 3,
            "allow_precise_location_to_viewer": False,
        },
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def make_search_session(
    db: AsyncSession,
    project_id: UUID,
    celery_job_id: str | None = None,
    reference_audio_keys: list[str] | None = None,
    species_config: list[Any] | None = None,
) -> SearchSession:
    """Insert a SearchSession row and return it."""
    session = SearchSession(
        project_id=project_id,
        model_name="perch",
        status=SearchSessionStatus.COMPLETED,
        celery_job_id=celery_job_id,
        reference_audio_keys=reference_audio_keys,
        species_config=species_config,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ---------------------------------------------------------------------------
# Helper: build a fake get_worker_engine_and_session_factory
# ---------------------------------------------------------------------------

def _make_fake_engine_factory(
    known_keys: set[str],
    known_prefixes: set[tuple[UUID, str]],
) -> Any:
    """Return a mock get_worker_engine_and_session_factory that patches the DB step.

    The janitor calls:
        engine, session_factory = get_worker_engine_and_session_factory()
        async with session_factory() as db:
            known_keys, known_job_prefixes = await _collect_db_reference_state(db)
        await engine.dispose()

    We fake:
      - engine: AsyncMock with a no-op dispose()
      - session_factory(): async context manager yielding a dummy db session
        The real _collect_db_reference_state is NOT called because we also
        patch it separately with the pre-computed sets.
    """
    fake_engine = AsyncMock()
    fake_engine.dispose = AsyncMock()

    fake_db = MagicMock()

    @asynccontextmanager
    async def _fake_session_cm() -> Any:
        yield fake_db

    fake_session_factory = MagicMock(return_value=_fake_session_cm())

    def _factory() -> tuple[Any, Any]:
        return fake_engine, fake_session_factory

    return _factory


# ---------------------------------------------------------------------------
# T1 — dry-run blocks deletion
# ---------------------------------------------------------------------------


async def test_dry_run_blocks_deletion(
    db_session: AsyncSession,
    test_project: Project,
) -> None:
    """dry_run=True: objects are enumerated but delete_objects is never called."""
    fake_s3 = FakeS3Client()
    pid = test_project.id
    job_id = str(uuid4())
    orphan_key = f"search_reference/{pid}/{job_id}/source_0.wav"
    fake_s3.put(orphan_key, _STALE)

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = True
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(set(), set())

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(set(), set()),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["dry_run"] is True
    assert result["deleted"] == 0
    assert result["failed"] == 0
    # At least one orphan was detected
    assert result["individual_keys"] >= 1 or result["prefix_groups"] >= 1
    # delete_objects must never have been called
    assert fake_s3.delete_objects_calls == []
    assert fake_s3.delete_object_calls == []


# ---------------------------------------------------------------------------
# T2 — age filter
# ---------------------------------------------------------------------------


async def test_age_filter_excludes_recent(
    db_session: AsyncSession,
    test_project: Project,
) -> None:
    """Only objects older than cutoff are deleted; recent objects survive.

    Use distinct job prefixes so the fresh key is never touched by a
    prefix-level bulk delete that targets the stale key's prefix.
    """
    fake_s3 = FakeS3Client()
    pid = test_project.id
    job_id_recent = str(uuid4())
    job_id_stale = str(uuid4())

    key_recent = f"search_reference/{pid}/{job_id_recent}/recent.wav"
    key_stale = f"search_reference/{pid}/{job_id_stale}/stale.wav"
    fake_s3.put(key_recent, _FRESH)
    fake_s3.put(key_stale, _STALE)

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(set(), set())

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(set(), set()),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["dry_run"] is False
    # stale key deleted, recent key still in store
    assert key_recent in fake_s3._store
    assert key_stale not in fake_s3._store
    assert result["deleted"] >= 1


# ---------------------------------------------------------------------------
# T3 — DB referenced key preserved
# ---------------------------------------------------------------------------


async def test_db_referenced_key_preserved(
    db_session: AsyncSession,
    test_project: Project,
) -> None:
    """Keys referenced in DB (reference_audio_keys / species_config) are not deleted."""
    fake_s3 = FakeS3Client()
    pid = test_project.id
    job_id = str(uuid4())
    ref_key = f"search_reference/{pid}/{job_id}/source_0.wav"
    fake_s3.put(ref_key, _STALE)

    # Insert a SearchSession that references the key both via reference_audio_keys
    # and via species_config so both code-paths are exercised.
    await make_search_session(
        db_session,
        project_id=pid,
        celery_job_id=job_id,
        reference_audio_keys=[ref_key],
        species_config=[
            {"sources": [{"s3_key": ref_key}]}
        ],
    )

    known_keys, known_prefixes = await _collect_db_reference_state(db_session)

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(known_keys, known_prefixes)

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(known_keys, known_prefixes),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["deleted"] == 0
    # The key must still exist in fake S3
    assert ref_key in fake_s3._store


# ---------------------------------------------------------------------------
# T4 — Case A prefix bulk delete
# ---------------------------------------------------------------------------


async def test_case_a_prefix_bulk_delete(
    db_session: AsyncSession,
    test_project: Project,
) -> None:
    """No DB session for this job → entire prefix deleted in one batch."""
    fake_s3 = FakeS3Client()
    pid = test_project.id
    new_job_id = str(uuid4())
    keys = [
        f"search_reference/{pid}/{new_job_id}/source_{i}.wav"
        for i in range(3)
    ]
    for k in keys:
        fake_s3.put(k, _STALE)

    # No SearchSession inserted → known_prefixes is empty

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(set(), set())

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(set(), set()),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["dry_run"] is False
    assert result["prefix_groups"] == 1
    assert result["individual_keys"] == 0
    assert result["deleted"] == 3
    assert result["failed"] == 0
    # All 3 keys removed from fake store
    for k in keys:
        assert k not in fake_s3._store


# ---------------------------------------------------------------------------
# T5 — Case B/C individual delete
# ---------------------------------------------------------------------------


async def test_case_b_individual_delete(
    db_session: AsyncSession,
    test_project: Project,
) -> None:
    """Mixed prefix: referenced key survives, unreferenced key is deleted individually."""
    fake_s3 = FakeS3Client()
    pid = test_project.id
    job_id = str(uuid4())

    key_ref = f"search_reference/{pid}/{job_id}/source_0.wav"
    key_orphan = f"search_reference/{pid}/{job_id}/source_1.wav"
    fake_s3.put(key_ref, _STALE)
    fake_s3.put(key_orphan, _STALE)

    # Insert session to record job_id — but reference_audio_keys only lists key_ref
    await make_search_session(
        db_session,
        project_id=pid,
        celery_job_id=job_id,
        reference_audio_keys=[key_ref],
    )

    known_keys, known_prefixes = await _collect_db_reference_state(db_session)

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(known_keys, known_prefixes)

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(known_keys, known_prefixes),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["dry_run"] is False
    assert result["prefix_groups"] == 0
    assert result["individual_keys"] == 1
    assert result["deleted"] == 1
    assert result["failed"] == 0
    # Referenced key untouched, orphan removed
    assert key_ref in fake_s3._store
    assert key_orphan not in fake_s3._store


# ---------------------------------------------------------------------------
# T6 — legacy non-UUID job_id tolerated
# ---------------------------------------------------------------------------


async def test_legacy_non_uuid_job_id_tolerated(
    db_session: AsyncSession,
    test_project: Project,
) -> None:
    """Non-UUID job_id is accepted; key is treated as orphan and deleted."""
    fake_s3 = FakeS3Client()
    pid = test_project.id
    legacy_key = f"search_reference/{pid}/old-job/source_0.wav"
    fake_s3.put(legacy_key, _STALE)

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(set(), set())

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(set(), set()),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["deleted"] == 1
    assert legacy_key not in fake_s3._store


# ---------------------------------------------------------------------------
# T7 — invalid project_id skipped
# ---------------------------------------------------------------------------


async def test_invalid_project_id_skipped(
    db_session: AsyncSession,
) -> None:
    """Keys with non-UUID project_id segment are silently skipped (not deleted)."""
    fake_s3 = FakeS3Client()
    bad_key = "search_reference/not-a-uuid/some-job/file.wav"
    fake_s3.put(bad_key, _STALE)

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(set(), set())

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(set(), set()),
        ),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["individual_keys"] == 0
    assert result["prefix_groups"] == 0
    assert result["deleted"] == 0
    # Bad key still in store
    assert bad_key in fake_s3._store


# ---------------------------------------------------------------------------
# T8 — partial failure logged
# ---------------------------------------------------------------------------


async def test_partial_failure_logged(
    db_session: AsyncSession,
    test_project: Project,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Partial s3:DeleteObjects failure is logged and counted in failed."""
    fake_s3 = FakeS3Client()
    pid = test_project.id
    job_id = str(uuid4())

    key_ok = f"search_reference/{pid}/{job_id}/ok.wav"
    key_fail = f"search_reference/{pid}/{job_id}/fail.wav"
    fake_s3.put(key_ok, _STALE)
    fake_s3.put(key_fail, _STALE)

    # Insert session so that job_id is in known_prefixes → forces individual path
    ref_key_other = f"search_reference/{pid}/{job_id}/other.wav"
    await make_search_session(
        db_session,
        project_id=pid,
        celery_job_id=job_id,
        reference_audio_keys=[ref_key_other],
    )
    known_keys, known_prefixes = await _collect_db_reference_state(db_session)

    # Mock delete_objects_batch to simulate partial failure
    mock_batch_result = BatchDeleteResult(
        deleted=[key_ok],
        errors=[S3DeletionError(key=key_fail, code="AccessDenied", message="Access Denied")],
    )

    settings_stub = MagicMock()
    settings_stub.JANITOR_DRY_RUN = False
    settings_stub.JANITOR_AGE_HOURS = 24
    settings_stub.S3_BUCKET = "echoroo"

    fake_factory = _make_fake_engine_factory(known_keys, known_prefixes)

    with (
        patch("echoroo.core.s3.get_s3_client", return_value=fake_s3),
        patch("echoroo.workers.search_tasks.get_settings", return_value=settings_stub),
        patch("echoroo.core.s3.get_settings", return_value=settings_stub),
        patch(
            "echoroo.workers.search_tasks.get_worker_engine_and_session_factory",
            side_effect=fake_factory,
        ),
        patch(
            "echoroo.workers.search_tasks._collect_db_reference_state",
            return_value=(known_keys, known_prefixes),
        ),
        patch(
            "echoroo.workers.search_tasks.delete_objects_batch",
            return_value=mock_batch_result,
        ),
        caplog.at_level(logging.WARNING, logger="echoroo.workers.search_tasks"),
    ):
        result = await _run_orphan_search_reference_cleanup()

    assert result["deleted"] == 1
    assert result["failed"] == 1
    # Warning log must mention "partial batch deletion failure" and the failing key
    warning_text = " ".join(caplog.messages)
    assert "partial batch deletion failure" in warning_text
    assert key_fail in warning_text


# ---------------------------------------------------------------------------
# T9 — _extract_species_config_s3_keys malformed inputs
# ---------------------------------------------------------------------------


def test_extract_species_config_malformed() -> None:
    """_extract_species_config_s3_keys handles every malformed shape gracefully."""
    fn = _extract_species_config_s3_keys

    # None
    assert fn(None) == []
    # Non-list scalar
    assert fn("not a list") == []
    # Empty list
    assert fn([]) == []
    # List with empty dict (no 'sources')
    assert fn([{}]) == []
    # sources is not a list
    assert fn([{"sources": "not a list"}]) == []
    # sources is a list but entry is empty dict (no 's3_key')
    assert fn([{"sources": [{}]}]) == []
    # s3_key is int (not str)
    assert fn([{"sources": [{"s3_key": 123}]}]) == []
    # s3_key is empty string
    assert fn([{"sources": [{"s3_key": ""}]}]) == []
    # Valid s3_key
    assert fn([{"sources": [{"s3_key": "search_reference/a/b/c.wav"}]}]) == [
        "search_reference/a/b/c.wav"
    ]
    # Multiple species, mixed valid/invalid
    assert fn(
        [
            {"sources": [{"s3_key": "search_reference/x/y/z.wav"}, {"s3_key": ""}]},
            {"sources": [{"s3_key": 42}]},
            {},
        ]
    ) == ["search_reference/x/y/z.wav"]
