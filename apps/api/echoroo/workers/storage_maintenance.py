"""Scheduled cleanup for the application-owned storage and audio cache trees."""

from __future__ import annotations

import logging
import os
import stat
import time
from collections.abc import Iterator
from pathlib import Path

from echoroo.core import storage
from echoroo.core.settings import get_settings
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


def _iter_regular_files(root: Path) -> Iterator[tuple[Path, float]]:
    """Yield regular files below ``root`` without following symlinks."""

    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            directory_stat = directory.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("compressed cache directory lookup failed for %s: %s", directory, exc)
            continue
        if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
            continue

        try:
            with os.scandir(directory) as entries:
                children = list(entries)
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("compressed cache directory scan failed for %s: %s", directory, exc)
            continue

        for entry in children:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(metadata.st_mode):
                    yield Path(entry.path), metadata.st_mtime
            except FileNotFoundError:
                continue
            except OSError as exc:
                logger.warning("compressed cache file lookup failed for %s: %s", entry.path, exc)


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.storage_maintenance.sweep_storage_temporaries",
)
def sweep_storage_temporaries() -> int:
    """Remove abandoned storage publication temporaries."""

    try:
        count = storage.sweep_temporaries()
    except OSError as exc:
        logger.warning("storage temporary sweep encountered a file error: %s", exc)
        return 0
    logger.info("storage temporary sweep removed %d file(s)", count)
    return count


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.storage_maintenance.sweep_compressed_cache",
)
def sweep_compressed_cache() -> int:
    """Remove stale compressed-cache files and abandoned encoder temporaries."""

    settings = get_settings()
    cache_root = Path(settings.COMPRESSED_CACHE_DIR)
    try:
        root_stat = cache_root.lstat()
    except FileNotFoundError:
        logger.info("compressed cache directory is absent: %s", cache_root)
        return 0
    except OSError as exc:
        logger.warning("compressed cache root lookup failed for %s: %s", cache_root, exc)
        return 0

    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        logger.warning("compressed cache root is not a directory: %s", cache_root)
        return 0

    now = time.time()
    cache_cutoff = now - settings.COMPRESSED_CACHE_MAX_AGE_DAYS * 24 * 60 * 60
    temporary_cutoff = now - 24 * 60 * 60
    removed = 0
    for path, modified in _iter_regular_files(cache_root):
        cutoff = temporary_cutoff if path.name.startswith(".echoroo-tmp-") else cache_cutoff
        if modified >= cutoff:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logger.warning("compressed cache cleanup failed for %s: %s", path, exc)
            continue
        removed += 1

    logger.info("compressed cache sweep removed %d file(s)", removed)
    return removed


__all__ = ["sweep_compressed_cache", "sweep_storage_temporaries"]
