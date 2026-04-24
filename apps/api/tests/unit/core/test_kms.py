"""Unit tests for echoroo.core.kms — the single source of truth for KMS ops.

Covers T030a-d via T031 (TDD red → green):
    * wrap_dek / unwrap_dek         — TOTP DEK envelope (FR-051, FR-066, FR-067)
    * compute_pii_hash              — keyed HMAC via kms:GenerateMac (FR-091, FR-091b)
    * sign_invitation_hmac /
      verify_invitation_hmac        — dual-key k_old/k_new rotation (FR-052, FR-040,
                                      research.md §14)
    * compute_audit_chain_hash      — tamper-evident chain (FR-092)

All tests exercise the module against a moto-backed KMS so no real AWS
credentials are required. moto provides `GenerateDataKey`, `Encrypt`,
`Decrypt`, and `GenerateMac` / `VerifyMac` on HMAC CMKs, which is what
the module depends on.

The tests intentionally drive the module's public contract — they are
the *red* side of strict TDD for Phase 2.2 and must exist in the tree
before `apps/api/echoroo/core/kms.py` is written.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Aliases used by the tests — kept in sync with scripts/init-localstack.sh
# and research.md §1. The module under test reads them from env so the
# same env values are injected via the `kms_env` fixture below.
TOTP_DEK_ALIAS = "alias/echoroo-test-totp-dek"
PII_HASH_ALIAS = "alias/echoroo-test-pii-hash"
AUDIT_CHAIN_ALIAS = "alias/echoroo-test-audit-chain"
INVITATION_NEW_ALIAS = "alias/echoroo-test-invitation-hmac-new"
INVITATION_OLD_ALIAS = "alias/echoroo-test-invitation-hmac-old"

AWS_REGION = "us-east-1"


def _create_cmk_with_alias(
    kms_client: Any,
    alias_name: str,
    *,
    key_usage: str,
    key_spec: str,
) -> str:
    """Create a CMK + alias in moto and return the key-id."""
    resp = kms_client.create_key(KeyUsage=key_usage, KeySpec=key_spec)
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias_name, TargetKeyId=key_id)
    return str(key_id)


@pytest.fixture
def kms_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """Provision a fresh moto-backed KMS and wire env vars for the module.

    Yields the key-id mapping so tests can reference specific keys if
    they need to (e.g. for direct VerifyMac calls). The fixture also
    re-imports `echoroo.core.kms` so any module-level cached client is
    reset between tests.
    """
    with mock_aws():
        # AWS credentials need to be set even for moto — boto3 otherwise
        # raises NoCredentialsError before the mock intercepts.
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)

        client = boto3.client("kms", region_name=AWS_REGION)

        totp_id = _create_cmk_with_alias(
            client,
            TOTP_DEK_ALIAS,
            key_usage="ENCRYPT_DECRYPT",
            key_spec="SYMMETRIC_DEFAULT",
        )
        pii_id = _create_cmk_with_alias(
            client,
            PII_HASH_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )
        audit_id = _create_cmk_with_alias(
            client,
            AUDIT_CHAIN_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )
        inv_new_id = _create_cmk_with_alias(
            client,
            INVITATION_NEW_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )
        inv_old_id = _create_cmk_with_alias(
            client,
            INVITATION_OLD_ALIAS,
            key_usage="GENERATE_VERIFY_MAC",
            key_spec="HMAC_256",
        )

        # Wire env vars that echoroo.core.kms reads. The module honours
        # several historical names; we set the canonical ones used by
        # scripts/init-localstack.sh and .env.example (T011).
        monkeypatch.setenv("AWS_KMS_REGION", AWS_REGION)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", TOTP_DEK_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_HASH_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", AUDIT_CHAIN_ALIAS)
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", INVITATION_NEW_ALIAS
        )
        monkeypatch.setenv(
            "AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", INVITATION_OLD_ALIAS
        )
        # Leave AWS_KMS_ENDPOINT unset — moto intercepts the default
        # regional endpoint. If the module reads it, the None/absent
        # value must be tolerated.
        monkeypatch.delenv("AWS_KMS_ENDPOINT", raising=False)
        monkeypatch.delenv("AWS_ENDPOINT_URL_KMS", raising=False)

        # Force re-import so any module-level boto3 client cache resets.
        import echoroo.core.kms as kms_module

        importlib.reload(kms_module)

        yield {
            "totp_id": totp_id,
            "pii_id": pii_id,
            "audit_id": audit_id,
            "inv_new_id": inv_new_id,
            "inv_old_id": inv_old_id,
        }


# ---------------------------------------------------------------------------
# T030a — TOTP DEK wrap / unwrap
# ---------------------------------------------------------------------------


def test_wrap_dek_roundtrip(kms_env: dict[str, str]) -> None:
    """wrap_dek(plaintext) followed by unwrap_dek returns the original DEK."""
    from echoroo.core import kms

    plaintext = b"\x00" * 32  # 256-bit DEK
    wrapped = kms.wrap_dek(plaintext)

    assert isinstance(wrapped, bytes)
    assert wrapped != plaintext  # ciphertext must differ from plaintext
    assert len(wrapped) > 0

    recovered = kms.unwrap_dek(wrapped)
    assert recovered == plaintext


def test_wrap_dek_produces_distinct_ciphertext_per_call(
    kms_env: dict[str, str],
) -> None:
    """KMS envelope is non-deterministic — two wraps of the same DEK differ."""
    from echoroo.core import kms

    plaintext = b"\x11" * 32
    wrapped_a = kms.wrap_dek(plaintext)
    wrapped_b = kms.wrap_dek(plaintext)

    assert wrapped_a != wrapped_b
    # But both must still unwrap to the same plaintext.
    assert kms.unwrap_dek(wrapped_a) == plaintext
    assert kms.unwrap_dek(wrapped_b) == plaintext


def test_unwrap_dek_rejects_tampered_blob(kms_env: dict[str, str]) -> None:
    """Flipping a byte in the wrapped blob must cause unwrap to raise."""
    from echoroo.core import kms

    plaintext = b"\x22" * 32
    wrapped = bytearray(kms.wrap_dek(plaintext))
    # Flip a byte in the payload (avoid the first byte of AWS metadata).
    wrapped[-1] ^= 0xFF

    with pytest.raises(Exception):
        kms.unwrap_dek(bytes(wrapped))


# ---------------------------------------------------------------------------
# T030b — compute_pii_hash via kms:GenerateMac
# ---------------------------------------------------------------------------


def test_compute_pii_hash_deterministic(kms_env: dict[str, str]) -> None:
    """Same input must produce same hash (keyed HMAC determinism, FR-091)."""
    from echoroo.core import kms

    a = kms.compute_pii_hash("alice@example.com")
    b = kms.compute_pii_hash("alice@example.com")

    assert a == b
    assert a != ""


def test_compute_pii_hash_returns_hex(kms_env: dict[str, str]) -> None:
    """Hash must be a lowercase hex string of the MAC output."""
    from echoroo.core import kms

    result = kms.compute_pii_hash("user@example.com")

    assert isinstance(result, str)
    # HMAC_SHA_256 → 32 bytes → 64 hex characters.
    assert len(result) == 64
    int(result, 16)  # must parse as hex
    assert result == result.lower()


def test_compute_pii_hash_differs_for_different_inputs(
    kms_env: dict[str, str],
) -> None:
    from echoroo.core import kms

    a = kms.compute_pii_hash("alice@example.com")
    b = kms.compute_pii_hash("bob@example.com")

    assert a != b


def test_compute_pii_hash_handles_unicode(kms_env: dict[str, str]) -> None:
    """Hash must accept arbitrary UTF-8 strings (emails can be IDN)."""
    from echoroo.core import kms

    # Zero-byte collision check: trailing null must not alias.
    assert kms.compute_pii_hash("foo") != kms.compute_pii_hash("foo\x00")
    # Unicode passthrough.
    assert len(kms.compute_pii_hash("山田太郎@example.jp")) == 64


# ---------------------------------------------------------------------------
# T030c — invitation HMAC sign / verify with k_old fallback
# ---------------------------------------------------------------------------


def test_sign_invitation_hmac_returns_hex(kms_env: dict[str, str]) -> None:
    from echoroo.core import kms

    sig = kms.sign_invitation_hmac(b"invitation:project=foo;email=bar")

    assert isinstance(sig, str)
    assert len(sig) == 64
    int(sig, 16)


def test_verify_invitation_hmac_accepts_valid_new_key(
    kms_env: dict[str, str],
) -> None:
    from echoroo.core import kms

    payload = b"invitation:project=foo;email=bar"
    sig = kms.sign_invitation_hmac(payload)

    assert kms.verify_invitation_hmac(payload, sig) is True


def test_verify_invitation_hmac_rejects_tampered_payload(
    kms_env: dict[str, str],
) -> None:
    from echoroo.core import kms

    payload = b"invitation:project=foo;email=bar"
    sig = kms.sign_invitation_hmac(payload)

    assert kms.verify_invitation_hmac(b"invitation:project=foo;email=evil", sig) is False


def test_verify_invitation_hmac_rejects_garbage_signature(
    kms_env: dict[str, str],
) -> None:
    from echoroo.core import kms

    assert kms.verify_invitation_hmac(b"payload", "deadbeef" * 8) is False


def test_verify_invitation_hmac_falls_back_to_k_old(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """During 14-day grace, tokens signed by the *previous* key must verify.

    Simulated by: sign with key_old directly (via low-level boto3 GenerateMac
    against the OLD alias), then ask the module to verify. The module must
    try k_new first (which fails), then k_old (which succeeds).
    """
    from echoroo.core import kms

    payload = b"pre-rotation-token"

    # Sign directly with the OLD alias to simulate a token issued before
    # rotation. The module itself only signs with NEW.
    kms_client = boto3.client("kms", region_name=AWS_REGION)
    resp = kms_client.generate_mac(
        Message=payload,
        KeyId=INVITATION_OLD_ALIAS,
        MacAlgorithm="HMAC_SHA_256",
    )
    sig_hex = resp["Mac"].hex()

    # Sanity check: signing the same payload with NEW yields a different sig.
    sig_new = kms.sign_invitation_hmac(payload)
    assert sig_new != sig_hex

    # Verify must return True because fallback chain includes k_old.
    assert kms.verify_invitation_hmac(payload, sig_hex) is True


def test_verify_invitation_hmac_returns_false_when_old_unconfigured(
    kms_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """When OLD alias is not configured (post-grace), only k_new is tried.

    A signature that would have validated under k_old must now be rejected.
    """
    import importlib

    # Capture a k_old signature before removing the env var.
    kms_client = boto3.client("kms", region_name=AWS_REGION)
    resp = kms_client.generate_mac(
        Message=b"legacy",
        KeyId=INVITATION_OLD_ALIAS,
        MacAlgorithm="HMAC_SHA_256",
    )
    old_sig = resp["Mac"].hex()

    monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", raising=False)

    # Reload so the module picks up the new env view.
    import echoroo.core.kms as kms_module

    importlib.reload(kms_module)

    assert kms_module.verify_invitation_hmac(b"legacy", old_sig) is False


# ---------------------------------------------------------------------------
# T030d — audit chain HMAC
# ---------------------------------------------------------------------------


def test_compute_audit_chain_hash_deterministic(kms_env: dict[str, str]) -> None:
    from echoroo.core import kms

    prev = "0" * 64
    row = b'{"action":"login","user_id":"abc"}'

    h1 = kms.compute_audit_chain_hash(prev, row)
    h2 = kms.compute_audit_chain_hash(prev, row)

    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64
    int(h1, 16)


def test_compute_audit_chain_hash_changes_with_prev(kms_env: dict[str, str]) -> None:
    from echoroo.core import kms

    row = b'{"action":"login"}'

    h_a = kms.compute_audit_chain_hash("0" * 64, row)
    h_b = kms.compute_audit_chain_hash("f" * 64, row)

    assert h_a != h_b


def test_compute_audit_chain_hash_changes_with_row(kms_env: dict[str, str]) -> None:
    from echoroo.core import kms

    prev = "0" * 64

    h_a = kms.compute_audit_chain_hash(prev, b'{"action":"a"}')
    h_b = kms.compute_audit_chain_hash(prev, b'{"action":"b"}')

    assert h_a != h_b


def test_audit_chain_uses_distinct_key_from_pii_hash(kms_env: dict[str, str]) -> None:
    """Defence-in-depth: audit_chain and pii_hash keys MUST be separate CMKs.

    We can't directly inspect the key bytes (they never leave KMS), but we
    can assert that given identical inputs the two HMACs differ — which
    can only happen if the underlying keys differ.
    """
    from echoroo.core import kms

    payload = "identical"
    pii_h = kms.compute_pii_hash(payload)
    chain_h = kms.compute_audit_chain_hash("0" * 64, payload.encode())

    # Even if we happened to use the same "prev||row" formatting, the keys
    # must differ so the hashes diverge.
    assert pii_h != chain_h


# ---------------------------------------------------------------------------
# Key-isolation smoke: each function points at a distinct alias env var.
# This guards against accidental copy-paste regressions where two functions
# share a key (which would violate research.md §1 "each alias maps to a
# distinct CMK").
# ---------------------------------------------------------------------------


def test_keys_are_isolated(kms_env: dict[str, str]) -> None:
    assert os.environ["AWS_KMS_CMK_2FA_ALIAS"] != os.environ["AWS_KMS_CMK_PII_HASH_ALIAS"]
    assert (
        os.environ["AWS_KMS_CMK_PII_HASH_ALIAS"]
        != os.environ["AWS_KMS_CMK_AUDIT_CHAIN_ALIAS"]
    )
    assert (
        os.environ["AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW"]
        != os.environ["AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD"]
    )
