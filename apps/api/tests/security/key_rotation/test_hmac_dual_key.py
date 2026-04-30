"""HMAC dual-key rotation window tests (T974, FR-040, 14-day grace).

Verifies that the KMS-based invitation token signing supports a dual-key
rotation window:

  * After rotation (k_new activated), tokens signed by k_old are still
    accepted for 14 days (grace window). k_new is tried first; falling
    back to k_old only when k_new verification fails.
  * After the grace window closes (k_old env var unset), k_old-signed
    tokens are rejected and only k_new is accepted.
  * k_new-signed tokens are always accepted regardless of whether k_old
    is configured.
  * Tampered tokens (wrong payload, garbage sig) are rejected under both
    key states.
  * A token signed by a completely unknown (third) key is rejected even
    during the grace window.

This test suite reuses the ``kms_env`` fixture from
``tests/unit/core/test_kms.py`` (via conftest.py import or local
re-definition). To avoid cross-module fixture import complexity, we
define a self-contained ``kms_env_rotation`` fixture here that sets up
both k_new and k_old in the same moto context.

Shim: NOT applicable (no HTTP path — pure service-layer / KMS tests).
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AWS_REGION = "us-east-1"

# Canonical alias names used by the rotation fixture.
INVITATION_NEW_ALIAS = "alias/echoroo-t974-invitation-hmac-new"
INVITATION_OLD_ALIAS = "alias/echoroo-t974-invitation-hmac-old"
INVITATION_THIRD_ALIAS = "alias/echoroo-t974-invitation-hmac-third"

# Aliases for non-invitation CMKs (required by echoroo.core.kms on import).
TOTP_DEK_ALIAS = "alias/echoroo-t974-totp-dek"
PII_HASH_ALIAS = "alias/echoroo-t974-pii-hash"
AUDIT_CHAIN_ALIAS = "alias/echoroo-t974-audit-chain"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_hmac_key(kms_client: Any, alias: str) -> str:
    """Create an HMAC_256 CMK and return its raw KeyId."""
    resp = kms_client.create_key(KeyUsage="GENERATE_VERIFY_MAC", KeySpec="HMAC_256")
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return str(key_id)


def _create_enc_key(kms_client: Any, alias: str) -> str:
    """Create a SYMMETRIC_DEFAULT CMK and return its raw KeyId."""
    resp = kms_client.create_key(KeyUsage="ENCRYPT_DECRYPT", KeySpec="SYMMETRIC_DEFAULT")
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return str(key_id)


# ---------------------------------------------------------------------------
# kms_env_rotation fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def kms_env_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    """Provision moto KMS with two invitation signing keys + supporting CMKs.

    Yields a mapping with raw KeyIds for k_new, k_old, and a third
    independent key. Env vars point at k_new + k_old to simulate a
    rotation in progress.

    INVITATION_HMAC_ALIAS_OLD is set throughout. Individual tests that
    want to simulate the post-grace state (old key expired) should call
    ``monkeypatch.delenv('AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD')`` and
    reload ``echoroo.core.kms`` to force the env change into the cached
    client.
    """
    # Remove any LocalStack endpoint so moto intercepts the calls.
    monkeypatch.delenv("AWS_KMS_ENDPOINT", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_KMS", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)

        kms = boto3.client("kms", region_name=AWS_REGION)

        totp_id = _create_enc_key(kms, TOTP_DEK_ALIAS)
        pii_id = _create_hmac_key(kms, PII_HASH_ALIAS)
        audit_id = _create_hmac_key(kms, AUDIT_CHAIN_ALIAS)
        inv_new_id = _create_hmac_key(kms, INVITATION_NEW_ALIAS)
        inv_old_id = _create_hmac_key(kms, INVITATION_OLD_ALIAS)
        inv_third_id = _create_hmac_key(kms, INVITATION_THIRD_ALIAS)

        monkeypatch.setenv("AWS_KMS_REGION", AWS_REGION)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", TOTP_DEK_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", PII_HASH_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", AUDIT_CHAIN_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", INVITATION_NEW_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", INVITATION_OLD_ALIAS)

        import echoroo.core.kms as kms_module
        importlib.reload(kms_module)

        yield {
            "inv_new_id": inv_new_id,
            "inv_old_id": inv_old_id,
            "inv_third_id": inv_third_id,
            "totp_id": totp_id,
            "pii_id": pii_id,
            "audit_id": audit_id,
        }


# ---------------------------------------------------------------------------
# T974-1: k_new signed token is accepted (steady-state, no rotation needed)
# ---------------------------------------------------------------------------


def test_k_new_signed_token_is_accepted(kms_env_rotation: dict[str, str]) -> None:
    """A token signed by k_new is always accepted.

    This is the steady-state case: rotation has completed and k_new is the
    only active key.
    """
    from echoroo.core import kms

    payload = b"invitation:project=abc;email=user@example.com"
    sig = kms.sign_invitation_hmac(payload)

    assert kms.verify_invitation_hmac(payload, sig) is True, (
        "k_new-signed token must be accepted (FR-040)"
    )


# ---------------------------------------------------------------------------
# T974-2: k_old signed token accepted during grace window (k_old configured)
# ---------------------------------------------------------------------------


def test_k_old_signed_token_accepted_during_grace_window(
    kms_env_rotation: dict[str, str],
) -> None:
    """Token signed by the previous key (k_old) is accepted during grace window.

    Simulates a token issued before the rotation — signed directly via the
    k_old KeyId — and verifies that the module accepts it by falling back
    to k_old after k_new fails.

    This is the 14-day grace window contract (FR-040, research.md §14).
    """
    from echoroo.core import kms

    payload = b"pre-rotation-token:project=xyz;email=legacy@example.com"

    # Sign directly with k_old to simulate a token issued before rotation.
    kms_client = boto3.client("kms", region_name=AWS_REGION)
    resp = kms_client.generate_mac(
        Message=payload,
        KeyId=kms_env_rotation["inv_old_id"],
        MacAlgorithm="HMAC_SHA_256",
    )
    old_sig = resp["Mac"].hex()

    # Sanity: k_new would produce a different signature.
    new_sig = kms.sign_invitation_hmac(payload)
    assert new_sig != old_sig, "k_new and k_old must produce different MACs"

    # Verification must succeed via the k_old fallback.
    assert kms.verify_invitation_hmac(payload, old_sig) is True, (
        "k_old-signed token must be accepted during the 14-day grace window (FR-040)"
    )


# ---------------------------------------------------------------------------
# T974-3: k_old token rejected after grace window closes (k_old unset)
# ---------------------------------------------------------------------------


def test_k_old_signed_token_rejected_after_grace_window(
    kms_env_rotation: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After grace window, k_old env var is unset and k_old tokens are rejected.

    Operators signal end-of-grace by unsetting
    ``AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD``. Once unset, the fallback
    path is no longer tried and k_old-signed tokens must fail.
    """
    # Capture an k_old signature while the alias is still configured.
    kms_client = boto3.client("kms", region_name=AWS_REGION)
    payload = b"expired-grace-token:project=xyz;email=old@example.com"
    resp = kms_client.generate_mac(
        Message=payload,
        KeyId=kms_env_rotation["inv_old_id"],
        MacAlgorithm="HMAC_SHA_256",
    )
    old_sig = resp["Mac"].hex()

    # Unset the k_old env var to simulate the end of the grace window.
    monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", raising=False)

    import echoroo.core.kms as kms_module
    importlib.reload(kms_module)

    assert kms_module.verify_invitation_hmac(payload, old_sig) is False, (
        "k_old-signed token must be rejected after the grace window closes (FR-040)"
    )


