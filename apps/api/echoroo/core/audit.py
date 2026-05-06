"""Audit log sanitizer (FR-091a, FR-091b).

The sanitizer is the runtime safety net that guarantees raw PII is never
persisted to the audit log JSONB columns (``detail`` / ``before`` / ``after``).
The build-time CI lint (FR-091a layer a) guards against *literal* PII key
names in source code; this module is layer b — a deep-walk + regex + decode
pipeline that catches dynamic injection, Unicode homoglyph bypass, URL-
encoded, and base64-encoded PII before the row reaches PostgreSQL.

Pipeline per scalar string value:

    1. Unicode NFKC normalise (collapses fullwidth / homoglyph tricks)
    2. Scan for PII regexes against the normalised form
    3. If no hit, try urllib.parse.unquote once and re-scan
    4. If still no hit, attempt base64 decode (padding-tolerant) and re-scan
       the decoded UTF-8 (skip silently on binary / invalid)
    5. On any hit, replace the ENTIRE value with
       ``{"hash": <keyed-hmac-sha256>, "hash_version": "v2", "redacted": True}``

Collections are walked recursively (BOTH dict keys and values + list
elements). String dict keys whose normalised form contains PII are replaced
with a stable opaque marker ``__redacted_key_<8-hex>__`` so an attacker
cannot smuggle PII through the key axis (Phase 2.10 #3).

Keyed hashing
-------------
Phase 2.10 #4: the redaction marker's ``hash`` field uses a KEYED HMAC
(via :func:`echoroo.core.kms.compute_pii_hash`, which round-trips to KMS)
rather than plain SHA-256. A plain hash of low-entropy values (emails,
phone numbers) is dictionary-attackable; the keyed HMAC denies that
attack because the key is held inside KMS and never exposed to the
application process.

Tests can inject a deterministic fake hash function via the ``hash_fn``
parameter on :func:`sanitize_value` to avoid a KMS dependency in unit
tests. ``hash_version`` is ``v2`` to mark the keyed-hash migration. v1
(unkeyed sha256) is deprecated; per project_status.md (Pre-launch) no
production rows exist, so no migration is needed.

Performance: typical audit payloads are < 4 KB with ≤ 50 leaves; scan cost
is dominated by regex matching (~0.1 ms per payload in CPython 3.11) plus
one KMS round-trip per redaction (~5 ms p99 in production).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import re
import unicodedata
import urllib.parse
from collections.abc import Callable
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASH_VERSION: Final[str] = "v3"
"""Version tag stored in the redacted marker so future algorithm changes can
be distinguished without a breaking schema migration.

* v1 — unkeyed SHA-256, deprecated by Phase 2.10 #4 (no production rows
  existed per project_status.md "Pre-launch", so no migration required).
* v2 — keyed HMAC-SHA256 via :func:`echoroo.core.kms.compute_pii_hash`,
  applied to VALUES only. Dict KEY markers still used a plain SHA-256
  truncated to 8 hex chars, which Phase 2.11 P0-a flagged as
  dictionary-attackable for low-entropy PII (emails, phone numbers).
* v3 — Phase 2.11 P0-a: dict KEY markers route through the same keyed
  hash function used for value redaction (default
  :func:`echoroo.core.kms.compute_pii_hash`) and preserve a 32-hex-char
  suffix to defeat birthday collisions in cardinality dashboards. Both
  keys and values now use the keyed HMAC; the bumped HASH_VERSION lets
  log readers tell the two regimes apart.
