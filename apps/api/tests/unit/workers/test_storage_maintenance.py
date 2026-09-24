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


def _point_cache_at(monkeypatch, cache: Path) -> None:
    monkeypatch.setattr(
        storage_maintenance,
        "get_settings",
        lambda: SimpleNamespace(COMPRESSED_CACHE_DIR=str(cache), COMPRESSED_CACHE_MAX_AGE_DAYS=30),
    )


def _age(path: Path, days: float) -> None:
    then = time.time() - days * 24 * 60 * 60
    os.utime(path, (then, then))


def test_sweep_storage_temporaries_file_error_returns_zero(monkeypatch) -> None:
    def fail() -> int:
        raise PermissionError("denied")

    monkeypatch.setattr(storage_maintenance.storage, "sweep_temporaries", fail)

    assert storage_maintenance.sweep_storage_temporaries.run() == 0


def test_sweep_compressed_cache_rejects_a_root_that_is_not_a_directory(
    tmp_path: Path, monkeypatch
) -> None:
    root_file = tmp_path / "cache"
    root_file.write_bytes(b"not a directory")
    _point_cache_at(monkeypatch, root_file)
    assert storage_maintenance.sweep_compressed_cache.run() == 0

    target = tmp_path / "real-cache"
    target.mkdir()
    stale = target / "stale.ogg"
    stale.write_bytes(b"x")
    _age(stale, 60)
    link = tmp_path / "linked-cache"
    link.symlink_to(target, target_is_directory=True)
    _point_cache_at(monkeypatch, link)
    assert storage_maintenance.sweep_compressed_cache.run() == 0
    assert stale.exists()


def test_sweep_compressed_cache_root_lookup_error_returns_zero(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    _point_cache_at(monkeypatch, cache)
    real_lstat = Path.lstat

    def lstat(self: Path):  # type: ignore[no-untyped-def]
        if self == cache:
            raise PermissionError("denied")
        return real_lstat(self)

    monkeypatch.setattr(Path, "lstat", lstat)

    assert storage_maintenance.sweep_compressed_cache.run() == 0


def test_sweep_compressed_cache_skips_files_it_cannot_remove(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    locked = cache / "locked.ogg"
    vanished = cache / "vanished.ogg"
    removable = cache / "removable.ogg"
    for path in (locked, vanished, removable):
        path.write_bytes(b"x")
        _age(path, 60)
    _point_cache_at(monkeypatch, cache)
    real_unlink = Path.unlink

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if self == locked:
            raise PermissionError("denied")
        if self == vanished:
            raise FileNotFoundError(self)
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)

    assert storage_maintenance.sweep_compressed_cache.run() == 1
    assert locked.exists()
    assert not removable.exists()


def test_iter_regular_files_tolerates_scan_errors_and_special_files(
    tmp_path: Path, monkeypatch
) -> None:
    cache = tmp_path / "cache"
    unreadable = cache / "unreadable"
    vanished = cache / "vanished"
    unreadable.mkdir(parents=True)
    vanished.mkdir()
    kept = cache / "kept.ogg"
    kept.write_bytes(b"x")
    fifo = cache / "pipe"
    os.mkfifo(fifo)
    real_scandir = os.scandir
    real_lstat = Path.lstat

    def scandir(path):  # type: ignore[no-untyped-def]
        if Path(path) == unreadable:
            raise PermissionError("denied")
        if Path(path) == vanished:
            raise FileNotFoundError(path)
        return real_scandir(path)

    def lstat(self: Path):  # type: ignore[no-untyped-def]
        if self == cache / "gone":
            raise FileNotFoundError(self)
        if self == cache / "denied":
            raise PermissionError("denied")
        return real_lstat(self)

    monkeypatch.setattr(storage_maintenance.os, "scandir", scandir)
    monkeypatch.setattr(Path, "lstat", lstat)

    found = [path for path, _ in storage_maintenance._iter_regular_files(cache)]
    assert found == [kept]
    # Directories that vanish or cannot be inspected before scanning are skipped.
    assert list(storage_maintenance._iter_regular_files(cache / "gone")) == []
    assert list(storage_maintenance._iter_regular_files(cache / "denied")) == []


def test_iter_regular_files_skips_entries_that_fail_mid_scan(tmp_path: Path) -> None:
    class _Entry:
        def __init__(self, path: Path, error: OSError) -> None:
            self.path = str(path)
            self._error = error

        def is_symlink(self) -> bool:
            raise self._error

    class _Entries:
        def __init__(self, entries: list[_Entry]) -> None:
            self._entries = entries

        def __enter__(self) -> list[_Entry]:
            return self._entries

        def __exit__(self, *_args: object) -> None:
            return None

    cache = tmp_path / "cache"
    cache.mkdir()
    entries = [
        _Entry(cache / "vanished.ogg", FileNotFoundError("gone")),
        _Entry(cache / "denied.ogg", PermissionError("denied")),
    ]
    original = storage_maintenance.os.scandir
    storage_maintenance.os.scandir = lambda _path: _Entries(entries)  # type: ignore[assignment]
    try:
        assert list(storage_maintenance._iter_regular_files(cache)) == []
    finally:
        storage_maintenance.os.scandir = original  # type: ignore[assignment]
