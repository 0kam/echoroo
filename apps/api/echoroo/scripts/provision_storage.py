"""Provision and verify the application-owned POSIX storage tree."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

from echoroo.core import storage
from echoroo.core.settings import get_settings


def _ensure_root(root: Path) -> None:
    """Create the storage root and its marker when they are absent."""

    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        root.mkdir(parents=True, mode=0o750)
        os.chmod(root, 0o750)
    else:
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise RuntimeError(f"storage root is not a directory: {root}")
        if stat.S_IMODE(root_stat.st_mode) != 0o750:
            if root_stat.st_uid != os.geteuid():
                raise RuntimeError(
                    f"storage root has mode {stat.S_IMODE(root_stat.st_mode):04o}, "
                    f"requires 0750, and is owned by UID {root_stat.st_uid}; "
                    "run provisioning as the owning application user"
                )
            os.chmod(root, 0o750)

    marker = root / storage.MARKER_NAME
    try:
        marker.lstat()
    except FileNotFoundError:
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
            os.chmod(marker, 0o640)


def provision(root: Path) -> None:
    """Provision ``root`` and run the full storage readiness probe."""

    _ensure_root(root)
    settings = get_settings()
    previous_root = settings.STORAGE_ROOT
    settings.STORAGE_ROOT = str(root)
    try:
        storage.ensure_ready(full=True)
    finally:
        settings.STORAGE_ROOT = previous_root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        help="Storage root to provision (default: settings.STORAGE_ROOT).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the storage provisioner and return a process exit code."""

    try:
        args = _build_parser().parse_args(argv)
        root = args.root or Path(get_settings().STORAGE_ROOT)
        provision(root)
    except Exception as exc:  # noqa: BLE001 — CLI must report a useful reason
        print(f"Storage provisioning failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
