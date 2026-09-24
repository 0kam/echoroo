"""Tests for the storage-backed search-reference janitor."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from echoroo.core import storage
from echoroo.core.storage import BatchDeleteResult, StorageDeletionError
from echoroo.workers import search_tasks

pytestmark = pytest.mark.asyncio

_STALE = datetime.now(UTC) - timedelta(hours=25)
_FRESH = datetime.now(UTC) - timedelta(hours=23)


def _key(project_id: str, job_id: str, name: str) -> str:
    return f"search_reference/{project_id}/{job_id}/{name}"


def _write_with_mtime(root: Path, key: str, modified: datetime) -> None:
    storage.write_bytes(key, b"audio")
    path = root / key
    timestamp = modified.timestamp()
    os.utime(path, (timestamp, timestamp))


def _patch_janitor_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dry_run: bool = False,
    known_keys: set[str] | None = None,
    known_prefixes: set[tuple[object, str]] | None = None,
) -> None:
    settings = SimpleNamespace(JANITOR_DRY_RUN=dry_run, JANITOR_AGE_HOURS=24)
    monkeypatch.setattr(search_tasks, "get_settings", lambda: settings)

    async def _collect(_db: object):
        return known_keys or set(), known_prefixes or set()

    monkeypatch.setattr(
        search_tasks,
        "_collect_db_reference_state",
        _collect,
    )

    class _Engine:
        async def dispose(self) -> None:
            return None

    @asynccontextmanager
    async def _session_factory() -> object:
        yield object()

    monkeypatch.setattr(
        search_tasks,
        "get_worker_engine_and_session_factory",
        lambda: (_Engine(), _session_factory),
    )


async def test_dry_run_does_not_delete(storage_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_id = str(uuid4())
    key = _key(project_id, str(uuid4()), "source.wav")
    _write_with_mtime(storage_root, key, _STALE)
    _patch_janitor_environment(monkeypatch, dry_run=True)

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result == {
        "dry_run": True,
        "total_scanned": 1,
        "prefix_groups": 1,
        "prefix_keys": 1,
        "individual_keys": 0,
        "deleted": 0,
        "failed": 0,
    }
    assert (storage_root / key).exists()


async def test_mixed_age_siblings_only_delete_aged_keys(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = str(uuid4())
    job_id = str(uuid4())
    old_key = _key(project_id, job_id, "old.wav")
    young_key = _key(project_id, job_id, "young.wav")
    _write_with_mtime(storage_root, old_key, _STALE)
    _write_with_mtime(storage_root, young_key, _FRESH)
    _patch_janitor_environment(monkeypatch)

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["prefix_groups"] == 1
    assert result["prefix_keys"] == 1
    assert result["deleted"] == 1
    assert not (storage_root / old_key).exists()
    assert (storage_root / young_key).exists()


async def test_key_added_after_listing_survives(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = str(uuid4())
    job_id = str(uuid4())
    listed_key = _key(project_id, job_id, "listed.wav")
    added_key = _key(project_id, job_id, "added-after-list.wav")
    _write_with_mtime(storage_root, listed_key, _STALE)
    _patch_janitor_environment(monkeypatch)

    listed_objects = list(storage.list_prefix("search_reference/"))

    def _listed_after_publish(_prefix: str):
        storage.write_bytes(added_key, b"new")
        return iter(listed_objects)

    monkeypatch.setattr(search_tasks.storage, "list_prefix", _listed_after_publish)

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["deleted"] == 1
    assert not (storage_root / listed_key).exists()
    assert (storage_root / added_key).exists()


async def test_recent_objects_are_not_aged(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key(str(uuid4()), str(uuid4()), "recent.wav")
    _write_with_mtime(storage_root, key, _FRESH)
    _patch_janitor_environment(monkeypatch)

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["total_scanned"] == 1
    assert result["prefix_groups"] == 0
    assert result["individual_keys"] == 0
    assert result["deleted"] == 0
    assert (storage_root / key).exists()


async def test_db_referenced_key_is_preserved(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = uuid4()
    job_id = str(uuid4())
    key = _key(str(project_id), job_id, "source.wav")
    _write_with_mtime(storage_root, key, _STALE)
    _patch_janitor_environment(
        monkeypatch,
        known_keys={key},
        known_prefixes={(project_id, job_id)},
    )

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["deleted"] == 0
    assert (storage_root / key).exists()


async def test_individual_delete_for_mixed_references(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = uuid4()
    job_id = str(uuid4())
    referenced = _key(str(project_id), job_id, "referenced.wav")
    orphan = _key(str(project_id), job_id, "orphan.wav")
    _write_with_mtime(storage_root, referenced, _STALE)
    _write_with_mtime(storage_root, orphan, _STALE)
    _patch_janitor_environment(
        monkeypatch,
        known_keys={referenced},
        known_prefixes={(project_id, job_id)},
    )

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["prefix_groups"] == 0
    assert result["individual_keys"] == 1
    assert result["deleted"] == 1
    assert (storage_root / referenced).exists()
    assert not (storage_root / orphan).exists()


async def test_invalid_project_id_is_skipped(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = "search_reference/not-a-uuid/job/source.wav"
    _write_with_mtime(storage_root, key, _STALE)
    _patch_janitor_environment(monkeypatch)

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["deleted"] == 0
    assert result["prefix_groups"] == 0
    assert result["individual_keys"] == 0
    assert (storage_root / key).exists()


async def test_delete_many_errors_are_counted(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = _key(str(uuid4()), str(uuid4()), "source.wav")
    _write_with_mtime(storage_root, key, _STALE)
    _patch_janitor_environment(monkeypatch)
    monkeypatch.setattr(
        search_tasks.storage,
        "delete_many",
        lambda keys: BatchDeleteResult(
            deleted=[],
            errors=[StorageDeletionError(keys[0], "AccessDenied", "denied")],
        ),
    )

    result = await search_tasks._run_orphan_search_reference_cleanup()

    assert result["deleted"] == 0
    assert result["failed"] == 1
    assert (storage_root / key).exists()


def test_extract_species_config_malformed() -> None:
    fn = search_tasks._extract_species_config_s3_keys

    assert fn(None) == []
    assert fn("not a list") == []
    assert fn([{}]) == []
    assert fn([{"sources": "not a list"}]) == []
    assert fn([{"sources": [{"s3_key": 123}]}]) == []
    assert fn([{"sources": [{"s3_key": ""}]}]) == []
    assert fn([{"sources": [{"s3_key": "search_reference/a/b/c.wav"}]}]) == [
        "search_reference/a/b/c.wav"
    ]
