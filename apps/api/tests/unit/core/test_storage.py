"""Contract tests for the unused POSIX storage API."""

from __future__ import annotations

import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from echoroo.core import storage


@pytest.fixture
def storage_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "storage"
    root.mkdir()
    (root / ".echoroo-storage").touch()
    settings = SimpleNamespace(STORAGE_ROOT=str(root))
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    return root


@pytest.mark.parametrize(
    "key",
    ["", "/absolute", "trailing/", "a//b", "../a", "a/../b", ".", "a/./b", "a\\b", "a\x00b", ".hidden"],
)
def test_path_for_rejects_invalid_keys(storage_root: Path, key: str) -> None:
    with pytest.raises(storage.StorageKeyError):
        storage.path_for(key)


def test_path_for_accepts_nested_key(storage_root: Path) -> None:
    assert storage.path_for("recordings/one.wav") == storage_root / "recordings/one.wav"


def test_path_for_rejects_existing_symlink_component(storage_root: Path) -> None:
    (storage_root / "outside").mkdir()
    (storage_root / "linked").symlink_to(storage_root / "outside", target_is_directory=True)

    with pytest.raises(storage.StorageKeyError):
        storage.path_for("linked/file.wav")


def test_marker_is_required(storage_root: Path) -> None:
    (storage_root / ".echoroo-storage").unlink()

    with pytest.raises(storage.StorageUnavailable, match="marker"):
        storage.ensure_ready()


def test_full_probe_passes_and_cleans_up(storage_root: Path) -> None:
    storage.ensure_ready(full=True)

    assert list((storage_root / ".echoroo-probe").iterdir()) == []


