"""POSIX storage helpers for the application-owned storage tree."""

from __future__ import annotations

import logging
import os
import re
import stat
from collections.abc import Iterable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from echoroo.core.settings import get_settings

logger = logging.getLogger(__name__)

_MARKER_NAME = ".echoroo-storage"
_PROBE_NAME = ".echoroo-probe"
_TEMPORARY_PATTERN = re.compile(r"^\.echoroo-tmp-[0-9a-f]{32}$")
_RANGE_CHUNK_SIZE = 64 * 1024
_COPY_CHUNK_SIZE = 1024 * 1024


class StorageError(Exception):
    """Base error for the POSIX storage API."""


class StorageKeyError(StorageError, ValueError):
    """The supplied storage key is not a safe object key."""


class StorageUnavailable(StorageError):
    """The provisioned storage tree is missing or unusable."""


class RangeNotSatisfiable(StorageError):
    """The requested byte range cannot be served."""

    def __init__(self, total: int) -> None:
        super().__init__(f"range is not satisfiable for an object of {total} bytes")
        self.total = total


@dataclass(frozen=True)
class StoredObject:
    """A file returned by :func:`list_prefix`."""

    key: str
    size: int
    modified: datetime


@dataclass(frozen=True)
class StorageDeletionError:
    """Structured error for one failed batch deletion."""

    key: str
    code: str
    message: str


@dataclass(frozen=True)
class BatchDeleteResult:
    """Result of deleting a collection of storage keys."""

    deleted: list[str]
    errors: list[StorageDeletionError]


class _RangeStream(Iterator[bytes]):
    """Bounded iterator over an open file handle."""

    def __init__(self, stream: BinaryIO, start: int, end: int) -> None:
        self._stream = stream
        self._position = start
        self._end = end
        self._closed = False
        self._stream.seek(start)

    def __iter__(self) -> _RangeStream:
        return self

    def __next__(self) -> bytes:
        if self._closed or self._position > self._end:
            self.close()
            raise StopIteration

        count = min(_RANGE_CHUNK_SIZE, self._end - self._position + 1)
        chunk = self._stream.read(count)
        if not chunk:
            self.close()
            raise StopIteration
        self._position += len(chunk)
        if self._position > self._end:
            self.close()
        return chunk

    def close(self) -> None:
        """Close the underlying file handle."""

        if not self._closed:
            self._closed = True
            self._stream.close()


@dataclass
class RangeRead:
    """A bounded byte iterator and the range metadata used to serve it."""

    stream: _RangeStream
    start: int
    end: int
    total: int
    partial: bool

    def close(self) -> None:
        """Close the reader before it is exhausted."""

        self.stream.close()


def is_temporary(name: str) -> bool:
    """Return whether ``name`` has the storage temporary-file shape."""

    return bool(_TEMPORARY_PATTERN.fullmatch(name))


def root() -> Path:
    """Return the configured storage root."""

    return Path(get_settings().STORAGE_ROOT)


def _key_parts(key: str) -> list[str]:
    if not isinstance(key, str):
        raise StorageKeyError("storage key must be a string")
    if not key:
        raise StorageKeyError("storage key must not be empty")
    if key.startswith("/"):
        raise StorageKeyError("storage key must not start with '/'")
    if key.endswith("/"):
        raise StorageKeyError("storage key must not end with '/'")
    if "\x00" in key:
        raise StorageKeyError("storage key must not contain NUL")
    if "\\" in key:
        raise StorageKeyError("storage key must not contain backslashes")

    parts = key.split("/")
    if any(not part for part in parts):
        raise StorageKeyError("storage key must not contain empty components")
    _validate_components(parts, "storage key")
    return parts


def _is_reserved_component(component: str) -> bool:
    """Return whether a path component is unavailable to storage keys."""

    if component.startswith("."):
        return True
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in component):
        return True
    try:
        return len(component.encode("utf-8")) > 255
    except UnicodeEncodeError:
        return True


def _validate_components(parts: list[str], label: str) -> None:
    for part in parts:
        if _is_reserved_component(part):
            raise StorageKeyError(f"{label} contains a reserved component")


def _lookup_path(base: Path, parts: list[str]) -> Path:
    current = base
    for part in parts:
        current /= part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(current_stat.st_mode):
            raise StorageKeyError(f"storage key contains symlink component: {part}")
    return base.joinpath(*parts)


