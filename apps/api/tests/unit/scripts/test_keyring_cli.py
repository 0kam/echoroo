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


def test_create_has_mode_0400(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """New keyrings are owner-readable only from creation."""

    path = tmp_path / "ring.json"
    open_calls: list[tuple[Path, int, int]] = []
    modes_before_chmod: list[int] = []
    original_open = keyring_cli.os.open
    original_fchmod = keyring_cli.os.fchmod

    def record_open(file_path: Path, flags: int, mode: int = 0o777) -> int:
        descriptor = original_open(file_path, flags, mode)
        open_calls.append((Path(file_path), flags, mode))
        return descriptor

    def record_fchmod(descriptor: int, mode: int) -> None:
        modes_before_chmod.append(stat.S_IMODE(keyring_cli.os.fstat(descriptor).st_mode))
        original_fchmod(descriptor, mode)

    monkeypatch.setattr(keyring_cli.os, "open", record_open)
    monkeypatch.setattr(keyring_cli.os, "fchmod", record_fchmod)
    _create(path)
    assert open_calls == [
        (
            path,
            keyring_cli.os.O_WRONLY
            | keyring_cli.os.O_CREAT
            | keyring_cli.os.O_EXCL
            | keyring_cli.os.O_NOFOLLOW
            | keyring_cli.os.O_CLOEXEC,
            0o400,
        )
    ]
    assert modes_before_chmod == [0o400]
    assert stat.S_IMODE(path.stat().st_mode) == 0o400
    assert len(keyring.load_keyring(path).key_ids) == 3


@pytest.mark.parametrize(
    "argv",
    [
        ["create", "keyring.json", "--material", "SECRET-SENTINEL"],
        ["create", "keyring.json", "SECRET-SENTINEL"],
        ["SECRET-SENTINEL", "keyring.json"],
    ],
)
def test_argument_errors_do_not_echo_supplied_arguments(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """Argparse failures use a fixed message without revealing arguments."""

    assert keyring_cli.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "invalid arguments; run with --help\n"
    assert "SECRET-SENTINEL" not in captured.err


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


@pytest.mark.parametrize(
    "failure",
    [
        "write",
        "partial-write",
        "temporary-fsync",
        "directory-fsync",
        "publish-replace",
        "rollback-replace",
        "cleanup",
    ],
)
def test_atomic_add_failures_leave_original_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Each atomic-update failure leaves a valid old or new recovery state."""

    path = tmp_path / "ring.json"
    _create(path)
    original = path.read_bytes()

    if failure == "write":

        def fail_write(_descriptor: int, _data: bytes) -> int:
            raise OSError("injected write failure")

        monkeypatch.setattr(keyring_cli.os, "write", fail_write)
    elif failure == "partial-write":
        write_calls = 0

        def partial_write(descriptor: int, data: bytes) -> int:
            nonlocal write_calls
            write_calls += 1
            if write_calls == 1:
                return min(7, len(data))
            raise OSError("injected write failure")

        monkeypatch.setattr(keyring_cli.os, "write", partial_write)
    elif failure in ("temporary-fsync", "directory-fsync"):
        fsync_calls = 0

        def fail_fsync(_descriptor: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if (failure == "temporary-fsync" and fsync_calls == 1) or (
                failure in ("directory-fsync", "rollback-replace") and fsync_calls == 2
            ):
                raise OSError("injected fsync failure")

        monkeypatch.setattr(keyring_cli.os, "fsync", fail_fsync)
    elif failure == "publish-replace":
        replace_calls = 0
        original_replace = keyring_cli.os.replace

        def fail_replace(source: Path, destination: Path) -> None:
            nonlocal replace_calls
            replace_calls += 1
            if (failure == "publish-replace" and replace_calls == 1) or (
                failure == "rollback-replace" and replace_calls == 2
            ):
                raise OSError("injected replace failure")
            original_replace(source, destination)

        monkeypatch.setattr(keyring_cli.os, "replace", fail_replace)
    elif failure == "rollback-replace":
        fsync_calls = 0
        replace_calls = 0
        original_replace = keyring_cli.os.replace

        def fail_directory_fsync(_descriptor: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 2:
                raise OSError("injected fsync failure")

        def fail_rollback_replace(source: Path, destination: Path) -> None:
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("injected replace failure")
            original_replace(source, destination)

        monkeypatch.setattr(keyring_cli.os, "fsync", fail_directory_fsync)
        monkeypatch.setattr(keyring_cli.os, "replace", fail_rollback_replace)
    else:
        original_unlink = Path.unlink
        rollback_unlinks = 0

        def fail_cleanup(file_path: Path, *, missing_ok: bool = False) -> None:
            nonlocal rollback_unlinks
            if file_path.name.startswith(".ring.json.rollback-") and rollback_unlinks == 0:
                rollback_unlinks += 1
                raise OSError("injected cleanup failure")
            original_unlink(file_path, missing_ok=missing_ok)

        monkeypatch.setattr(Path, "unlink", fail_cleanup)

    assert (
        keyring_cli.main(["add", str(path), "--purpose", "pii-hmac", "--id", "pii-hmac-next"]) == 1
    )
    if failure == "rollback-replace":
        assert path.read_bytes() != original
        assert "pii-hmac-next" in keyring.load_keyring(path).key_ids
    else:
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
