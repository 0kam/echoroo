"""Codex supplement: DEK rewrap + KMS isolation (T979e, FR-091b).

Verifies two related cryptographic isolation properties:

A. KMS isolation:
   - Only ``apps/api/echoroo/core/kms.py`` is permitted to call
     ``boto3.client('kms', ...)`` or ``boto3.resource('kms', ...)``.
   - The enforcement is validated by running ``scripts/lint_kms_isolation.py``
     over the live codebase and asserting it reports zero violations.
   - If the script is absent from the repository, the test is marked xfail.

B. DEK rewrap — roundtrip integrity (moto):
   - ``kms.wrap_dek(plaintext)`` → ``kms.unwrap_dek(ciphertext)`` returns
     the original plaintext unchanged.
   - The wrapped ciphertext is not equal to the plaintext (i.e. it is
     actually encrypted, not stored verbatim).
   - Wrapping the same plaintext twice produces different ciphertexts
     (randomised IV / ciphertext uniqueness property).
   - Decrypting a tampered ciphertext raises a ``ClientError``.

C. DEK rewrap script:
   - ``scripts/rewrap_dek.py`` presence is documented; if absent the test
     is marked xfail to record the missing runbook artefact.

D. PII hash roundtrip (moto):
   - ``kms.compute_pii_hash(value)`` returns a stable hex string for the
     same input and the same key.
   - Different inputs produce different hashes.
   - The hash is 64 hexadecimal characters (32-byte HMAC-SHA256 as hex).

Shim: NOT applicable — all tests are pure service-layer / KMS tests with
no HTTP surface. No JWT auth is required.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AWS_REGION = "us-east-1"

# Unique alias prefixes to avoid collisions with other moto-based test modules.
_TOTP_DEK_ALIAS = "alias/echoroo-t979e-totp-dek"
_PII_HASH_ALIAS = "alias/echoroo-t979e-pii-hash"
_AUDIT_CHAIN_ALIAS = "alias/echoroo-t979e-audit-chain"
_INVITATION_ALIAS = "alias/echoroo-t979e-invitation-hmac"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_enc_key(kms_client: Any, alias: str) -> str:
    """Create a SYMMETRIC_DEFAULT CMK and attach an alias."""
    resp = kms_client.create_key(
        KeyUsage="ENCRYPT_DECRYPT", KeySpec="SYMMETRIC_DEFAULT"
    )
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return str(key_id)


def _create_hmac_key(kms_client: Any, alias: str) -> str:
    """Create an HMAC_256 CMK and attach an alias."""
    resp = kms_client.create_key(KeyUsage="GENERATE_VERIFY_MAC", KeySpec="HMAC_256")
    key_id = resp["KeyMetadata"]["KeyId"]
    kms_client.create_alias(AliasName=alias, TargetKeyId=key_id)
    return str(key_id)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def kms_env_t979e(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[dict[str, str]]:
    """Provision moto KMS with the four CMKs required by echoroo.core.kms.

    Yields a mapping of role → KeyId for diagnostic assertions.
    """
    monkeypatch.delenv("AWS_KMS_ENDPOINT", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL_KMS", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)

    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setenv("AWS_DEFAULT_REGION", AWS_REGION)

        kms = boto3.client("kms", region_name=AWS_REGION)
        totp_id = _create_enc_key(kms, _TOTP_DEK_ALIAS)
        pii_id = _create_hmac_key(kms, _PII_HASH_ALIAS)
        audit_id = _create_hmac_key(kms, _AUDIT_CHAIN_ALIAS)
        inv_id = _create_hmac_key(kms, _INVITATION_ALIAS)

        monkeypatch.setenv("AWS_KMS_REGION", AWS_REGION)
        monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", _TOTP_DEK_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_PII_HASH_ALIAS", _PII_HASH_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", _AUDIT_CHAIN_ALIAS)
        monkeypatch.setenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW", _INVITATION_ALIAS)
        monkeypatch.delenv("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD", raising=False)

        import echoroo.core.kms as kms_module

        importlib.reload(kms_module)

        yield {
            "totp_id": totp_id,
            "pii_id": pii_id,
            "audit_id": audit_id,
            "inv_id": inv_id,
        }


# ---------------------------------------------------------------------------
# Section A: KMS isolation lint
# ---------------------------------------------------------------------------


def test_kms_isolation_no_direct_boto3_kms_outside_wrapper() -> None:
    """No module outside ``echoroo/core/kms.py`` calls ``boto3.client('kms', ...)``.

    Runs ``scripts/lint_kms_isolation.py`` (AST-based static analysis) over
    the live ``apps/api/echoroo/`` tree and asserts zero violations.

    This test enforces FR-091b: all KMS access MUST route through the
    central wrapper so key rotation, DEK envelope encryption, and audit
    logging remain centralised.

    If the lint script is absent (e.g. a worktree without the scripts/
    directory), the test is skipped with an informational message rather
    than failing — the script's absence in a worktree is not itself a
    security violation.
    """
    # The lint script lives in {repo_root}/scripts/. We search upward from the
    # test file for a directory that contains scripts/lint_kms_isolation.py.
    # This handles both the host layout (apps/api/tests/security/crypto → 5
    # levels up) and the container layout (/app/tests/security/crypto → 3
    # levels up to /app). IndexError is caught when we reach the filesystem
    # root before finding the scripts directory.
    #
    # Phase 17 A-8: respect ``REPO_ROOT`` env if set so CI / containers
    # that mount the test tree without a sibling ``scripts/`` directory
    # can still resolve the lint script (the security-tests CI job sets
    # REPO_ROOT=${{ github.workspace }}).
    import os as _os

    this_file = Path(__file__).resolve()
    lint_script: Path | None = None
    repo_root = this_file.parent

    env_root = _os.environ.get("REPO_ROOT")
    if env_root:
        # Codex Round 1 R1-M1: when REPO_ROOT is explicitly set (CI /
        # container), a missing lint script is a hard failure — never a
        # silent skip. If the operator wired REPO_ROOT they expect the
        # security gate to actually run; falling through to skip would
        # bypass FR-091b enforcement in CI.
        repo_root = Path(env_root)
        candidate = repo_root / "scripts" / "lint_kms_isolation.py"
        assert candidate.exists(), (
            f"lint_kms_isolation.py not found at {candidate}. "
            "REPO_ROOT is set but the script is missing — CI must mount "
            "the repository scripts/ directory so this security gate can run."
        )
        lint_script = candidate
    else:
        # Local fallback: ancestor search, skip if nothing found so the
        # test remains usable from arbitrary worktrees that lack scripts/.
        for n in range(1, 10):
            try:
                candidate_root = this_file.parents[n]
            except IndexError:
                break
            candidate = candidate_root / "scripts" / "lint_kms_isolation.py"
            if candidate.exists():
                repo_root = candidate_root
                lint_script = candidate
                break
        if lint_script is None or not lint_script.exists():
            pytest.skip(
                "lint_kms_isolation.py not found in any ancestor directory "
                "and REPO_ROOT is not set — skipping (set REPO_ROOT to enforce)."
            )

    # Find the echoroo source root — may be at apps/api/echoroo (host) or
    # echoroo (container where /app is the api root).
    echoroo_root = repo_root / "apps" / "api" / "echoroo"
    if not echoroo_root.exists():
        echoroo_root = repo_root / "echoroo"
    if not echoroo_root.exists():
        pytest.skip(f"echoroo source root not found under {repo_root} — skipping")

    # Import the lint module by inserting the scripts/ parent into sys.path.
    scripts_dir = str(lint_script.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    try:
        import lint_kms_isolation as lint_mod
    except ImportError as exc:
        pytest.skip(f"Could not import lint_kms_isolation: {exc}")

    violations = lint_mod.find_violations(echoroo_root, repo_root=repo_root)

    assert not violations, (
        f"KMS isolation violated — {len(violations)} module(s) call "
        "boto3.client('kms') outside echoroo/core/kms.py:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Section B: DEK wrap/unwrap roundtrip
# ---------------------------------------------------------------------------


def test_dek_wrap_unwrap_roundtrip(kms_env_t979e: dict[str, str]) -> None:
    """``wrap_dek`` → ``unwrap_dek`` recovers the original plaintext.

    The DEK envelope encryption contract (FR-051): wrapping a 32-byte key
    with the TOTP CMK and then decrypting must yield the original bytes.
    """
    from echoroo.core import kms

    plaintext = b"\x42" * 32  # 32 bytes: AES-256-GCM key size
    wrapped = kms.wrap_dek(plaintext)
    recovered = kms.unwrap_dek(wrapped)

    assert recovered == plaintext, (
        "DEK roundtrip failed: unwrap_dek did not return the original plaintext"
    )


def test_dek_wrapped_ciphertext_differs_from_plaintext(
    kms_env_t979e: dict[str, str],
) -> None:
    """The KMS ciphertext blob must not be equal to the plaintext.

    This test documents the obvious but critical property that ``wrap_dek``
    actually encrypts the DEK rather than returning it verbatim.
    """
    from echoroo.core import kms

    plaintext = b"\xDE\xAD\xBE\xEF" * 8  # 32 bytes
    wrapped = kms.wrap_dek(plaintext)

    assert wrapped != plaintext, (
        "wrap_dek returned the plaintext unchanged — encryption did not occur"
    )


def test_dek_wrap_ciphertext_uniqueness(kms_env_t979e: dict[str, str]) -> None:
    """Wrapping the same plaintext twice produces different ciphertexts.

    AWS KMS SYMMETRIC_DEFAULT encryption uses a randomised IV, so each
    ``Encrypt`` call must produce a distinct ciphertext even for the same
    plaintext and key. This property ensures that ciphertext comparison
    cannot leak information about equality of plaintexts.
    """
    from echoroo.core import kms

    plaintext = b"\x99" * 32
    wrapped_a = kms.wrap_dek(plaintext)
    wrapped_b = kms.wrap_dek(plaintext)

    assert wrapped_a != wrapped_b, (
        "wrap_dek produced identical ciphertexts for the same plaintext — "
        "IV randomisation may be broken"
    )


def test_dek_unwrap_tampered_ciphertext_raises(
    kms_env_t979e: dict[str, str],
) -> None:
    """Decrypting a tampered ciphertext raises a ``ClientError``.

    AWS KMS authenticates ciphertext integrity; a single-byte flip in the
    ciphertext blob must be rejected with a ``ClientError``. This validates
    that ciphertext integrity protection is active.
    """
    import botocore.exceptions

    from echoroo.core import kms

    plaintext = b"\x11" * 32
    wrapped = kms.wrap_dek(plaintext)

    # Flip the first byte of the ciphertext to produce a tampered blob.
    tampered = bytes([wrapped[0] ^ 0xFF]) + wrapped[1:]

    with pytest.raises(botocore.exceptions.ClientError):
        kms.unwrap_dek(tampered)


# ---------------------------------------------------------------------------
# Section B': DEK rewrap roundtrip (Phase 17 A-8)
# ---------------------------------------------------------------------------


_DESTINATION_DEK_ALIAS = "alias/echoroo-t979e-totp-dek-v2"


def test_dek_rewrap_roundtrip_with_new_cmk(
    monkeypatch: pytest.MonkeyPatch,
    kms_env_t979e: dict[str, str],
) -> None:
    """``rewrap_dek`` produces ciphertext decryptable under the new CMK.

    Provisions a SECOND symmetric CMK on the moto KMS, calls
    :func:`kms.rewrap_dek` with that destination, then re-points the
    TOTP alias env var at the new CMK and asserts that
    :func:`kms.unwrap_dek` recovers the original plaintext. This proves
    the FR-091b property that the plaintext DEK survives rewrap
    intact even though it is never exposed to the application.
    """
    from echoroo.core import kms

    # Provision a destination CMK via the boto3 client moto already
    # exposes through the fixture's ``mock_aws()`` context.
    boto_kms = boto3.client("kms", region_name=AWS_REGION)
    dest_id = _create_enc_key(boto_kms, _DESTINATION_DEK_ALIAS)

    plaintext = b"\x77" * 32
    wrapped_old = kms.wrap_dek(plaintext)
    wrapped_new = kms.rewrap_dek(wrapped_old, destination_key_id=dest_id)

    assert wrapped_new != wrapped_old, (
        "rewrap_dek returned the input ciphertext unchanged — re-encrypt "
        "did not occur"
    )

    # Re-point the TOTP alias env var at the destination CMK and reset
    # the cached client / alias resolution so unwrap routes to the
    # destination key.
    monkeypatch.setenv("AWS_KMS_CMK_2FA_ALIAS", _DESTINATION_DEK_ALIAS)
    kms._reset_client_cache()

    recovered = kms.unwrap_dek(wrapped_new)
    assert recovered == plaintext, (
        "rewrap_dek roundtrip failed: unwrap under destination CMK did "
        "not return the original plaintext"
    )


def test_dek_rewrap_with_explicit_source_key_id(
    kms_env_t979e: dict[str, str],
) -> None:
    """``rewrap_dek`` honours an explicit ``source_key_id`` hint.

    AWS KMS ``ReEncrypt`` accepts an optional ``SourceKeyId`` parameter;
    moto resolves it against the ciphertext metadata. Passing the
    source CMK explicitly must produce the same plaintext as omitting
    it (the auto-resolve path).
    """
    from echoroo.core import kms

    boto_kms = boto3.client("kms", region_name=AWS_REGION)
    dest_alias = "alias/echoroo-t979e-totp-dek-v3"
    dest_id = _create_enc_key(boto_kms, dest_alias)

    plaintext = b"\x33" * 32
    wrapped_old = kms.wrap_dek(plaintext)

    wrapped_new = kms.rewrap_dek(
        wrapped_old,
        destination_key_id=dest_id,
        source_key_id=kms_env_t979e["totp_id"],
    )
    # Decrypt with the destination CMK directly through the boto3 client
    # to avoid coupling this assertion to env-var alias routing.
    resp = boto_kms.decrypt(CiphertextBlob=wrapped_new, KeyId=dest_id)
    assert resp["Plaintext"] == plaintext


def test_dek_rewrap_does_not_expose_plaintext_in_response(
    kms_env_t979e: dict[str, str],
) -> None:
    """``rewrap_dek`` returns ONLY the new ciphertext blob.

    The whole point of ``kms:ReEncrypt`` is that the plaintext stays
    inside KMS. Asserting the return value is opaque ciphertext (and
    not a tuple / dict containing ``Plaintext``) documents the contract
    enforced by ``echoroo.core.kms.rewrap_dek``.
    """
    from echoroo.core import kms

    boto_kms = boto3.client("kms", region_name=AWS_REGION)
    dest_id = _create_enc_key(boto_kms, "alias/echoroo-t979e-totp-dek-v4")

    plaintext = b"\xAB" * 32
    wrapped_old = kms.wrap_dek(plaintext)
    out = kms.rewrap_dek(wrapped_old, destination_key_id=dest_id)

    assert isinstance(out, bytes), "rewrap_dek must return raw bytes"
    # The plaintext must not be byte-substring of the returned ciphertext —
    # this is statistically near-impossible for an authenticated
    # encryption blob, but documents the no-leakage invariant.
    assert plaintext not in out, (
        "rewrap_dek leaked plaintext-looking bytes into the ciphertext "
        "blob — KMS contract violated"
    )


# ---------------------------------------------------------------------------
# Section C: DEK rewrap script
# ---------------------------------------------------------------------------


def test_dek_rewrap_script_exists() -> None:
    """``scripts/rewrap_dek.py`` exists as a runbook artefact (Phase 17 A-8).

    The rewrap script is needed to re-encrypt all stored TOTP DEKs after a
    CMK rotation. Without it, operators cannot complete a CMK rotation
    without downtime. The script is the runtime companion to
    ``docs/runbook/dek_rewrap.md`` and uses the new
    :func:`echoroo.core.kms.rewrap_dek` wrapper (which calls
    ``kms:ReEncrypt`` so the plaintext DEK never leaves KMS).
    """
    # Search upward from the test file for the repo root containing
    # ``scripts/rewrap_dek.py``. Both host (apps/api/tests/...) and
    # container (/app/tests/...) layouts are supported; an explicit
    # ``REPO_ROOT`` env var overrides the search for CI runners that
    # mount the test tree without sibling ``scripts/`` directory.
    import os as _os

    env_root = _os.environ.get("REPO_ROOT")
    if env_root:
        candidates = [Path(env_root) / "scripts" / "rewrap_dek.py"]
    else:
        this_file = Path(__file__).resolve()
        candidates = []
        for n in range(1, 10):
            try:
                root = this_file.parents[n]
            except IndexError:
                break
            candidates.append(root / "scripts" / "rewrap_dek.py")

    found = next((p for p in candidates if p.exists()), None)
    assert found is not None, (
        "rewrap_dek.py not found in any ancestor scripts/ directory "
        f"(searched: {[str(p) for p in candidates]}). "
        "Create the script as part of the CMK rotation runbook or set "
        "REPO_ROOT to point at the repository root."
    )


# ---------------------------------------------------------------------------
# Section D: PII hash stability and uniqueness
# ---------------------------------------------------------------------------


def test_pii_hash_is_stable_for_same_input(kms_env_t979e: dict[str, str]) -> None:
    """``compute_pii_hash`` is deterministic: same input → same hash.

    The PII hash (keyed HMAC-SHA256) must be stable so that audit rows
    written at different times can be joined by the hash value. If the
    output were random, historical audit log searches would break.
    """
    from echoroo.core import kms

    value = "stable-pii-test@example.com"
    hash_a = kms.compute_pii_hash(value)
    hash_b = kms.compute_pii_hash(value)

    assert hash_a == hash_b, (
        "compute_pii_hash returned different values for the same input — "
        "HMAC is not deterministic"
    )


def test_pii_hash_differs_for_different_inputs(
    kms_env_t979e: dict[str, str],
) -> None:
    """``compute_pii_hash`` returns different values for different inputs.

    A keyed HMAC must not produce hash collisions for any pair of distinct
    inputs (with overwhelming probability). Testing two concrete values
    documents the expected uniqueness property.
    """
    from echoroo.core import kms

    hash_a = kms.compute_pii_hash("alice@example.com")
    hash_b = kms.compute_pii_hash("bob@example.com")

    assert hash_a != hash_b, (
        "compute_pii_hash returned the same hash for different inputs — "
        "HMAC key or algorithm may be broken"
    )


def test_pii_hash_output_is_64_hex_chars(kms_env_t979e: dict[str, str]) -> None:
    """``compute_pii_hash`` output is 64 lowercase hex characters.

    The function documents its output as a 64-character lowercase hex string
    (32-byte HMAC-SHA256 serialised as hex). This test validates the wire
    format so callers can rely on the fixed-length output for storage.
    """
    from echoroo.core import kms

    result = kms.compute_pii_hash("format-test@example.com")

    assert len(result) == 64, (
        f"Expected 64-char hex string, got length {len(result)}: {result!r}"
    )
    assert result == result.lower(), (
        f"Expected lowercase hex, got: {result!r}"
    )
    # Verify every character is a valid hex digit.
    int(result, 16)  # raises ValueError if not valid hex


__all__ = [
    "test_dek_rewrap_script_exists",
    "test_dek_unwrap_tampered_ciphertext_raises",
    "test_dek_wrap_ciphertext_uniqueness",
    "test_dek_wrap_unwrap_roundtrip",
    "test_dek_wrapped_ciphertext_differs_from_plaintext",
    "test_kms_isolation_no_direct_boto3_kms_outside_wrapper",
    "test_pii_hash_differs_for_different_inputs",
    "test_pii_hash_is_stable_for_same_input",
    "test_pii_hash_output_is_64_hex_chars",
]