def path_for(key: str) -> Path:
    """Return the safe filesystem path for a storage key."""

    parts = _key_parts(key)
    return _lookup_path(_check_root(), parts)


def _unavailable(message: str, cause: BaseException | None = None) -> StorageUnavailable:
    error = StorageUnavailable(message)
    if cause is not None:
        error.__cause__ = cause
    return error


def _check_root() -> Path:
    storage_root = root()
    try:
        root_stat = storage_root.lstat()
    except FileNotFoundError as exc:
        raise _unavailable(f"storage root does not exist: {storage_root}", exc) from exc
    except OSError as exc:
        raise _unavailable(f"storage root cannot be inspected: {storage_root}", exc) from exc

    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise StorageUnavailable(f"storage root is not a directory: {storage_root}")

    try:
        with os.scandir(storage_root):
            pass
        marker_stat = (storage_root / _MARKER_NAME).lstat()
    except FileNotFoundError as exc:
        raise _unavailable(
            f"storage root is not provisioned; missing {_MARKER_NAME}: {storage_root}",
            exc,
        ) from exc
    except OSError as exc:
        raise _unavailable(f"storage root is unreadable: {storage_root}", exc) from exc

    if stat.S_ISLNK(marker_stat.st_mode) or not stat.S_ISREG(marker_stat.st_mode):
        raise StorageUnavailable(f"storage marker is not a regular file: {storage_root}")
    return storage_root


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _set_directory_mode(directory: Path) -> None:
    os.chmod(directory, 0o750)


def _full_probe(storage_root: Path) -> None:
    """Exercise every primitive publication relies on inside the probe directory."""

    probe_dir = storage_root / _PROBE_NAME
    token = uuid4().hex
    first = probe_dir / f"probe-{token}.first"
    replaced = probe_dir / f"probe-{token}.replaced"
    linked = probe_dir / f"probe-{token}.linked"
    original_failure: Exception | None = None
    cleanup_failures: list[OSError] = []
    try:
        try:
            probe_stat = probe_dir.lstat()
        except FileNotFoundError:
            try:
                os.mkdir(probe_dir, 0o750)
            except FileExistsError as exc:
                probe_stat = probe_dir.lstat()
                if stat.S_ISLNK(probe_stat.st_mode) or not stat.S_ISDIR(probe_stat.st_mode):
                    raise OSError(f"probe path is not a directory: {probe_dir}") from exc
            else:
                _set_directory_mode(probe_dir)
        else:
            if stat.S_ISLNK(probe_stat.st_mode) or not stat.S_ISDIR(probe_stat.st_mode):
                raise OSError(f"probe path is not a directory: {probe_dir}")

        with first.open("wb") as stream:
            stream.write(b"echoroo storage probe")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(first, replaced)
        os.link(replaced, linked)
        try:
            os.link(replaced, linked)
        except FileExistsError:
            pass
        else:
            raise OSError("hard-link publication did not refuse a collision")
        _fsync_directory(probe_dir)
    except Exception as exc:
        original_failure = exc
    finally:
        for candidate in (first, replaced, linked):
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                cleanup_failures.append(exc)

    if original_failure is not None:
        detail = "storage full probe failed"
        if cleanup_failures:
            detail += f" during cleanup: {cleanup_failures[0]}"
        error = _unavailable(f"{detail}: {storage_root}", original_failure)
        raise error from original_failure
    if cleanup_failures:
        error = _unavailable(f"storage full probe cleanup failed: {storage_root}", cleanup_failures[0])
        raise error from cleanup_failures[0]

    try:
        _fsync_directory(probe_dir)
    except OSError as exc:
        raise _unavailable(f"storage full probe cleanup failed: {storage_root}", exc) from exc


def ensure_ready(*, full: bool = False) -> None:
    """Verify the provisioned storage root and optionally run its full probe."""

    storage_root = _check_root()
    if full:
        _full_probe(storage_root)


