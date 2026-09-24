"""Contract tests for the unused POSIX storage API."""

from __future__ import annotations

import os
import stat
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
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
    [
        "",
        "/absolute",
        "trailing/",
        "a//b",
        "../a",
        "a/../b",
        ".",
        "a/./b",
        "a\\b",
        "a\x00b",
        ".hidden",
        ".echoroo-probe/object",
        "nested/.echoroo-storage/object",
        "nested/object/.echoroo-tmp-0123456789abcdef0123456789abcdef",
        "line\nbreak",
        "x" * 256,
        "é" * 128,
    ],
)
def test_path_for_rejects_invalid_keys(storage_root: Path, key: str) -> None:
    with pytest.raises(storage.StorageKeyError):
        storage.path_for(key)


@pytest.mark.parametrize(
    "key",
    [
        ".reserved/first",
        "middle/.reserved/last",
        "last/.reserved",
    ],
)
def test_reserved_components_are_consistent_for_write_list_and_delete(
    storage_root: Path, key: str
) -> None:
    with pytest.raises(storage.StorageKeyError):
        storage.write_bytes(key, b"hidden")
    with pytest.raises(storage.StorageKeyError):
        list(storage.list_prefix(key))
    with pytest.raises(storage.StorageKeyError):
        storage.delete_prefix(key)
    assert list(storage.list_prefix("")) == []


def test_path_for_accepts_nested_key(storage_root: Path) -> None:
    assert storage.path_for("recordings/one.wav") == storage_root / "recordings/one.wav"


def test_utf8_component_boundary_and_temporary_name_contract(storage_root: Path) -> None:
    first = "é" * 127 + "a"
    second = "é" * 127 + "b"
    storage.write_bytes(first, b"first")
    storage.write_bytes(second, b"second")

    assert {item.key for item in storage.list_prefix("")} == {first, second}
    assert storage.is_temporary(".echoroo-tmp-0123456789abcdef0123456789abcdef")
    assert not storage.is_temporary(".name.tmp-0123456789abcdef0123456789abcdef")
    with pytest.raises(storage.StorageKeyError):
        storage.path_for("line\nbreak")


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


def test_full_probe_cold_start_directory_race_is_safe(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_mkdir = storage.os.mkdir
    mkdir_barrier = threading.Barrier(2)
    probe_dir = storage_root / ".echoroo-probe"

    def racing_mkdir(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], mode: int = 0o777) -> None:
        if Path(path) == probe_dir:
            mkdir_barrier.wait(timeout=5)
        original_mkdir(path, mode)

    monkeypatch.setattr(storage.os, "mkdir", racing_mkdir)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: storage.ensure_ready(full=True), range(2)))

    assert results == [None, None]
    assert probe_dir.is_dir()
    assert list(probe_dir.iterdir()) == []


def test_full_probe_cleanup_failure_preserves_original_failure(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("hard links unavailable")

    original_unlink = Path.unlink

    def fail_cleanup(self: Path, *args: object, **kwargs: object) -> None:
        if self.parent == storage_root / ".echoroo-probe":
            raise OSError("probe cleanup unavailable")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(storage.os, "link", fail_link)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)

    with pytest.raises(storage.StorageUnavailable, match="during cleanup") as raised:
        storage.ensure_ready(full=True)

    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "hard links unavailable"


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


def test_write_cleanup_after_publication_failure(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_fsync_directory = storage._fsync_directory

    def fail_destination_fsync(directory: Path) -> None:
        if directory == storage_root:
            return original_fsync_directory(directory)
        if directory == storage_root / "published":
            raise OSError("directory fsync failed after publication")
        return original_fsync_directory(directory)

    monkeypatch.setattr(storage, "_fsync_directory", fail_destination_fsync)
    with pytest.raises(OSError, match="after publication"):
        storage.write_bytes("published/object", b"published")

    assert (storage_root / "published/object").read_bytes() == b"published"
    assert not any(storage.is_temporary(path.name) for path in storage_root.rglob("*"))


def test_publication_fsyncs_existing_ancestor_chain_after_writer_failure(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsync_paths: list[Path] = []
    fsync_lock = threading.Lock()
    destination_barrier = threading.Barrier(2)
    original_fsync_directory = storage._fsync_directory

    def barrier_fsync(directory: Path) -> None:
        with fsync_lock:
            fsync_paths.append(directory)
        if directory == storage_root / "a" / "b":
            destination_barrier.wait(timeout=5)
            if threading.current_thread().name == "writer-a":
                raise OSError("writer A failed before ancestor sync")
        original_fsync_directory(directory)

    monkeypatch.setattr(storage, "_fsync_directory", barrier_fsync)
    failures: list[BaseException] = []

    def writer_a() -> None:
        try:
            storage.write_bytes("a/b/from-a", b"a")
        except BaseException as exc:  # noqa: BLE001 - the test records the injected failure
            failures.append(exc)

    def writer_b() -> None:
        try:
            storage.write_bytes("a/b/from-b", b"b")
        except BaseException as exc:  # noqa: BLE001 - the test records unexpected failures
            failures.append(exc)

    first = threading.Thread(target=writer_a, name="writer-a")
    first.start()
    while not fsync_paths:
        time.sleep(0.001)
    second = threading.Thread(target=writer_b, name="writer-b")
    second.start()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], OSError)
    assert {storage_root / "a" / "b", storage_root / "a", storage_root} <= set(fsync_paths)


def test_published_file_mode_is_0640(storage_root: Path) -> None:
    storage.write_bytes("mode/file", b"data")

    assert stat.S_IMODE((storage_root / "mode/file").stat().st_mode) == 0o640
    assert stat.S_IMODE((storage_root / "mode").stat().st_mode) == 0o750


