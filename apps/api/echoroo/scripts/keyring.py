"""Provision and inspect a local Echoroo keyring."""

from __future__ import annotations

import argparse
import base64
import errno
import fcntl
import json
import os
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

from echoroo.core import keyring

_KEYRING_MODE = 0o400
_LOCK_MODE = 0o600
_PREFIX_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class _ArgumentError(Exception):
    """An argparse failure with no user-controlled message."""


def _json_bytes(ring: keyring.Keyring) -> bytes:
    """Serialize a validated keyring without changing its contents."""

    return (
        json.dumps(ring.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _write_all(descriptor: int, data: bytes) -> None:
    """Write all bytes to a file descriptor."""

    written = 0
    while written < len(data):
        count = os.write(descriptor, data[written:])
        if count <= 0:
            raise OSError("keyring write returned no progress")
        written += count


def _write_new_file(path: Path, data: bytes, mode: int) -> None:
    """Create, write, fsync and close one new file."""

    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            mode,
        )
        created = True
        os.fchmod(descriptor, mode)
        _write_all(descriptor, data)
        os.fsync(descriptor)
    except Exception:
        if created:
            with suppress(FileNotFoundError):
                path.unlink()
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _fsync_directory(directory: Path) -> None:
    """Fsync a directory entry update."""

    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _new_material() -> bytes:
    """Generate fresh key material."""

    return os.urandom(32)


def _created_date() -> str:
    """Return today's UTC date in the keyring format."""

    return datetime.now(UTC).date().isoformat()


def _new_document(prefix: str) -> dict[str, object]:
    """Build a new three-purpose keyring document."""

    if _PREFIX_PATTERN.fullmatch(prefix) is None:
        raise keyring.KeyringConfigError("prefix must be YYYY-MM")
    created = _created_date()
    keys = {
        f"{purpose}-{prefix}": {
            "purpose": purpose,
            "material": base64.b64encode(_new_material()).decode("ascii"),
            "created": created,
        }
        for purpose in ("totp-wrap", "pii-hmac", "audit-hmac")
    }
    return {"format": 1, "keys": keys}


def _create(path: Path, prefix: str | None) -> None:
    """Create a new keyring at an unused path."""

    selected_prefix = prefix or datetime.now(UTC).strftime("%Y-%m")
    ring = keyring.Keyring.from_dict(_new_document(selected_prefix))
    _write_new_file(path, _json_bytes(ring), _KEYRING_MODE)
    print(f"created keyring at {path}")


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Hold a non-blocking exclusive lock for one keyring update."""

    lock_path = Path(f"{path}.lock")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            _LOCK_MODE,
        )
        os.fchmod(descriptor, _LOCK_MODE)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise keyring.KeyringConfigError("keyring update is already in progress") from exc
            raise
        yield
    finally:
        if descriptor is not None:
            with suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _atomic_update(path: Path, ring: keyring.Keyring) -> None:
    """Publish a validated keyring with a same-directory temporary file."""

    temporary = path.parent / f".{path.name}.tmp-{uuid4().hex}"
    rollback = path.parent / f".{path.name}.rollback-{uuid4().hex}"
    replaced = False
    try:
        os.link(path, rollback, follow_symlinks=False)
        _write_new_file(temporary, _json_bytes(ring), _KEYRING_MODE)
        os.replace(temporary, path)
        replaced = True
        try:
            _fsync_directory(path.parent)
        except Exception:
            with suppress(OSError):
                os.replace(rollback, path)
            replaced = False
            raise
        rollback.unlink()
    except Exception:
        if replaced and rollback.exists():
            with suppress(OSError):
                os.replace(rollback, path)
        raise
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()
        with suppress(FileNotFoundError):
            rollback.unlink()


def _add(path: Path, purpose: str, key_id: str) -> None:
    """Add one fresh key under an exclusive update lock."""

    if purpose not in ("totp-wrap", "pii-hmac", "audit-hmac"):
        raise keyring.KeyringConfigError("unknown key purpose")
    keyring._validate_key_id(key_id, error_type=keyring.KeyringConfigError)
    with _exclusive_lock(path):
        current = keyring.load_keyring(path)
        document = current.to_dict()
        keys = document["keys"]
        assert isinstance(keys, dict)
        if key_id in keys:
            raise keyring.KeyringConfigError("key id already exists")
        keys[key_id] = {
            "purpose": purpose,
            "material": base64.b64encode(_new_material()).decode("ascii"),
            "created": _created_date(),
        }
        updated = keyring.Keyring.from_dict(document)
        _atomic_update(path, updated)
    print(f"added key {key_id} ({purpose}) to {path}")


def _check(path: Path) -> None:
    """Validate a keyring and print safe metadata."""

    ring = keyring.load_keyring(path)
    for key_id in ring.key_ids:
        entry = ring.keys[key_id]
        print(f"{key_id}\t{entry.purpose}\t{entry.created}\t{ring.fingerprint(key_id)}")


class _ArgumentParser(argparse.ArgumentParser):
    """Argument parser whose usage errors use the CLI's 0/1 contract."""

    def error(self, _message: str) -> NoReturn:
        """Turn parser errors into a normal command failure."""

        raise _ArgumentError

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        """Keep non-zero argparse exits free of user-supplied arguments."""

        if status:
            raise _ArgumentError
        super().exit(status, message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a new keyring")
    create.add_argument("path", type=Path)
    create.add_argument("--prefix", help="key id month in YYYY-MM format")

    add = subparsers.add_parser("add", help="add one key to an existing keyring")
    add.add_argument("path", type=Path)
    add.add_argument("--purpose", required=True)
    add.add_argument("--id", dest="key_id", required=True)

    check = subparsers.add_parser("check", help="validate and inspect a keyring")
    check.add_argument("path", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the keyring command and return its process exit code."""

    try:
        keyring.harden_process()
        args = _build_parser().parse_args(argv)
        if args.command == "create":
            _create(args.path, args.prefix)
        elif args.command == "add":
            _add(args.path, args.purpose, args.key_id)
        elif args.command == "check":
            _check(args.path)
        else:  # pragma: no cover - argparse enforces the command choices
            raise ValueError("unknown command")
    except _ArgumentError:
        print("invalid arguments; run with --help", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI must report a useful reason
        print(f"keyring command failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