def _ensure_destination(storage_root: Path, path: Path) -> Path:
    parts = path.relative_to(storage_root).parts
    destination = storage_root
    for part in parts[:-1]:
        destination /= part
        try:
            current_stat = destination.lstat()
        except FileNotFoundError:
            try:
                os.mkdir(destination, 0o750)
            except FileExistsError:
                current_stat = destination.lstat()
            else:
                _set_directory_mode(destination)
                continue
        if stat.S_ISLNK(current_stat.st_mode):
            raise StorageKeyError(f"storage key contains symlink component: {part}")
        if not stat.S_ISDIR(current_stat.st_mode):
            raise NotADirectoryError(destination)
    return path.parent


def _publication_directories(storage_root: Path, destination: Path) -> list[Path]:
    directories: list[Path] = []
    current = destination
    while True:
        directories.append(current)
        if current == storage_root:
            return directories
        current = current.parent


def _write_temp(
    temporary: Path,
    *,
    data: bytes | None = None,
    source: Path | None = None,
) -> int:
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o640,
    )
    descriptor_open = True
    try:
        os.chmod(temporary, 0o640)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor_open = False
            written = 0
            if data is not None:
                stream.write(data)
                written = len(data)
            else:
                assert source is not None
                with source.open("rb") as source_stream:
                    while True:
                        chunk = source_stream.read(_COPY_CHUNK_SIZE)
                        if not chunk:
                            break
                        stream.write(chunk)
                        written += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
            return written
    finally:
        if descriptor_open:
            os.close(descriptor)


def _write_published(
    storage_root: Path,
    path: Path,
    *,
    data: bytes | None = None,
    source: Path | None = None,
    exclusive: bool,
) -> int:
    destination = _ensure_destination(storage_root, path)
    temporary = destination / f".echoroo-tmp-{uuid4().hex}"
    try:
        written = _write_temp(temporary, data=data, source=source)
        if exclusive:
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        for directory in _publication_directories(storage_root, destination):
            _fsync_directory(directory)
        return written
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def write_bytes(key: str, data: bytes, *, exclusive: bool = False) -> int:
    """Write bytes atomically and return the published byte count."""

    parts = _key_parts(key)
    storage_root = _check_root()
    destination = _lookup_path(storage_root, parts)
    return _write_published(storage_root, destination, data=data, exclusive=exclusive)


def write_file(src: Path, key: str, *, exclusive: bool = False) -> int:
    """Copy a local file into storage atomically."""

    parts = _key_parts(key)
    storage_root = _check_root()
    destination = _lookup_path(storage_root, parts)
    return _write_published(storage_root, destination, source=Path(src), exclusive=exclusive)


def copy(src_key: str, dst_key: str) -> int:
    """Copy one stored object to another key."""

    source_parts = _key_parts(src_key)
    destination_parts = _key_parts(dst_key)
    storage_root = _check_root()
    source = _lookup_path(storage_root, source_parts)
    destination = _lookup_path(storage_root, destination_parts)
    return _write_published(storage_root, destination, source=source, exclusive=False)


def exists(key: str) -> bool:
    """Return whether the key currently has a filesystem entry."""

    parts = _key_parts(key)
    storage_root = _check_root()
    path = _lookup_path(storage_root, parts)
    try:
        path.stat()
    except FileNotFoundError:
        _check_root()
        return False
    return True


def size(key: str) -> int | None:
    """Return the key's size, or ``None`` when it is absent."""

    parts = _key_parts(key)
    storage_root = _check_root()
    path = _lookup_path(storage_root, parts)
    try:
        return path.stat().st_size
    except FileNotFoundError:
        _check_root()
        return None


def open_read(key: str) -> BinaryIO:
    """Open a stored object for binary reading."""

    parts = _key_parts(key)
    storage_root = _check_root()
    path = _lookup_path(storage_root, parts)
    return path.open("rb")


def _parse_range(
    range_header: str | None,
    total: int,
) -> tuple[int, int, bool]:
    if range_header is None or not isinstance(range_header, str):
        return 0, total - 1, False

    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", range_header)
    if match is None:
        return 0, total - 1, False
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return 0, total - 1, False
    if total == 0:
        raise RangeNotSatisfiable(total)

    if not start_text:
        normalized_end = end_text.lstrip("0") or "0"
        if normalized_end == "0":
            return 0, total - 1, False
        suffix_length = total if len(normalized_end) > 19 else min(int(normalized_end), total)
        return total - suffix_length, total - 1, True

    normalized_start = start_text.lstrip("0") or "0"
    if len(normalized_start) > 19:
        raise RangeNotSatisfiable(total)
    start = int(normalized_start)
    if start >= total:
        raise RangeNotSatisfiable(total)
    if not end_text:
        end = total - 1
    else:
        normalized_end = end_text.lstrip("0") or "0"
        end = total - 1 if len(normalized_end) > 19 else min(int(normalized_end), total - 1)
    if end < start:
        return 0, total - 1, False
    return start, end, True


