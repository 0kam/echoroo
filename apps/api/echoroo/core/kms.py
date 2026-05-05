"""KMS wrapper — the single source of truth for all KMS operations.

This module is the only place in the application permitted to call
``boto3.client('kms', ...)``. Every other module must route through the
public functions exported here. Violations are detected by
``scripts/lint_kms_isolation.py`` (T032) and fail CI.

Functional scope (006 permissions redesign, Phase 2.2):

* ``wrap_dek`` / ``unwrap_dek``
    TOTP secret DEK envelope encryption against
    ``alias/echoroo-totp-dek`` (FR-051, FR-066, FR-067).

* ``compute_pii_hash``
    Keyed HMAC-SHA256 via ``kms:GenerateMac`` against
    ``alias/echoroo-pii-hash-hmac`` (FR-091, FR-091b). The raw key bytes
    never leave KMS — the application only ever sees the MAC output.

* ``sign_invitation_hmac`` / ``verify_invitation_hmac``
    Invitation token signing with dual-key k_new / k_old support for
    14-day rotation grace (FR-052, FR-040, research.md §14). New
    signatures are always produced with ``k_new``; verification tries
    ``k_new`` first, then falls back to ``k_old`` if configured.

* ``compute_audit_chain_hash``
    Audit log chain-hash via dedicated CMK
    ``alias/echoroo-audit-chain-hmac`` (FR-092).

Design notes:
* The boto3 KMS client is constructed lazily and cached at module level.
  Rotation of the client (after env var changes in tests) is handled by
  ``importlib.reload``.
* No key material is cached in the process — every call round-trips to
  KMS. This is cheap in production (KMS p99 ≈ 5 ms) and satisfies
  FR-091b (no in-process exposure of HMAC keys).
* ``kms:GenerateMac`` with ``HMAC_SHA_256`` produces a 32-byte MAC. We
  serialise as lowercase hex (64 chars) so it is safe to embed in JSON,
  URLs, and the existing ``row_hash`` VARCHAR(64) audit column.

Environment variables (canonical names — see .env.example §"006"):

    AWS_KMS_ENDPOINT                        LocalStack endpoint (dev).
    AWS_ENDPOINT_URL_KMS                    AWS SDK-standard alias for the above.
    AWS_KMS_REGION                          AWS region for all CMKs.
    AWS_KMS_CMK_2FA_ALIAS                   TOTP DEK wrapping CMK alias.
    AWS_KMS_CMK_PII_HASH_ALIAS              PII hashing CMK alias (v1).
    AWS_KMS_CMK_PII_HASH_ALIAS_V2           Optional v2 PII hashing CMK
                                             alias used during a dual-write
                                             rotation window (FR-091b).
                                             Unset → single-key mode.
    AWS_KMS_CMK_AUDIT_CHAIN_ALIAS           Audit chain-hash CMK alias.
    AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW   Current invitation signing CMK.
    AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD   Previous invitation CMK (grace
                                             window only). Optional.
    AWS_KMS_CMK_INVITATION_HMAC_ALIAS       Legacy single-key alias. Used as
                                             _NEW fallback when _NEW unset.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import boto3

# ---------------------------------------------------------------------------
# Defaults — kept in sync with scripts/init-localstack.sh. Callers may
# override via env vars. The defaults match the LocalStack bootstrap so
# dev containers work out of the box.
# ---------------------------------------------------------------------------

_DEFAULT_REGION = "us-east-1"
_DEFAULT_TOTP_DEK_ALIAS = "alias/echoroo-totp-dek"
_DEFAULT_PII_HASH_ALIAS = "alias/echoroo-pii-hash-hmac"
_DEFAULT_AUDIT_CHAIN_ALIAS = "alias/echoroo-audit-chain-hmac"
_DEFAULT_INVITATION_HMAC_ALIAS = "alias/echoroo-invitation-hmac"

_MAC_ALGORITHM = "HMAC_SHA_256"


# ---------------------------------------------------------------------------
# boto3 client (lazy, module-level, single-instance)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _client() -> Any:
    """Return a singleton boto3 KMS client.

    ``lru_cache`` memoises construction; the cache is transparent to
    tests because ``importlib.reload(echoroo.core.kms)`` rebinds the
    cache. Reading endpoint/region from env on first use means that
    ``monkeypatch.setenv`` before the first KMS call is honoured.
    """
    region = os.environ.get("AWS_KMS_REGION") or os.environ.get(
        "AWS_DEFAULT_REGION", _DEFAULT_REGION
    )
    endpoint_url = os.environ.get("AWS_KMS_ENDPOINT") or os.environ.get(
        "AWS_ENDPOINT_URL_KMS"
    )
    kwargs: dict[str, Any] = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("kms", **kwargs)


def _reset_client_cache() -> None:
    """Clear the cached boto3 client.

    Exposed for tests and key rotation hooks. Production code has no
    reason to call this; the process-wide singleton is stable for the
    lifetime of the worker.
    """
    _client.cache_clear()
    _resolve_key_id.cache_clear()


@lru_cache(maxsize=16)
def _resolve_key_id(alias: str) -> str:
    """Resolve an ``alias/...`` identifier to its canonical KeyId.

    AWS KMS accepts aliases for ``Encrypt`` and ``Decrypt`` but some
    ``GenerateMac`` / ``VerifyMac`` implementations (moto, older CLI
    versions) require a raw KeyId. Resolving once per alias keeps the
    hot path to a single KMS call per op and costs nothing after the
    first lookup.

    Returning the alias itself when ``describe_key`` fails lets real
    AWS (which accepts aliases universally) continue to work even if
    ``kms:DescribeKey`` is denied by IAM — in that case the downstream
    ``generate_mac`` call is responsible for surfacing the error.
    """
    try:
        resp = _client().describe_key(KeyId=alias)
    except Exception:  # noqa: BLE001 — tolerate IAM-restricted environments
        return alias
    key_id = resp.get("KeyMetadata", {}).get("KeyId")
    if not isinstance(key_id, str) or not key_id:
        return alias
    return key_id


# ---------------------------------------------------------------------------
# Alias resolvers — each wrapped so we fail fast with a clear error if an
# operator forgot to configure a CMK.
# ---------------------------------------------------------------------------


def _alias(env_var: str, default: str) -> str:
    value = os.environ.get(env_var, default)
    if not value:
        raise RuntimeError(
            f"KMS alias not configured: set {env_var} or rely on the default"
        )
    return value


def _totp_dek_alias() -> str:
    return _alias("AWS_KMS_CMK_2FA_ALIAS", _DEFAULT_TOTP_DEK_ALIAS)


def _pii_hash_alias() -> str:
    return _alias("AWS_KMS_CMK_PII_HASH_ALIAS", _DEFAULT_PII_HASH_ALIAS)


def _pii_hash_alias_v2() -> str | None:
    """Return the v2 PII hash alias when rotation is active, else ``None``.

    The v2 alias is opt-in (FR-091b): operators set
    ``AWS_KMS_CMK_PII_HASH_ALIAS_V2`` only during a rotation window. An
    unset env var → single-key mode → ``compute_pii_hash_dual`` returns
    only the v1 component and ``verify_pii_hash`` skips the v2 path.
    """
    value = os.environ.get("AWS_KMS_CMK_PII_HASH_ALIAS_V2")
    return value or None


def _audit_chain_alias() -> str:
    return _alias("AWS_KMS_CMK_AUDIT_CHAIN_ALIAS", _DEFAULT_AUDIT_CHAIN_ALIAS)


def _invitation_alias_new() -> str:
    """Return the currently active invitation HMAC alias."""
    new = os.environ.get("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW")
    if new:
        return new
    # Backwards compatibility: single-alias deployments (no rotation in
    # progress) can point everything at the legacy env var.
    return _alias("AWS_KMS_CMK_INVITATION_HMAC_ALIAS", _DEFAULT_INVITATION_HMAC_ALIAS)


def _invitation_alias_old() -> str | None:
    """Return the previous invitation HMAC alias, or None outside grace.

    Returning ``None`` (rather than raising) lets callers skip the
    fallback path cleanly once the 14-day grace window closes and
    operators unset the env var.
    """
    old = os.environ.get("AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD")
    return old or None


# ---------------------------------------------------------------------------
# T030a — TOTP DEK envelope
# ---------------------------------------------------------------------------


def wrap_dek(plaintext: bytes) -> bytes:
    """Wrap a TOTP data encryption key with the TOTP CMK.

    Returns the opaque KMS ciphertext blob. Callers store this blob
    alongside the encrypted TOTP secret; decrypting the secret requires
    first calling :func:`unwrap_dek` to recover the plaintext DEK.

    Args:
        plaintext: Raw DEK bytes (typically 32 bytes for AES-256-GCM).

    Returns:
        AWS KMS ciphertext blob, opaque bytes.
    """
    resp = _client().encrypt(
        KeyId=_totp_dek_alias(),
        Plaintext=plaintext,
    )
    ciphertext = resp["CiphertextBlob"]
    assert isinstance(ciphertext, bytes)
    return ciphertext


def unwrap_dek(wrapped: bytes) -> bytes:
    """Decrypt a previously wrapped DEK.

    Args:
        wrapped: Opaque KMS ciphertext blob returned by :func:`wrap_dek`.

    Returns:
        The original plaintext DEK bytes.

    Raises:
        botocore.exceptions.ClientError: If the blob was tampered with,
            signed by a different CMK, or the CMK has been rotated and
            the blob is no longer decryptable.
    """
    resp = _client().decrypt(
        CiphertextBlob=wrapped,
        KeyId=_totp_dek_alias(),
    )
    plaintext = resp["Plaintext"]
    assert isinstance(plaintext, bytes)
    return plaintext


# ---------------------------------------------------------------------------
# T030b — PII hash via kms:GenerateMac
# ---------------------------------------------------------------------------


def compute_pii_hash(value: str) -> str:
    """Return a keyed HMAC-SHA256 of ``value`` as lowercase hex.

    The key lives inside KMS and is never loaded into the application
    process (FR-091b). A compromise of the DB or application code cannot
    reveal the key — only the KMS audit log would record abuse.

    Args:
        value: Arbitrary UTF-8 string (email, IP, user-agent, etc.).

    Returns:
        64-character lowercase hex string representing the 32-byte MAC.
    """
    return _compute_pii_hash_with_alias(value, _pii_hash_alias())


# ---------------------------------------------------------------------------
# Phase 17 backlog A-2 — PII hash key rotation (FR-091b)
#
# ``compute_pii_hash_dual`` and ``verify_pii_hash`` implement the
# dual-write + dual-read contract that lets a CMK rotation roll forward
# without downtime:
#
#   * Pre-rotation (single-key mode):
#       AWS_KMS_CMK_PII_HASH_ALIAS_V2 unset.
#       ``compute_pii_hash_dual(value)`` → ``{"v1": <hex>}``.
#       ``verify_pii_hash`` matches the single-key v1 only.
#       ``get_pii_hash_version`` → 1.
#
#   * Rotation in progress (dual-write):
#       Operators set AWS_KMS_CMK_PII_HASH_ALIAS_V2 alongside the
#       existing AWS_KMS_CMK_PII_HASH_ALIAS. Every new write computes
#       BOTH hashes; the audit / invitation tables persist the v2
#       hash in a sibling ``*_v2`` column. Lookups try the v2 hash
#       first (matching freshly-written rows) then fall back to the
#       v1 hash (matching pre-rotation rows). The daily backfill
#       worker fills v2 for rows that have plaintext available.
#       ``get_pii_hash_version`` → 2.
#
#   * Post-rotation (v2 only):
#       Operators retire v1 by re-pointing
#       AWS_KMS_CMK_PII_HASH_ALIAS at the v2 CMK and unsetting
#       AWS_KMS_CMK_PII_HASH_ALIAS_V2. Code re-enters single-key
#       mode, this time keyed by what was previously v2.
#
# The v1 component of ``compute_pii_hash_dual`` MUST be byte-identical
# to ``compute_pii_hash`` (test T975-2). Sharing the implementation by
# delegating ensures that invariant cannot drift.
# ---------------------------------------------------------------------------


def _compute_pii_hash_with_alias(value: str, alias: str) -> str:
    """Compute the keyed HMAC against the given alias (internal helper).

    Centralised so :func:`compute_pii_hash` and the dual-write helpers
    share the exact same byte-level construction (UTF-8 encoding,
    ``HMAC_SHA_256`` algorithm, lowercase hex output).
    """
    message = value.encode("utf-8")
    resp = _client().generate_mac(
        Message=message,
        KeyId=_resolve_key_id(alias),
        MacAlgorithm=_MAC_ALGORITHM,
    )
    mac = resp["Mac"]
    assert isinstance(mac, bytes)
    return mac.hex()


def compute_pii_hash_dual(value: str) -> dict[str, str]:
    """Return the keyed HMAC under v1 and (when rotation is active) v2.

    The shape of the returned dict is driven by
    :func:`get_pii_hash_version` so writers and the version metadata
    column can never disagree (Phase 17 backlog A-2 Round 2 / R1-C2):

      * ``get_pii_hash_version() == 1`` (pre-rotation, single-key mode):
        return ``{"v1": <hex>}``. Writers MUST persist
        ``pii_hash_version = NULL`` (or 1) and leave the ``*_v2``
        sibling columns NULL.

      * ``get_pii_hash_version() == 2`` and v2 alias **set** (rotation
        in progress / dual-write window): return
        ``{"v1": <hex>, "v2": <hex>}`` computed against the two
        distinct CMKs. Writers MUST populate both columns and stamp
        ``pii_hash_version = 2``.

      * ``get_pii_hash_version() == 2`` and v2 alias **unset**
        (post-rotation: operator re-pointed
        ``AWS_KMS_CMK_PII_HASH_ALIAS`` at the v2 CMK and flipped
        ``ECHOROO_PII_HASH_ROTATION_COMPLETE``): return
        ``{"v1": <hex>, "v2": <hex>}`` where v1 == v2 byte-identically
        (both computed under the now-canonical alias). The redundant
        write keeps the storage shape stable across the rotation
        boundary and lets bulk lookups use ``WHERE *_v2 = ? OR
        legacy = ?`` without special-casing the post-rotation row
        family.

    Callers persisting to a sibling ``*_v2`` column MUST therefore
    guard with ``"v2" in result`` rather than relying on a sentinel
    value — writing ``None`` into the v2 column when the version
    metadata column says 2 would defeat the dual-read contract.

    The v1 component is byte-identical to :func:`compute_pii_hash` so
    historical-row lookups keyed on v1 continue to match.
    """
    v1 = _compute_pii_hash_with_alias(value, _pii_hash_alias())
    if get_pii_hash_version() == 1:
        # Single-key / pre-rotation. v2 column intentionally not populated.
        return {"v1": v1}
    v2_alias = _pii_hash_alias_v2()
    if v2_alias is None:
        # Post-rotation: v2 alias unset but the operator has flipped the
        # COMPLETE flag, so AWS_KMS_CMK_PII_HASH_ALIAS now points at the
        # rotated CMK. Reusing the v1 hash for v2 keeps writer + reader
        # logic uniform and lets every WHERE *_v2 = ? query continue to
        # match without a separate post-rotation branch.
        return {"v1": v1, "v2": v1}
    v2 = _compute_pii_hash_with_alias(value, v2_alias)
    return {"v1": v1, "v2": v2}


def verify_pii_hash(value: str, stored_hash: str) -> bool:
    """Return True iff ``stored_hash`` matches ``value`` under v1 OR v2.

    Verification order is v2 → v1 because:
      * Steady-state post-rotation rows (and freshly-written
        dual-write rows) match v2 first, so the common path is one
        KMS round-trip.
      * Pre-rotation historical rows fall back to v1.

    The :func:`hmac.compare_digest` constant-time comparator is used so
    a timing oracle cannot distinguish "wrong value" from "v1 row that
    happens to share a v2 prefix". Both KMS calls happen unconditionally
    when rotation is active to keep the timing side-channel flat for
    callers that do leak match/no-match.

    Failure semantics (Phase 17 backlog A-2 Round 2 / R1-I2):
      A KMS error on the v2 path is **fail-open by design** (FR-091b
      prioritises read availability during rotation), but it is NOT
      silent: every v2 unavailability is logged at WARNING level with
      the alias and exception class so operators can reconcile the
      KMS audit log against the application log. The v1 path uses the
      same observability shim. Returning ``True`` purely on a v1 match
      while v2 was unavailable is therefore explicit, not accidental.
    """
    import hmac as _hmac
    import logging

    logger = logging.getLogger(__name__)

    if not isinstance(stored_hash, str) or len(stored_hash) != 64:
        return False

    v2_alias = _pii_hash_alias_v2()
    matched_v2 = False
    matched_v1 = False

    if v2_alias is not None:
        try:
            candidate_v2 = _compute_pii_hash_with_alias(value, v2_alias)
        except Exception as exc:  # noqa: BLE001 — KMS error → fall back to v1 only
            # FR-091b fail-open by design: rotation must not break read
            # availability. Surface the failure in observability so
            # operators can spot the boundary case.
            logger.warning(
                "verify_pii_hash: v2 KMS unavailable; falling back to v1 "
                "(alias=%s exc=%s)",
                v2_alias,
                exc.__class__.__name__,
            )
            candidate_v2 = ""
        if candidate_v2 and _hmac.compare_digest(candidate_v2, stored_hash):
            matched_v2 = True

    try:
        candidate_v1 = _compute_pii_hash_with_alias(value, _pii_hash_alias())
    except Exception as exc:  # noqa: BLE001 — KMS error → no v1 match possible
        logger.warning(
            "verify_pii_hash: v1 KMS unavailable; v1 match not attempted "
            "(alias=%s exc=%s)",
            _pii_hash_alias(),
            exc.__class__.__name__,
        )
        candidate_v1 = ""
    if candidate_v1 and _hmac.compare_digest(candidate_v1, stored_hash):
        matched_v1 = True

    return matched_v2 or matched_v1


def get_pii_hash_version() -> int:
    """Return the active PII hash CMK version (1 or 2).

    The version is derived from operator-controlled environment:

      * ``AWS_KMS_CMK_PII_HASH_ALIAS_V2`` set
            → rotation in progress (dual-write) → 2
      * ``ECHOROO_PII_HASH_ROTATION_COMPLETE=true``
            → operator has retired the v1 alias and pointed
              ``AWS_KMS_CMK_PII_HASH_ALIAS`` at the v2 CMK → 2
      * neither set
            → single-key (pre-rotation) mode → 1

    The two upgrade signals are intentionally orthogonal: a deployment
    is "in progress" while v2 alias is present, and "completed" once
    the operator flips ``ECHOROO_PII_HASH_ROTATION_COMPLETE`` and
    unsets the v2 alias. Both end-states agree that the canonical
    hash carries generation 2.
    """
    if _pii_hash_alias_v2() is not None:
        return 2
    if os.environ.get("ECHOROO_PII_HASH_ROTATION_COMPLETE", "").lower() in (
        "true",
        "1",
        "yes",
    ):
        return 2
    return 1


# ---------------------------------------------------------------------------
# T030c — invitation token HMAC with k_old / k_new grace
# ---------------------------------------------------------------------------


def sign_invitation_hmac(payload: bytes) -> str:
    """Sign an invitation token payload with the current (k_new) key.

    The signature is returned as lowercase hex so it can be safely
    embedded in URLs without base64 padding concerns.

    Args:
        payload: Canonical byte payload (typically
            ``b"{invitation_id}:{expires_at_iso}"``).

    Returns:
        64-character lowercase hex HMAC-SHA256.
    """
    resp = _client().generate_mac(
        Message=payload,
        KeyId=_resolve_key_id(_invitation_alias_new()),
        MacAlgorithm=_MAC_ALGORITHM,
    )
    mac = resp["Mac"]
    assert isinstance(mac, bytes)
    return mac.hex()


def verify_invitation_hmac(payload: bytes, sig: str) -> bool:
    """Verify an invitation signature using k_new, falling back to k_old.

    The verification order is deliberately k_new → k_old so steady-state
    traffic (post-grace) only makes one KMS call. During a rotation
    window tokens issued by the previous key still validate.

    KMS ``VerifyMac`` raises ``ClientError`` (InvalidCiphertextException
    / KMSInvalidMacException) when the MAC does not match. We translate
    those into ``False`` so callers can treat the result as a boolean
    check without catching boto3 exceptions.

    Args:
        payload: The byte payload that was signed.
        sig: Lowercase hex HMAC-SHA256 to verify.

    Returns:
        True if the signature is valid under k_new **or** k_old.
    """
    try:
        mac = bytes.fromhex(sig)
    except ValueError:
        return False

    client = _client()

    for alias in (_invitation_alias_new(), _invitation_alias_old()):
        if alias is None:
            continue
        try:
            resp = client.verify_mac(
                Message=payload,
                KeyId=_resolve_key_id(alias),
                MacAlgorithm=_MAC_ALGORITHM,
                Mac=mac,
            )
        except Exception:  # noqa: BLE001 — boto3 raises ClientError on mismatch
            continue
        if resp.get("MacValid", False):
            return True
    return False


# ---------------------------------------------------------------------------
# T030d — audit log chain-hash
# ---------------------------------------------------------------------------


def compute_audit_chain_hash(prev_hash: str, canonical_row: bytes) -> str:
    """Compute ``row_hash = HMAC-SHA256(chain_key, prev_hash || canonical_row)``.

    The chain_key lives in a dedicated CMK (``alias/echoroo-audit-chain-hmac``)
    to guarantee that a compromise of the PII hashing key cannot be used
    to forge audit chain entries, and vice versa.

    The ``prev_hash`` is treated as an opaque byte string (the hex is
    encoded verbatim — no conversion to raw bytes). This keeps the
    canonicalisation trivial to audit and matches the schema where
    ``prev_hash`` is stored as hex.

    Args:
        prev_hash: Lowercase hex row_hash of the previous audit row
            (genesis row uses 64 zero chars).
        canonical_row: Canonicalised JSON (or other stable byte
            representation) of the current audit row.

    Returns:
        64-character lowercase hex HMAC-SHA256.
    """
    message = prev_hash.encode("ascii") + canonical_row
    resp = _client().generate_mac(
        Message=message,
        KeyId=_resolve_key_id(_audit_chain_alias()),
        MacAlgorithm=_MAC_ALGORITHM,
    )
    mac = resp["Mac"]
    assert isinstance(mac, bytes)
    return mac.hex()


__all__ = [
    "compute_audit_chain_hash",
    "compute_pii_hash",
    "compute_pii_hash_dual",
    "get_pii_hash_version",
    "sign_invitation_hmac",
    "unwrap_dek",
    "verify_invitation_hmac",
    "verify_pii_hash",
    "wrap_dek",
]
