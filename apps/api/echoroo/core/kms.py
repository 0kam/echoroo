"""Application-facing cryptographic operations backed by the local keyring.

The public functions in this module preserve the application-facing crypto
boundary. Key material is loaded and validated by :mod:`echoroo.core.keyring`;
this adapter does not expose it or log any operation inputs.
"""

from __future__ import annotations

import hmac
import logging

from echoroo.core import keyring

logger = logging.getLogger(__name__)


def _selected_key(key_id: str | None, role: str) -> str:
    """Return a validated selected key id or raise a configuration error."""
    if key_id is None:
        raise keyring.KeyringConfigError(f"{role} key selector is missing")
    return key_id


def wrap_dek(plaintext: bytes | bytearray, *, key_id: str) -> bytes:
    """Wrap a TOTP data-encryption key under the selected key id."""
    return keyring.get_keyring().wrap(plaintext, key_id)


def unwrap_dek(wrapped: bytes, *, key_id: str) -> bytearray:
    """Unwrap a TOTP data-encryption key and bind it to ``key_id``."""
    return keyring.get_keyring().unwrap(wrapped, key_id)


def rewrap_dek(
    wrapped: bytes,
    *,
    source_key_id: str,
    destination_key_id: str,
) -> bytes:
    """Rewrap a TOTP data-encryption key between explicit key ids."""
    return keyring.get_keyring().rewrap(
        wrapped,
        source_key_id,
        destination_key_id,
    )


def _hmac_hex(key_id: str, message: bytes, purpose: keyring.HmacPurpose) -> str:
    """Compute a keyed digest through the configured keyring."""
    return keyring.get_keyring().hmac_hex(key_id, message, purpose)


def compute_pii_hash(value: str) -> str:
    """Return the selected v1 PII HMAC as lowercase hexadecimal."""
    selectors = keyring.get_selectors()
    pii_key = _selected_key(selectors.pii_key, "PII")
    return _hmac_hex(pii_key, value.encode("utf-8"), "pii-hmac")


def compute_pii_hash_dual(value: str) -> dict[str, str]:
    """Return the selected v1 PII HMAC and, when selected, the v2 HMAC."""
    selectors = keyring.get_selectors()
    pii_key = _selected_key(selectors.pii_key, "PII")
    v1 = _hmac_hex(pii_key, value.encode("utf-8"), "pii-hmac")
    if selectors.pii_key_v2 is None:
        return {"v1": v1}
    v2 = _hmac_hex(selectors.pii_key_v2, value.encode("utf-8"), "pii-hmac")
    return {"v1": v1, "v2": v2}


def verify_pii_hash(value: str, stored_hash: str) -> bool:
    """Return whether ``stored_hash`` matches the selected v2 or v1 HMAC."""
    if not isinstance(stored_hash, str) or len(stored_hash) != 64:
        return False

    selectors = keyring.get_selectors()
    message = value.encode("utf-8")
    matched_v2 = False
    matched_v1 = False

    if selectors.pii_key_v2 is not None:
        try:
            candidate_v2 = _hmac_hex(selectors.pii_key_v2, message, "pii-hmac")
        except keyring.KeyringError as exc:
            logger.warning(
                "verify_pii_hash: v2 keyring unavailable; falling back to v1 (%s)",
                exc.__class__.__name__,
            )
            candidate_v2 = ""
        if candidate_v2:
            matched_v2 = hmac.compare_digest(candidate_v2, stored_hash)

    try:
        pii_key = _selected_key(selectors.pii_key, "PII")
        candidate_v1 = _hmac_hex(pii_key, message, "pii-hmac")
    except keyring.KeyringError as exc:
        logger.warning(
            "verify_pii_hash: v1 keyring unavailable; v1 match not attempted (%s)",
            exc.__class__.__name__,
        )
        candidate_v1 = ""
    if candidate_v1:
        matched_v1 = hmac.compare_digest(candidate_v1, stored_hash)

    return matched_v2 or matched_v1


def get_pii_hash_version() -> int:
    """Return 2 when a v2 PII key is selected, otherwise 1."""
    return 2 if keyring.get_selectors().pii_key_v2 is not None else 1


def compute_audit_chain_hash(prev_hash: str, canonical_row: bytes) -> str:
    """Return the audit-chain HMAC over the previous hash and canonical row."""
    selectors = keyring.get_selectors()
    audit_key = _selected_key(selectors.audit_key, "audit")
    message = prev_hash.encode("ascii") + canonical_row
    return _hmac_hex(audit_key, message, "audit-hmac")


__all__ = [
    "compute_audit_chain_hash",
    "compute_pii_hash",
    "compute_pii_hash_dual",
    "get_pii_hash_version",
    "rewrap_dek",
    "unwrap_dek",
    "verify_pii_hash",
    "wrap_dek",
]
