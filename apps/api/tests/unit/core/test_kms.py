"""Tests for the keyring-backed cryptographic adapter."""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import pytest

from echoroo.core import kms
from echoroo.core.keyring import KeyringAuthError, KeyringKeyError, load_keyring
from echoroo.core.settings import get_settings


def _key_material(key_id: str) -> bytes:
    """Read one test key's material from the fixture keyring."""
    ring = load_keyring(get_settings().KEYRING_FILE)
    return ring.keys[key_id].material


def test_wrap_unwrap_with_explicit_key_id() -> None:
    plaintext = b"d" * 32

    wrapped = kms.wrap_dek(plaintext, key_id="test-totp-wrap")
    recovered = kms.unwrap_dek(wrapped, key_id="test-totp-wrap")

    assert isinstance(recovered, bytearray)
    assert recovered == plaintext


def test_unwrap_rejects_wrong_key_id() -> None:
    wrapped = kms.wrap_dek(b"d" * 32, key_id="test-totp-wrap")

    with pytest.raises(KeyringKeyError):
        kms.unwrap_dek(wrapped, key_id="test-totp-wrap-old")


def test_rewrap_uses_explicit_source_and_target_ids() -> None:
    plaintext = b"d" * 32
    wrapped = kms.wrap_dek(plaintext, key_id="test-totp-wrap-old")

    rewrapped = kms.rewrap_dek(
        wrapped,
        source_key_id="test-totp-wrap-old",
        destination_key_id="test-totp-wrap",
    )

    assert kms.unwrap_dek(rewrapped, key_id="test-totp-wrap") == plaintext
    with pytest.raises(KeyringKeyError):
        kms.unwrap_dek(rewrapped, key_id="test-totp-wrap-old")


def test_compute_pii_hash_matches_known_answer() -> None:
    value = "subject@example.com"
    expected = hmac.new(
        _key_material("test-pii-hmac"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    assert kms.compute_pii_hash(value) == expected


def test_compute_pii_hash_dual_write_shape(select_keys: Any) -> None:
    select = select_keys
    assert kms.compute_pii_hash_dual("subject@example.com").keys() == {"v1"}

    select(KEYRING_PII_KEY_V2="test-pii-hmac-v2")
    result = kms.compute_pii_hash_dual("subject@example.com")

    assert result.keys() == {"v1", "v2"}
    assert result["v1"] != result["v2"]
    assert kms.get_pii_hash_version() == 2


def test_verify_pii_hash_prefers_v2_but_keeps_v1_history(select_keys: Any) -> None:
    select = select_keys
    select(KEYRING_PII_KEY_V2="test-pii-hmac-v2")
    hashes = kms.compute_pii_hash_dual("subject@example.com")

    assert kms.verify_pii_hash("subject@example.com", hashes["v2"])
    assert kms.verify_pii_hash("subject@example.com", hashes["v1"])
    assert not kms.verify_pii_hash("other@example.com", hashes["v1"])


def test_verify_pii_hash_v2_error_falls_back_without_material_in_warning(
    select_keys: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    select = select_keys
    select(KEYRING_PII_KEY_V2="test-pii-hmac-v2")
    value = "subject@example.com"
    historical_hash = kms.compute_pii_hash(value)
    original = kms._hmac_hex

    def fail_v2(key_id: str, message: bytes, purpose: str) -> str:
        if key_id == "test-pii-hmac-v2":
            raise KeyringAuthError("test authentication failure")
        return original(key_id, message, purpose)  # type: ignore[arg-type]

    monkeypatch.setattr(kms, "_hmac_hex", fail_v2)
    with caplog.at_level(logging.WARNING, logger="echoroo.core.kms"):
        assert kms.verify_pii_hash(value, historical_hash)

    assert "KeyringAuthError" in caplog.text
    assert value not in caplog.text
    assert "test-pii-hmac-v2" not in caplog.text


def test_compute_audit_chain_hash_matches_known_answer() -> None:
    previous = "0" * 64
    row = b"canonical-row"
    expected = hmac.new(
        _key_material("test-audit-hmac"), previous.encode("ascii") + row, hashlib.sha256
    ).hexdigest()

    assert kms.compute_audit_chain_hash(previous, row) == expected
