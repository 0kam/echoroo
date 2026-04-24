"""Audit log sanitizer (FR-091a).

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
       ``{"hash": sha256(original_utf8), "hash_version": "v1", "redacted": True}``

Collections are walked recursively (dict values + list elements). Keys are
not sanitised — per FR-091a the build-time lint already forbids PII key
names. Non-string leaves (int / float / bool / None / UUID) pass through
unchanged except that ``actor_user_id`` / ``before.owner_id`` UUIDs are
explicitly allowed raw by spec.

The hash is SHA-256 (NOT the KMS keyed hash) because this module runs
without external dependencies — the KMS-keyed ``actor_user_id_hash`` /
``ip_hash`` / ``user_agent_hash`` columns are computed by
``audit_service.py`` before the sanitizer ever sees them. Using SHA-256
for the runtime replacement keeps the sanitizer pure and deterministic,
which is what the bypass test suite (T052) verifies.

Performance: typical audit payloads are < 4 KB with ≤ 50 leaves; scan cost
is dominated by regex matching (~0.1 ms per payload in CPython 3.11).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import re
import unicodedata
import urllib.parse
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HASH_VERSION: Final[str] = "v1"
"""Version tag stored in the redacted marker so future algorithm changes can
be distinguished without a breaking schema migration."""

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


def _build_redaction(original: str) -> dict[str, Any]:
    """Return the redaction marker for ``original``."""
    digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
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


# ---------------------------------------------------------------------------
# T050b — recursive replacement
# ---------------------------------------------------------------------------


def sanitize_value(value: Any) -> Any:
    """Return a sanitised copy of ``value`` with PII strings redacted.

    - ``dict``: recurse on values (keys are NOT touched; the build-time lint
      owns the key-name guardrail).
    - ``list`` / ``tuple``: recurse on each element; tuples are returned as
      lists because JSONB has no tuple type.
    - ``str``: if it contains PII, return the redaction marker; otherwise
      return the string unchanged (the normalised form is NOT written back
      to preserve audit-log fidelity for non-PII content such as event
      descriptions).
    - anything else: returned unchanged.
    """
    if isinstance(value, dict):
        return {key: sanitize_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_value(inner) for inner in value]
    if isinstance(value, str):
        if _scan_string(value):
            return _build_redaction(value)
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
    "sanitize_value",
]
