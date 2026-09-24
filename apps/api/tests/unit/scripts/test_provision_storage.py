"""Tests for the storage provisioning CLI."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from echoroo.scripts import provision_storage


def test_provision_storage_is_idempotent_and_runs_full_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "storage"
    calls: list[bool] = []
    monkeypatch.setattr(
        provision_storage.storage,
        "ensure_ready",
        lambda *, full=False: calls.append(full),
    )

    assert provision_storage.main([str(root)]) == 0
    marker = root / provision_storage.storage.MARKER_NAME
    marker.write_bytes(b"keep")
    assert provision_storage.main([str(root)]) == 0

    assert stat.S_IMODE(root.stat().st_mode) == 0o750
    assert marker.read_bytes() == b"keep"
    assert calls == [True, True]


def test_provision_storage_reports_probe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        provision_storage.storage,
        "ensure_ready",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("probe failed")),
    )

    assert provision_storage.main([str(tmp_path / "storage")]) == 1
    assert "probe failed" in capsys.readouterr().err


def test_provision_storage_normalizes_existing_root_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing root owned by the current user is tightened to 0750."""
    root = tmp_path / "storage"
    root.mkdir()
    root.chmod(0o755)
    monkeypatch.setattr(
        provision_storage.storage,
        "ensure_ready",
        lambda **_kwargs: None,
    )

    assert provision_storage.main([str(root)]) == 0
    assert stat.S_IMODE(root.stat().st_mode) == 0o750
