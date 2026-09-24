"""Tests for process and worker-scoped storage test isolation."""

from __future__ import annotations

import os
from pathlib import Path

from echoroo.core import storage


def test_conftest_storage_root_is_provisioned_and_worker_scoped() -> None:
    root = Path(os.environ["STORAGE_ROOT"])
    run_id = os.environ["ECHOROO_TEST_STORAGE_RUN_ID"]
    worker_id = os.environ.get("PYTEST_XDIST_WORKER", "main")

    assert root != Path("/data/storage")
    assert root.is_dir()
    assert (root / storage.MARKER_NAME).is_file()
    assert run_id in root.parent.name
    assert worker_id in root.parent.name
    assert Path(os.environ["UPLOAD_STAGING_DIR"]).parent == root.parent
    assert Path(os.environ["COMPRESSED_CACHE_DIR"]).parent == root.parent


def test_storage_root_fixture_is_fresh_and_provisioned(storage_root: Path) -> None:
    assert list(storage_root.iterdir()) == [storage_root / storage.MARKER_NAME]
    storage.ensure_ready(full=True)