def read_range(key: str, range_header: str | None) -> RangeRead:
    """Open a whole object or one bounded inclusive byte range."""

    stream = open_read(key)
    try:
        total = os.fstat(stream.fileno()).st_size
        start, end, partial = _parse_range(range_header, total)
        bounded = _RangeStream(stream, start, end)
    except Exception:
        stream.close()
        raise
    return RangeRead(bounded, start, end, total, partial)


def _validate_prefix(prefix: str) -> tuple[list[str], bool]:
    if not isinstance(prefix, str):
        raise StorageKeyError("storage prefix must be a string")
    if not prefix:
        return [], False
    if prefix.startswith("/") or "\x00" in prefix or "\\" in prefix:
        raise StorageKeyError("storage prefix is not a safe key prefix")
    trailing = prefix.endswith("/")
    body = prefix[:-1] if trailing else prefix
    parts = body.split("/")
    if any(not part for part in parts):
        raise StorageKeyError("storage prefix contains an invalid component")
    _validate_components(parts, "storage prefix")
    return parts, trailing


def _scan_base(storage_root: Path, parts: list[str], trailing: bool) -> Path | None:
    candidate_parts = parts if trailing else parts[:-1]
    base = storage_root
    for part in candidate_parts:
        candidate = base / part
        try:
            candidate_stat = candidate.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISDIR(candidate_stat.st_mode):
            return None
        base = candidate
    return base


def _prefix_can_match(path_key: str, prefix: str) -> bool:
    """Whether a directory at ``path_key`` can hold a key starting with ``prefix``."""
    if not prefix or not path_key or path_key.startswith(prefix):
        return True
    # Descendants of ``job1/`` never match ``job10``: require a component boundary.
    return prefix.startswith(path_key + "/")


def _relative_key(storage_root: Path, path: Path) -> str:
    relative = path.relative_to(storage_root)
    return relative.as_posix() if relative.parts else ""


def _walk_files(
    storage_root: Path,
    directory: Path,
    prefix: str,
) -> Iterator[tuple[Path, os.stat_result]]:
    """Iteratively walk matching regular files with closed scandir handles."""

    stack = [directory]
    while stack:
        current = stack.pop()
        current_key = _relative_key(storage_root, current)
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except FileNotFoundError:
            continue

        child_directories: list[Path] = []
        for entry in entries:
            if _is_reserved_component(entry.name):
                continue
            child_key = f"{current_key}/{entry.name}" if current_key else entry.name
            if not _prefix_can_match(child_key, prefix):
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    child_directories.append(Path(entry.path))
                elif child_key.startswith(prefix) and entry.is_file(follow_symlinks=False):
                    yield Path(entry.path), entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
        stack.extend(reversed(child_directories))


def list_prefix(prefix: str) -> Iterator[StoredObject]:
    """Yield regular files whose keys start with ``prefix``."""

    parts, trailing = _validate_prefix(prefix)
    storage_root = _check_root()
    base = _scan_base(storage_root, parts, trailing)
    if base is None:
        return
    for path, metadata in _walk_files(storage_root, base, prefix):
        key = path.relative_to(storage_root).as_posix()
        yield StoredObject(
            key=key,
            size=metadata.st_size,
            modified=datetime.fromtimestamp(metadata.st_mtime, tz=UTC),
        )


def _delete_resolved(key: str, path: Path) -> tuple[bool, OSError | None]:
    try:
        os.unlink(path)
    except FileNotFoundError:
        # Absence only counts as deletion while the tree is still there: a
        # lost mount must not report every key as deleted.
        _check_root()
        try:
            path.parent.lstat()
        except FileNotFoundError:
            return True, None
        except OSError as exc:
            logger.warning("storage delete lookup failed for %s: %s", key, exc)
            return False, exc
        try:
            _fsync_directory(path.parent)
        except OSError as exc:
            logger.warning("storage directory fsync failed after absent %s: %s", key, exc)
            return False, exc
        return True, None
    except OSError as exc:
        logger.warning("storage delete failed for %s: %s", key, exc)
        return False, exc

    try:
        _fsync_directory(path.parent)
    except OSError as exc:
        logger.warning("storage directory fsync failed after deleting %s: %s", key, exc)
        return False, exc
    return True, None