def test_full_probe_rejects_hard_link_failure(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("hard links unavailable")

    monkeypatch.setattr(storage.os, "link", fail_link)

    with pytest.raises(storage.StorageUnavailable, match="full probe"):
        storage.ensure_ready(full=True)


def test_write_replace_and_exclusive(storage_root: Path) -> None:
    assert storage.write_bytes("nested/value", b"first") == 5
    assert (storage_root / "nested/value").read_bytes() == b"first"
    assert storage.write_bytes("nested/value", b"second") == 6
    assert (storage_root / "nested/value").read_bytes() == b"second"

    with pytest.raises(FileExistsError):
        storage.write_bytes("nested/value", b"third", exclusive=True)
    assert (storage_root / "nested/value").read_bytes() == b"second"


def test_write_cleans_temporary_after_success_and_error(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.write_bytes("success", b"ok")

    def fail_fsync(_descriptor: int) -> None:
        raise OSError("fsync failed")

    monkeypatch.setattr(storage.os, "fsync", fail_fsync)
    with pytest.raises(OSError, match="fsync failed"):
        storage.write_bytes("failure", b"not published")

    assert not any(storage.is_temporary(path.name) for path in storage_root.rglob("*"))


def test_published_file_mode_is_0640(storage_root: Path) -> None:
    storage.write_bytes("mode/file", b"data")

    assert stat.S_IMODE((storage_root / "mode/file").stat().st_mode) == 0o640
    assert stat.S_IMODE((storage_root / "mode").stat().st_mode) == 0o750


def test_write_file_copies_source_in_chunks(storage_root: Path) -> None:
    source = storage_root.parent / "input.bin"
    source.write_bytes(b"source data")

    assert storage.write_file(source, "copied/input.bin") == len(b"source data")
    assert source.read_bytes() == b"source data"
    assert (storage_root / "copied/input.bin").read_bytes() == b"source data"


def test_copy_has_fresh_mtime_and_keeps_source(storage_root: Path) -> None:
    storage.write_bytes("source", b"source")
    storage.write_bytes("destination", b"old")
    old_mtime = (storage_root / "destination").stat().st_mtime_ns
    time.sleep(0.01)

    assert storage.copy("source", "destination") == len(b"source")
    assert (storage_root / "source").read_bytes() == b"source"
    assert (storage_root / "destination").read_bytes() == b"source"
    assert (storage_root / "destination").stat().st_mtime_ns > old_mtime


def test_reader_handle_survives_replace(storage_root: Path) -> None:
    storage.write_bytes("reader", b"old")
    reader = storage.read_range("reader", None)
    storage.write_bytes("reader", b"new")

    assert b"".join(reader.stream) == b"old"


def test_exists_and_size_distinguish_absent_key_and_missing_root(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert storage.exists("absent") is False
    assert storage.size("absent") is None
    settings = storage.get_settings()
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(storage_root / "gone"))

    with pytest.raises(storage.StorageUnavailable):
        storage.exists("absent")
    with pytest.raises(storage.StorageUnavailable):
        storage.size("absent")


def test_delete_missing_and_directory(storage_root: Path) -> None:
    assert storage.delete("missing") is True
    (storage_root / "directory").mkdir()

    assert storage.delete("directory") is False
    assert (storage_root / "directory").is_dir()


def test_list_and_delete_prefix_use_string_prefixes_and_skip_temps(
    storage_root: Path,
) -> None:
    storage.write_bytes("foo/bar/one", b"1")
    storage.write_bytes("foo/barley", b"2")
    storage.write_bytes("foo/baz", b"3")
    storage.write_bytes("foobar", b"4")
    temporary = storage_root / "foo" / ".bar.tmp-0123456789abcdef0123456789abcdef"
    temporary.write_bytes(b"temporary")

    assert sorted(item.key for item in storage.list_prefix("foo/bar")) == [
        "foo/bar/one",
        "foo/barley",
    ]
    assert sorted(item.key for item in storage.list_prefix("foo/")) == [
        "foo/bar/one",
        "foo/barley",
        "foo/baz",
    ]
    assert all(item.modified.tzinfo is not None for item in storage.list_prefix("foo"))
    assert storage.delete_prefix("foo/bar") == 2
    assert storage.exists("foo/baz")
    assert storage.exists("foobar")
    assert storage.delete_prefix("foo/") == 1
    assert temporary.exists()

    with pytest.raises(storage.StorageKeyError):
        storage.delete_prefix("")


def test_delete_many_returns_deleted_and_error_records(storage_root: Path) -> None:
    storage.write_bytes("present", b"value")

    result = storage.delete_many(["present", "missing", ""])

    assert result.deleted == ["present", "missing"]
    assert len(result.errors) == 1
    assert result.errors[0] == storage.StorageDeletionError(
        "", "InvalidKey", "storage key must not be empty"
    )


@pytest.mark.parametrize(
    ("header", "expected", "partial"),
    [
        (None, (0, 25), False),
        ("not-a-range", (0, 25), False),
        ("bytes=0-3,5-7", (0, 25), False),
        ("bytes=2-5", (2, 5), True),
        ("bytes=2-999", (2, 25), True),
        ("bytes=2-", (2, 25), True),
        ("bytes=-4", (22, 25), True),
        ("bytes=-999", (0, 25), True),
        ("bytes=8-4", (0, 25), False),
    ],
)
def test_read_range_contract(
    storage_root: Path,
    header: str | None,
    expected: tuple[int, int],
    partial: bool,
) -> None:
    data = bytes(range(26))
    storage.write_bytes("range", data)

    result = storage.read_range("range", header)
    assert (result.start, result.end, result.total, result.partial) == (
        expected[0],
        expected[1],
        26,
        partial,
    )
    assert b"".join(result.stream) == data[expected[0] : expected[1] + 1]


def test_read_range_416_cases(storage_root: Path) -> None:
    storage.write_bytes("range", b"012345")
    with pytest.raises(storage.RangeNotSatisfiable) as out_of_bounds:
        storage.read_range("range", "bytes=6-")
    assert out_of_bounds.value.total == 6

    storage.write_bytes("empty", b"")
    with pytest.raises(storage.RangeNotSatisfiable) as empty:
        storage.read_range("empty", "bytes=0-0")
    assert empty.value.total == 0


def test_read_range_chunk_bound_and_early_close(storage_root: Path) -> None:
    data = bytes(index % 251 for index in range(200 * 1024))
    storage.write_bytes("large", data)

    result = storage.read_range("large", "bytes=1000-70000")
    chunks = list(result.stream)
    assert max(map(len, chunks)) <= 64 * 1024
    assert b"".join(chunks) == data[1000 : 70000 + 1]

    early = storage.read_range("large", "bytes=0-100")
    early.close()
    assert early.stream._closed is True  # noqa: SLF001 — contract checks early close


def test_sweep_temporaries_respects_age(storage_root: Path) -> None:
    old = storage_root / ".old.tmp-0123456789abcdef0123456789abcdef"
    fresh = storage_root / ".fresh.tmp-abcdef0123456789abcdef0123456789"
    nested = storage_root / "nested"
    nested.mkdir()
    old_nested = nested / ".old.tmp-11111111111111111111111111111111"
    for path in (old, fresh, old_nested):
        path.write_bytes(b"temporary")
    old_time = time.time() - 3600
    os.utime(old, (old_time, old_time))
    os.utime(old_nested, (old_time, old_time))

    assert storage.sweep_temporaries(timedelta(minutes=30)) == 2
    assert not old.exists()
    assert not old_nested.exists()
    assert fresh.exists()


def test_concurrent_exclusive_publication_has_one_winner(storage_root: Path) -> None:
    def publish(index: int) -> tuple[int, bytes] | None:
        payload = f"winner-{index}".encode()
        try:
            storage.write_bytes("concurrent", payload, exclusive=True)
        except FileExistsError:
            return None
        return index, payload

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(publish, range(8)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert (storage_root / "concurrent").read_bytes() == winners[0][1]
