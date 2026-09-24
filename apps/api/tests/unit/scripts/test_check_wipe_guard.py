"""Unit coverage for the storage-backed wipe guard marker check."""

from __future__ import annotations

import pytest

from echoroo.core import storage
from echoroo.scripts import check_wipe_guard as mod


def test_genesis_marker_check_uses_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def exists(key: str) -> bool:
        calls.append(key)
        return True

    monkeypatch.setattr(storage, "exists", exists)

    assert mod._check_s3_marker() is True
    assert calls == [mod.S3_GENESIS_KEY]


@pytest.mark.parametrize("error", [storage.StorageUnavailable("mount missing"), OSError("I/O")])
def test_storage_errors_use_infrastructure_exit_path(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(mod, "_load_settings", lambda: "database-url")
    monkeypatch.setattr(mod, "_check_db", lambda _database_url: (False, True))
    monkeypatch.setattr(storage, "exists", lambda _key: (_ for _ in ()).throw(error))

    assert mod.main([]) == 20