def delete(key: str) -> bool:
    """Delete a file key, returning whether it is gone afterward."""

    parts = _key_parts(key)
    storage_root = _check_root()
    try:
        path = _lookup_path(storage_root, parts)
    except OSError as exc:
        logger.warning("storage delete lookup failed for %s: %s", key, exc)
        return False
    deleted, _ = _delete_resolved(key, path)
    return deleted


def delete_prefix(prefix: str) -> int:
    """Delete files matching an S3-style string prefix."""

    if not prefix:
        raise StorageKeyError("refusing to delete the storage root")
    parts, trailing = _validate_prefix(prefix)
    storage_root = _check_root()
    base = _scan_base(storage_root, parts, trailing)
    if base is None:
        return 0
    deleted = 0
    for path, _ in _walk_files(storage_root, base, prefix):
        key = path.relative_to(storage_root).as_posix()
        removed, _ = _delete_resolved(key, path)
        if removed:
            deleted += 1
    return deleted


def _deletion_error(key: str, error: BaseException) -> StorageDeletionError:
    if isinstance(error, StorageKeyError):
        code = "InvalidKey"
    elif isinstance(error, OSError) and error.errno is not None:
        code = str(error.errno)
    else:
        code = type(error).__name__
    return StorageDeletionError(key, code, str(error))


def delete_many(keys: Iterable[str]) -> BatchDeleteResult:
    """Delete all supplied keys and collect per-key failures."""

    deleted: list[str] = []
    errors: list[StorageDeletionError] = []
    prepared: list[tuple[str, list[str]]] = []
    for key in keys:
        try:
            prepared.append((key, _key_parts(key)))
        except StorageKeyError as exc:
            errors.append(_deletion_error(key, exc))
    storage_root = _check_root()
    for key, parts in prepared:
        try:
            path = _lookup_path(storage_root, parts)
        except (StorageKeyError, OSError) as exc:
            errors.append(_deletion_error(key, exc))
            continue
        removed, error = _delete_resolved(key, path)
        if removed:
            deleted.append(key)
        elif error is not None:
            errors.append(_deletion_error(key, error))
    return BatchDeleteResult(deleted=deleted, errors=errors)


def sweep_temporaries(max_age: timedelta = timedelta(hours=24)) -> int:
    """Delete temporary files older than ``max_age`` and return the count."""

    storage_root = _check_root()
    cutoff = datetime.now(UTC).timestamp() - max_age.total_seconds()
    removed = 0
    for path, metadata in _walk_files_including_temporaries(storage_root):
        if not is_temporary(path.name) or metadata.st_mtime >= cutoff:
            continue
        try:
            os.unlink(path)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("temporary cleanup failed for %s: %s", path, exc)
            continue
        removed += 1
    return removed


def _walk_files_including_temporaries(
    directory: Path,
) -> Iterator[tuple[Path, os.stat_result]]:
    """Iteratively walk regular files while retaining generated temporaries."""

    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as iterator:
                entries = list(iterator)
        except FileNotFoundError:
            continue

        child_directories: list[Path] = []
        for entry in entries:
            if entry.name in {_MARKER_NAME, _PROBE_NAME}:
                continue
            temporary = is_temporary(entry.name)
            if _is_reserved_component(entry.name) and not temporary:
                continue
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if not temporary:
                        child_directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path), entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
        stack.extend(reversed(child_directories))


__all__ = [
    "BatchDeleteResult",
    "RangeNotSatisfiable",
    "RangeRead",
    "StorageDeletionError",
    "StorageError",
    "StorageKeyError",
    "StorageUnavailable",
    "StoredObject",
    "copy",
    "delete",
    "delete_many",
    "delete_prefix",
    "ensure_ready",
    "exists",
    "is_temporary",
    "list_prefix",
    "open_read",
    "path_for",
    "read_range",
    "root",
    "size",
    "sweep_temporaries",
    "write_bytes",
    "write_file",
]
