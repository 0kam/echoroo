"""Tests for the storage and compressed-cache maintenance tasks."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

from echoroo.workers import storage_maintenance


def test_sweep_storage_temporaries_returns_storage_count(
    monkeypatch,
) -> None:
    monkeypatch.setattr(storage_maintenance.storage, "sweep_temporaries", lambda: 4)

    assert storage_maintenance.sweep_storage_temporaries.run() == 4


def test_sweep_compressed_cache_age_filters_temps_and_symlinks(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache"
    nested = cache / "nested"
    nested.mkdir(parents=True)
    outside = tmp_path / "outside.ogg"
    outside.write_bytes(b"outside")

    old = cache / "old.ogg"
    fresh = cache / "fresh.ogg"
    old_temp = nested / ".echoroo-tmp-encoder"
    fresh_temp = nested / ".echoroo-tmp-fresh"
    for path in (old, fresh, old_temp, fresh_temp):
        path.write_bytes(b"cache")

    now = time.time()
    os.utime(old, (now - 31 * 24 * 60 * 60, now - 31 * 24 * 60 * 60))
    os.utime(fresh, (now - 2 * 24 * 60 * 60, now - 2 * 24 * 60 * 60))
    os.utime(old_temp, (now - 2 * 24 * 60 * 60, now - 2 * 24 * 60 * 60))
    os.utime(fresh_temp, (now - 12 * 60 * 60, now - 12 * 60 * 60))

    symlinked_file = cache / "symlink.ogg"
    symlinked_file.symlink_to(outside)
    symlinked_dir = cache / "symlinked-dir"
    symlinked_dir.symlink_to(tmp_path / "missing-dir", target_is_directory=True)
    monkeypatch.setattr(
        storage_maintenance,
        "get_settings",
        lambda: SimpleNamespace(
            COMPRESSED_CACHE_DIR=str(cache), COMPRESSED_CACHE_MAX_AGE_DAYS=30
        ),
    )

    assert storage_maintenance.sweep_compressed_cache.run() == 2
    assert not old.exists()
    assert not old_temp.exists()
    assert fresh.exists()
    assert fresh_temp.exists()
    assert symlinked_file.is_symlink()
    assert symlinked_dir.is_symlink()
    assert outside.exists()


def test_sweep_compressed_cache_missing_directory_is_not_an_error(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        storage_maintenance,
        "get_settings",
        lambda: SimpleNamespace(
            COMPRESSED_CACHE_DIR=str(tmp_path / "missing"),
            COMPRESSED_CACHE_MAX_AGE_DAYS=30,
        ),
    )

    assert storage_maintenance.sweep_compressed_cache.run() == 0
