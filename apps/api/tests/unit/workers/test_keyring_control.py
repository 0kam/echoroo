"""Tests for the Celery keyring status command and child hardening hook."""

from __future__ import annotations

from typing import Any

from echoroo.core import keyring
from echoroo.workers import keyring_control


def test_keyring_status_returns_worker_cache(monkeypatch: Any) -> None:
    expected = {"state": "0123456789abcdef", "selected": {}, "key_ids": []}
    monkeypatch.setattr(keyring, "keyring_status", lambda: expected)

    assert keyring_control.keyring_status(object()) is expected


def test_keyring_status_hides_keyring_error(monkeypatch: Any) -> None:
    def _fail() -> dict[str, object]:
        raise keyring.KeyringConfigError("material")

    monkeypatch.setattr(keyring, "keyring_status", _fail)

    assert keyring_control.keyring_status(object()) == {"error": "KeyringConfigError"}


def test_worker_process_init_hardens_child(monkeypatch: Any) -> None:
    calls: list[bool] = []
    monkeypatch.setattr(keyring, "harden_process", lambda: calls.append(True))

    keyring_control._harden_worker_process()

    assert calls == [True]