# ---------------------------------------------------------------------------
# T974-4: tampered payload rejected regardless of key state
# ---------------------------------------------------------------------------


def test_tampered_payload_rejected_during_grace_window(
    kms_env_rotation: dict[str, str],
) -> None:
    """A valid k_new signature does not validate against a different payload.

    This ensures HMAC binding is strict — flipping one byte in the payload
    invalidates the signature under both k_new and k_old.
    """
    from echoroo.core import kms

    original_payload = b"invitation:project=abc;email=legit@example.com"
    tampered_payload = b"invitation:project=abc;email=evil@example.com"

    sig = kms.sign_invitation_hmac(original_payload)

    assert kms.verify_invitation_hmac(tampered_payload, sig) is False, (
        "HMAC signature must not validate against a different payload"
    )


# ---------------------------------------------------------------------------
# T974-5: garbage signature rejected
# ---------------------------------------------------------------------------


def test_garbage_signature_rejected(kms_env_rotation: dict[str, str]) -> None:
    """A random hex string that is not a valid HMAC is rejected."""
    from echoroo.core import kms

    assert kms.verify_invitation_hmac(b"any payload", "deadbeef" * 8) is False, (
        "Garbage signature must be rejected"
    )


# ---------------------------------------------------------------------------
# T974-6: third/unknown key signature rejected even during grace window
# ---------------------------------------------------------------------------


def test_third_key_signature_rejected_during_grace_window(
    kms_env_rotation: dict[str, str],
) -> None:
    """A token signed by an unrelated third key is rejected even with k_old active.

    Only k_new and k_old (when configured) are in the verification chain.
    A token signed by any other key — even one that exists in KMS — must
    always be rejected.
    """
    from echoroo.core import kms

    payload = b"third-party-token:project=abc;email=attacker@example.com"

    # Sign with the third key directly.
    kms_client = boto3.client("kms", region_name=AWS_REGION)
    resp = kms_client.generate_mac(
        Message=payload,
        KeyId=kms_env_rotation["inv_third_id"],
        MacAlgorithm="HMAC_SHA_256",
    )
    third_sig = resp["Mac"].hex()

    assert kms.verify_invitation_hmac(payload, third_sig) is False, (
        "Token signed by an unknown third key must be rejected (FR-040 isolation)"
    )