"""

# Number of hex chars preserved in a dict-key redaction marker. Phase 2.11
# P0-a: 8 chars was vulnerable to birthday collisions; 32 chars (128 bits)
# is the same entropy as a random UUID and is safe for cardinality use.
_KEY_MARKER_HEX_LEN: Final[int] = 32

#: Type alias for the hash function injection point. Tests pass a
#: deterministic fake to avoid the KMS round-trip; production callers
#: omit the argument and the default routes through KMS.
HashFn = Callable[[str], str]

# Characters we strip before regex matching. Null bytes and other C0 control
# characters are common bypass attempts (null-byte truncation in native
# regex backends). We preserve tab (0x09), LF (0x0A), and CR (0x0D) since
# PII-like substrings can legitimately span those.
_CONTROL_STRIP_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# UUID canonical form (8-4-4-4-12 hex). FR-091a §c permits raw UUID user_id
# values in audit payloads, so we skip redaction for exact UUID-shaped
# leaves. The full-string anchor prevents bypassing the sanitizer by
# wrapping PII inside a UUID-ish container.
_UUID_ONLY_RE: Final[re.Pattern[str]] = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


# ---------------------------------------------------------------------------
# PII regex catalogue
# ---------------------------------------------------------------------------
# Each pattern is deliberately permissive — false positives redact more than
# needed, which is the fail-safe direction. A false negative (raw PII
# persisted) is the actual risk we are guarding against.

_EMAIL_RE: Final[re.Pattern[str]] = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

# International phone: +<country><digits with any mix of space / dash>.
# Enforced total digit count 8-16 (country + subscriber) to avoid matching
# short arithmetic expressions like "+1 2 = 3".
_PHONE_INTL_RE: Final[re.Pattern[str]] = re.compile(
    r"\+(?:[0-9][\s\-]?){7,15}[0-9]"
)

# Japanese domestic phone: 0X(X)-XXXX-XXXX or 0XX XXXX XXXX (loose).
_PHONE_JP_RE: Final[re.Pattern[str]] = re.compile(
    r"\b0[1-9]0[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b|\b0[1-9][\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b"
)

# Credit card: 13-19 digits, optional separators. Luhn not verified (FR-091a
# says regex-only is acceptable and redaction is the fail-safe direction).
_CREDIT_CARD_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d[ \-]?){13,19}\b"
)

# IBAN: country (2 letters) + 2 check digits + up to 30 alphanumeric.
_IBAN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}\b"
)

# US SSN: 3-2-4 digits. We accept any separator (or none) to catch obfuscation.
_US_SSN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9]{3}[\s\-]?[0-9]{2}[\s\-]?[0-9]{4}\b"
)

# Japanese My Number: 12 digits (spec FR-091a). We accept separator variants
# the same way US SSN does.
_JP_MY_NUMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:[0-9][\s\-]?){11}[0-9]\b"
)

# JWT: three base64url segments separated by dots. Keeping minimum segment
# length at 10 avoids matching regular "a.b.c" strings.
_JWT_RE: Final[re.Pattern[str]] = re.compile(
    r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"
)

# Bearer tokens: "Bearer <token>" or "Authorization: Bearer <token>".
_BEARER_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\bBearer\s+[A-Za-z0-9_\-\.=:]{8,}"
)

# AWS access key IDs (AKIA / ASIA) are 20 uppercase alphanumeric chars.
_AWS_AKID_RE: Final[re.Pattern[str]] = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")

# AWS secret access keys are 40 base64-ish characters. We only redact when
# the full 40-char token is isolated by word boundaries to minimise FP risk.
_AWS_SECRET_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9/+=])[A-Za-z0-9/+=]{40}(?![A-Za-z0-9/+=])"
)


# Order matters: more-specific patterns come first so we don't accidentally
# label a JWT as "credit card" (19+ digits would otherwise match).
_PII_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    _JWT_RE,
    _BEARER_RE,
    _AWS_AKID_RE,
    _AWS_SECRET_RE,
    _EMAIL_RE,
    _IBAN_RE,
    _PHONE_INTL_RE,
    _PHONE_JP_RE,
    _CREDIT_CARD_RE,
    _US_SSN_RE,
    _JP_MY_NUMBER_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(value: str) -> str:
    """Collapse Unicode compatibility forms + strip control chars.

    NFKC maps fullwidth Latin / Kana-width digits / homoglyph letters to
    their ASCII counterparts, defeating visual lookalike bypasses such as
    ``ｕｓｅｒ＠ｅｘａｍｐｌｅ．ｃｏｍ`` (fullwidth email).
    """
    return _CONTROL_STRIP_RE.sub("", unicodedata.normalize("NFKC", value))


def _matches_pii(value: str) -> bool:
    """Return True if ``value`` contains any PII pattern."""
    return any(pat.search(value) for pat in _PII_PATTERNS)


def _try_url_decode(value: str) -> str | None:
    """Return the URL-decoded form when it differs from the input, else None."""
    try:
        decoded = urllib.parse.unquote(value)
    except Exception:  # noqa: BLE001 — urllib raising is very rare, stay safe
        return None
    return decoded if decoded != value else None


def _try_base64_decode(value: str) -> str | None:
    """Attempt base64 decode and return the UTF-8 text, or None on failure.

    Accepts standard and URL-safe alphabets, and pads missing ``=`` so
    short encodings still decode. The output must be valid UTF-8 for the
    secondary regex scan to run; binary or non-UTF-8 payloads fall back
    to None (the original value still goes through the main regex scan,
    so this only catches additional bypasses).
    """
    stripped = value.strip()
    # Require at least 8 base64 chars to avoid decoding trivial 4-char strings
    # like "test" that happen to be valid base64.
    if len(stripped) < 8:
        return None
    padded = stripped + "=" * (-len(stripped) % 4)
    candidates: list[bytes] = []
    with contextlib.suppress(binascii.Error, ValueError):
        candidates.append(base64.b64decode(padded, validate=False))
    with contextlib.suppress(binascii.Error, ValueError):
        candidates.append(base64.urlsafe_b64decode(padded))
    for raw in candidates:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def _default_hash_fn(value: str) -> str:
    """Default keyed hash — KMS-backed HMAC-SHA256.

    Imported lazily so that tests / scripts that never trigger a
    redaction do not pay the boto3 import cost.
    """
    # Local import to avoid a top-level boto3 dependency in modules that
    # only call sanitize_value() with a test ``hash_fn`` injected.
    from echoroo.core.kms import compute_pii_hash

    return compute_pii_hash(value)


def _build_redaction(original: str, *, hash_fn: HashFn | None = None) -> dict[str, Any]:
    """Return the redaction marker for ``original``.

    Args:
        original: The PII string being redacted.
        hash_fn: Optional override of the keyed-hash callable. Defaults
            to :func:`_default_hash_fn` (KMS-backed). Tests pass a fake
            (e.g. ``lambda v: hashlib.sha256(b"test-key" + v.encode()).
            hexdigest()``) to keep the suite KMS-free.
    """
    fn = hash_fn or _default_hash_fn
    digest = fn(original)
    return {
        "hash": digest,
        "hash_version": HASH_VERSION,
        "redacted": True,
    }


def _scan_string(value: str) -> bool:
    """Return True if any of (normalised / url-decoded / base64-decoded)
    variant of ``value`` contains PII."""
    normalised = _normalise(value)
    # FR-091a §c: raw UUIDs (e.g. owner_id / target_user_id fields) are
    # allowed. The exact-match guard prevents extending the allowance to
    # free-form text that merely contains a UUID substring.
    if _UUID_ONLY_RE.match(normalised):
        return False
    if _matches_pii(normalised):
        return True

    url_decoded = _try_url_decode(normalised)
    if url_decoded is not None and _matches_pii(_normalise(url_decoded)):
        return True

    b64_decoded = _try_base64_decode(value)
    return bool(
        b64_decoded is not None and _matches_pii(_normalise(b64_decoded))
    )


def contains_pii(value: str) -> bool:
    """Public detector — return True if ``value`` contains any PII pattern.

    Phase 17 backlog A-13: this thin wrapper exposes the same regex
    catalogue used by :class:`AuditLogSanitizer` so the API-boundary
    operator-input validator (:mod:`echoroo.core.operator_pii_detector`)
    enforces the FR-091a contract identically. Sanitiser (audit) and
    detector (validator) responsibilities stay separated, but the
    underlying pattern set is owned by this module.

    The full sanitiser pipeline (NFKC normalisation, URL-decode and
    base64-decode bypass detection, UUID allowlist) is reused so an
    operator cannot smuggle PII past the validator with the same
    encoding tricks the audit sanitiser already defends against.

    Args:
        value: Free-form string to scan. Non-strings and empty strings
            return ``False`` rather than raising so this can be called
            unconditionally on user input that may be missing.

    Returns:
        True iff any PII regex matches the value (or any of its
        decoded variants).
    """
    if not isinstance(value, str) or not value:
        return False
    return _scan_string(value)


# ---------------------------------------------------------------------------
# T050b — recursive replacement
# ---------------------------------------------------------------------------


def _redacted_key_marker(
    original_key: str,
    *,
    hash_fn: HashFn | None = None,
) -> str:
    """Return a stable opaque marker for a redacted dict key.

    Phase 2.11 P0-a: previously the marker was the first 8 hex chars of a
    plain (unkeyed) SHA-256 over the key. Two problems with that design:

    * Plain SHA-256 of a low-entropy PII string (e.g. an email address or
      a phone number) is dictionary-attackable — an attacker who exfils
      the audit log can rainbow-table the key markers back to the
      original PII.
    * 8 hex chars (32 bits) is birthday-vulnerable for cardinality
      dashboards: ~64k keys collide with non-trivial probability.

    The marker now routes through the same keyed-hash callable used by
    value redaction (default :func:`_default_hash_fn` →
    :func:`echoroo.core.kms.compute_pii_hash`) and preserves
    :data:`_KEY_MARKER_HEX_LEN` (=32) hex chars (128 bits, same as a
    random UUID).

    Args:
        original_key: The PII string used as a dict key.
        hash_fn: Optional override of the keyed-hash callable. Defaults
            to the same KMS-backed HMAC used for value redaction so that
            (a) tests can inject a deterministic stub and (b) the same
            PII appearing as both KEY and VALUE produces consistent hash
            digests (just embedded into different shapes).
    """
    fn = hash_fn or _default_hash_fn
    short = fn(original_key)[:_KEY_MARKER_HEX_LEN]
    return f"__redacted_key_{short}__"


def sanitize_value(value: Any, *, hash_fn: HashFn | None = None) -> Any:
    """Return a sanitised copy of ``value`` with PII strings redacted.

    Args:
        value: Input to sanitise.
        hash_fn: Optional keyed-hash callable for the redaction marker.
            Defaults to :func:`_default_hash_fn` (KMS HMAC). Tests pass
            a deterministic stand-in to avoid the KMS dependency.

    - ``dict``: recurse on **both** keys and values. A key whose
      *string* form contains PII is replaced with a stable hashed
      marker (:func:`_redacted_key_marker`); its associated value is
      still sanitised recursively. Non-string keys (e.g. ``int``) are
      passed through. The build-time lint (FR-091a layer a) catches
      *literal* PII key names in source; this runtime guard catches
      dynamic injection of PII into key positions (e.g.
      ``{user_email: payload}``).
    - ``list`` / ``tuple``: recurse on each element; tuples are returned as
      lists because JSONB has no tuple type.
    - ``str``: if it contains PII, return the redaction marker; otherwise
      return the string unchanged (the normalised form is NOT written back
      to preserve audit-log fidelity for non-PII content such as event
      descriptions).
    - anything else: returned unchanged.
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, inner in value.items():
            sanitised_value = sanitize_value(inner, hash_fn=hash_fn)
            if isinstance(key, str) and _scan_string(key):
                # Phase 2.11 P0-a: route the key marker through the same
                # keyed hash used for value redaction so PII keys are not
                # dictionary-attackable.
                out[_redacted_key_marker(key, hash_fn=hash_fn)] = sanitised_value
            else:
                out[key] = sanitised_value
        return out
    if isinstance(value, (list, tuple)):
        return [sanitize_value(inner, hash_fn=hash_fn) for inner in value]
    if isinstance(value, str):
        if _scan_string(value):
            return _build_redaction(value, hash_fn=hash_fn)
        return value
    return value


