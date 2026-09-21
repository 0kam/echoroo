"""Local-filesystem staging helpers for resumable upload chunks.

Callers serialise operations per file with a database row lock; this module
does not use ``fcntl`` or ``flock`` because the production mount may not
support them.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import UUID

from echoroo.core.settings import get_settings


class StagingOffsetError(Exception):
    """The chunk does not start where the staged file ends."""

    def __init__(self, expected_offset: int) -> None:
        super().__init__(f"expected offset {expected_offset}")
        self.expected_offset = expected_offset


class StagingSizeError(Exception):
    """The chunk would make the file larger than its declared size."""


def _require_uuid(value: UUID) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError("session_id and file_id must be UUID instances")
    return value


def staging_root() -> Path:
    """Return the configured root directory for staged upload chunks."""

    return Path(get_settings().UPLOAD_STAGING_DIR)


def session_dir(session_id: UUID) -> Path:
    """Return the staging directory for one upload session."""

    return staging_root() / str(_require_uuid(session_id))


def part_path(session_id: UUID, file_id: UUID) -> Path:
    """Return the staged part-file path for one upload file."""

    return session_dir(session_id) / f"{_require_uuid(file_id)}.part"


def staged_size(session_id: UUID, file_id: UUID) -> int:
    """Return the current staged byte count, or zero when no part exists."""

    path = part_path(session_id, file_id)
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def append_chunk(
    session_id: UUID,
    file_id: UUID,
    *,
    offset: int,
    data: bytes,
    declared_size: int,
) -> int:
    """Append one chunk at the expected offset and return the new offset."""

    current = staged_size(session_id, file_id)
    if offset != current:
        raise StagingOffsetError(current)
    if offset + len(data) > declared_size:
        raise StagingSizeError

    directory = session_dir(session_id)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = part_path(session_id, file_id)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count == 0:
                raise OSError("os.write returned zero bytes")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)

    return offset + len(data)


def truncate_to(session_id: UUID, file_id: UUID, size: int) -> None:
    """Shrink a staged part file to ``size`` bytes when it exists."""

    if size < 0:
        raise ValueError("size must not be negative")

    path = part_path(session_id, file_id)
    try:
        current = path.stat().st_size
    except FileNotFoundError:
        return
    if size > current:
        raise ValueError("size cannot exceed the current staged size")
    os.truncate(path, size)


def remove_session(session_id: UUID) -> None:
    """Remove a session's staging directory if it exists."""

    shutil.rmtree(session_dir(session_id), ignore_errors=True)


def list_staged_sessions() -> list[UUID]:
    """Return UUID-named staging directories directly below the root."""

    root = staging_root()
    if not root.exists():
        return []

    sessions: list[UUID] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            sessions.append(UUID(entry.name))
        except ValueError:
            continue
    return sessions


__all__ = [
    "StagingOffsetError",
    "StagingSizeError",
    "append_chunk",
    "list_staged_sessions",
    "part_path",
    "remove_session",
    "session_dir",
    "staged_size",
    "staging_root",
    "truncate_to",
]
