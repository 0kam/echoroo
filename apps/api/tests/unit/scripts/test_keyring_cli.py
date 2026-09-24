"""Tests for the local keyring provisioning CLI."""

from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest

from echoroo.core import keyring
from echoroo.scripts import keyring as keyring_cli


def _create(path: Path) -> None:
    """Create a deterministic-month test keyring."""

    assert keyring_cli.main(["create", str(path), "--prefix", "2026-09"]) == 0


def test_create_refuses_existing_path(tmp_path: Path) -> None:
    """Create uses exclusive creation and never overwrites an existing file."""

    path = tmp_path / "ring.json"
    original = b"keep this file"
    path.write_bytes(original)
    assert keyring_cli.main(["create", str(path), "--prefix", "2026-09"]) == 1
    assert path.read_bytes() == original


def test_create_has_mode_0400(tmp_path: Path) -> None:
    """New keyrings are owner-readable only from creation."""

    path = tmp_path / "ring.json"
    _create(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert len(keyring.load_keyring(path).key_ids) == 3


def test_add_preserves_existing_keys_and_writes_new_material(tmp_path: Path) -> None:
    """Add publishes the old entries plus one fresh validated entry."""

    path = tmp_path / "ring.json"
    _create(path)
    before = keyring.load_keyring(path)
    assert (
        keyring_cli.main(["add", str(path), "--purpose", "pii-hmac", "--id", "pii-hmac-next"]) == 0
    )
    after = keyring.load_keyring(path)
    assert set(after.key_ids) == set(before.key_ids) | {"pii-hmac-next"}
    for key_id in before.key_ids:
        assert after.keys[key_id] == before.keys[key_id]
    assert after.keys["pii-hmac-next"].purpose == "pii-hmac"
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert stat.S_IMODE((tmp_path / "ring.json.lock").stat().st_mode) == 0o600


def test_add_rejects_duplicate_id_without_changing_ring(tmp_path: Path) -> None:
    """Duplicate ids are rejected before publication."""

    path = tmp_path / "ring.json"
    _create(path)
    original = path.read_bytes()
    assert (
        keyring_cli.main(["add", str(path), "--purpose", "pii-hmac", "--id", "pii-hmac-2026-09"])
        == 1
    )
    assert path.read_bytes() == original


def test_concurrent_add_fails_without_waiting(tmp_path: Path) -> None:
    """A held lock makes a second add fail immediately."""

    path = tmp_path / "ring.json"
    _create(path)
    with keyring_cli._exclusive_lock(path):
        assert (
            keyring_cli.main(["add", str(path), "--purpose", "pii-hmac", "--id", "pii-hmac-next"])
            == 1
        )


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
def test_atomic_add_failures_leave_original_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Write, fsync and replace failures do not damage the current ring."""

    path = tmp_path / "ring.json"
    _create(path)
    original = path.read_bytes()

    if failure == "write":

        def fail_write(_descriptor: int, _data: bytes) -> int:
            raise OSError("injected write failure")

        monkeypatch.setattr(keyring_cli.os, "write", fail_write)
    elif failure == "fsync":

        def fail_fsync(_descriptor: int) -> None:
            raise OSError("injected fsync failure")

        monkeypatch.setattr(keyring_cli.os, "fsync", fail_fsync)
    else:

        def fail_replace(_source: Path, _destination: Path) -> None:
            raise OSError("injected replace failure")

        monkeypatch.setattr(keyring_cli.os, "replace", fail_replace)

    assert (
        keyring_cli.main(["add", str(path), "--purpose", "pii-hmac", "--id", "pii-hmac-next"]) == 1
    )
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".ring.json.tmp-*"))
    assert not list(tmp_path.glob(".ring.json.rollback-*"))


def test_check_prints_fingerprints_not_material(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Check output contains safe metadata only."""

    path = tmp_path / "ring.json"
    _create(path)
    capsys.readouterr()
    ring = keyring.load_keyring(path)
    materials = [base64.b64encode(entry.material).decode("ascii") for entry in ring.keys.values()]

    assert keyring_cli.main(["check", str(path)]) == 0
    output = capsys.readouterr().out
    for key_id in ring.key_ids:
        assert key_id in output
        assert ring.fingerprint(key_id) in output
    for material in materials:
        assert material not in output