# ---------------------------------------------------------------------------
# T050a — Pydantic model
# ---------------------------------------------------------------------------


class AuditLogSanitizer(BaseModel):
    """Pydantic model that sanitises ``detail`` / ``before`` / ``after``
    JSONB payloads at validation time.

    Usage pattern in audit_service.py::

        sanitized = AuditLogSanitizer(
            detail=raw_detail, before=raw_before, after=raw_after
        )
        row = ProjectAuditLog(
            detail=sanitized.detail,
            before=sanitized.before,
            after=sanitized.after,
            ...
        )

    Any PII regex hit collapses the ENTIRE string value to the redaction
    marker; partial (substring) redaction is intentionally NOT supported
    because it leaks positional information about where the PII sat in
    the original payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: dict[str, Any]
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    @field_validator("detail", mode="before")
    @classmethod
    def _sanitize_detail(cls, value: Any) -> Any:
        if value is None:
            return {}
        sanitised = sanitize_value(value)
        if not isinstance(sanitised, dict):
            raise ValueError("detail must be a JSON object")
        return sanitised

    @field_validator("before", "after", mode="before")
    @classmethod
    def _sanitize_optional(cls, value: Any) -> Any:
        if value is None:
            return None
        sanitised = sanitize_value(value)
        if not isinstance(sanitised, dict):
            raise ValueError("before / after must be a JSON object or null")
        return sanitised


__all__ = [
    "HASH_VERSION",
    "AuditLogSanitizer",
    "HashFn",
    "contains_pii",
    "sanitize_value",
]