def test_published_modes_ignore_restrictive_umask(storage_root: Path) -> None:
    previous_umask = os.umask(0o077)
    try:
        storage.write_bytes("restricted/file", b"data")
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE((storage_root / "restricted/file").stat().st_mode) == 0o640
    assert stat.S_IMODE((storage_root / "restricted").stat().st_mode) == 0o750


def test_write_file_copies_source_in_chunks(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = storage_root.parent / "input.bin"
    source_data = b"source data" * 200_000
    source.write_bytes(source_data)

    original_open = Path.open

    class BoundedReader(BytesIO):
        def read(self, size: int = -1) -> bytes:
            if size < 0 or size > storage._COPY_CHUNK_SIZE:
                raise AssertionError("source was read without a bounded chunk")
            return super().read(size)

    source_opens = 0

    def bounded_open(self: Path, *args: object, **kwargs: object) -> object:
        nonlocal source_opens
        if self == source:
            source_opens += 1
            if source_opens == 1:
                return BoundedReader(source_data)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", bounded_open)
    assert storage.write_file(source, "copied/input.bin") == len(source_data)

    assert source.read_bytes() == source_data
    assert (storage_root / "copied/input.bin").read_bytes() == source_data


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


def test_delete_retries_parent_fsync_after_failed_publication_fsync(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.write_bytes("retry/object", b"value")
    original_fsync_directory = storage._fsync_directory
    failed = False

    def fail_once(directory: Path) -> None:
        nonlocal failed
        if directory == storage_root / "retry" and not failed:
            failed = True
            raise OSError("directory fsync failed")
        original_fsync_directory(directory)

    monkeypatch.setattr(storage, "_fsync_directory", fail_once)
    assert storage.delete("retry/object") is False
    assert not (storage_root / "retry/object").exists()
    assert storage.delete("retry/object") is True


def test_list_and_delete_prefix_use_string_prefixes_and_skip_temps(
    storage_root: Path,
) -> None:
    storage.write_bytes("foo/bar/one", b"1")
    storage.write_bytes("foo/barley", b"2")
    storage.write_bytes("foo/baz", b"3")
    storage.write_bytes("foobar", b"4")
    temporary = storage_root / "foo" / ".echoroo-tmp-0123456789abcdef0123456789abcdef"
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


def test_list_prefix_prunes_unrelated_directories(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.write_bytes("search_reference/p/job1/result", b"one")
    storage.write_bytes("search_reference/p/job2/result", b"two")
    storage.write_bytes("other/branch/result", b"other")
    visited: list[Path] = []
    original_scandir = storage.os.scandir

    def recording_scandir(path: str | bytes | os.PathLike[str] | os.PathLike[bytes]) -> object:
        visited.append(Path(path))
        return original_scandir(path)

    monkeypatch.setattr(storage.os, "scandir", recording_scandir)
    assert [item.key for item in storage.list_prefix("search_reference/p/job1")] == [
        "search_reference/p/job1/result"
    ]
    assert storage_root / "search_reference/p/job2" not in visited
    assert storage_root / "other" not in visited

    visited.clear()
    assert list(storage.list_prefix("missing_namespace/")) == []
    assert storage_root / "search_reference" not in visited


def test_iterative_walkers_handle_deep_storage_paths(storage_root: Path) -> None:
    path = storage_root
    for index in range(300):
        path /= f"d{index}"
        path.mkdir()
    object_path = path / "object"
    object_path.write_bytes(b"deep")

    key = "/".join(f"d{index}" for index in range(300)) + "/object"
    assert [item.key for item in storage.list_prefix(key)] == [key]
    old_temp = path / ".echoroo-tmp-0123456789abcdef0123456789abcdef"
    old_temp.write_bytes(b"temporary")
    old_time = time.time() - 3600
    os.utime(old_temp, (old_time, old_time))
    assert storage.sweep_temporaries(timedelta(minutes=30)) == 1


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


@pytest.mark.parametrize(
    ("header", "expected", "partial"),
    [
        ("bytes=0000000000000000000002-0000000000000000000004", (2, 4), True),
        ("bytes=0-" + "9" * 4301, (0, 25), True),
        ("bytes=-" + "9" * 4301, (0, 25), True),
        ("bytes=٠-١", (0, 25), False),
    ],
)
def test_read_range_uses_bounded_ascii_decimal_parsing(
    storage_root: Path,
    header: str,
    expected: tuple[int, int],
    partial: bool,
) -> None:
    data = bytes(range(26))
    storage.write_bytes("range", data)

    result = storage.read_range("range", header)
    assert (result.start, result.end, result.partial) == (*expected, partial)
    assert b"".join(result.stream) == data[expected[0] : expected[1] + 1]

    with pytest.raises(storage.RangeNotSatisfiable):
        storage.read_range("range", "bytes=" + "9" * 4301 + "-")


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
    assert early.stream._stream.closed is True  # noqa: SLF001 — underlying handle is closed


def test_sweep_temporaries_respects_age(storage_root: Path) -> None:
    old = storage_root / ".echoroo-tmp-0123456789abcdef0123456789abcdef"
    fresh = storage_root / ".echoroo-tmp-abcdef0123456789abcdef0123456789"
    nested = storage_root / "nested"
    nested.mkdir()
    old_nested = nested / ".echoroo-tmp-11111111111111111111111111111111"
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


def test_concurrent_writers_create_nested_directories(storage_root: Path) -> None:
    def publish(index: int) -> tuple[str, bytes]:
        key = f"concurrent/nested/object-{index}"
        payload = f"payload-{index}".encode()
        storage.write_bytes(key, payload)
        return key, payload

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(publish, range(8)))

    for key, payload in results:
        assert (storage_root / key).read_bytes() == payload
