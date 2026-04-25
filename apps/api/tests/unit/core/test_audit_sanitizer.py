"""Bypass test suite for :mod:`echoroo.core.audit` (T052, FR-091a, SC-020).

Each parametrised case starts with raw PII that would slip past a naive
regex-only scanner and asserts that :func:`sanitize_value` (and via it,
:class:`AuditLogSanitizer`) redacts the leaf completely. A redaction is
verified by two conditions:

1. The leaf becomes a dict with ``{"hash", "hash_version", "redacted"}``.
2. No substring of the original raw PII survives anywhere in the output
   tree (``_assert_no_raw_leak`` walks recursively).

The second condition is the critical one — if a future refactor weakens
the regex pipeline, it will leak raw PII somewhere in the structure
even if the leaf itself is replaced.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from echoroo.core.audit import (
    HASH_VERSION,
    AuditLogSanitizer,
    sanitize_value,
)


# ---------------------------------------------------------------------------
# Autouse hash_fn stub
# ---------------------------------------------------------------------------
#
# Phase 2.10 #4 replaced the plain SHA-256 redaction hash with a KMS-keyed
# HMAC via ``_default_hash_fn`` → ``echoroo.core.kms.compute_pii_hash``.
# Unit tests must not round-trip to KMS, so this autouse fixture patches
# the default to a deterministic local keyed hash.


_FAKE_TEST_KEY = b"test-key-phase-2.10"


def _fake_keyed_hash(value: str) -> str:
    """Deterministic stand-in for ``compute_pii_hash`` used by unit tests."""
    return hashlib.sha256(_FAKE_TEST_KEY + value.encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _patch_default_hash_fn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the sanitizer's default hash to the deterministic test stub."""
    from echoroo.core import audit as _audit_module

    monkeypatch.setattr(_audit_module, "_default_hash_fn", _fake_keyed_hash)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _flatten(value: Any) -> list[Any]:
    """Yield every leaf in a JSON-ish structure."""
    if isinstance(value, dict):
        out: list[Any] = []
        for v in value.values():
            out.extend(_flatten(v))
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_flatten(v))
        return out
    return [value]


def _assert_no_raw_leak(tree: Any, forbidden: str) -> None:
    """Fail the test if ``forbidden`` appears verbatim anywhere in ``tree``."""
    for leaf in _flatten(tree):
        if isinstance(leaf, str):
            assert forbidden not in leaf, (
                f"raw PII leak: {forbidden!r} found in {leaf!r}"
            )


def _assert_is_redaction(value: Any) -> None:
    assert isinstance(value, dict), f"expected redaction dict, got {type(value)!r}"
    assert value.get("redacted") is True
    assert value.get("hash_version") == HASH_VERSION
    assert isinstance(value.get("hash"), str) and len(value["hash"]) == 64


# ---------------------------------------------------------------------------
# Parametric bypass cases (≥ 10)
# ---------------------------------------------------------------------------


_EMAIL = "alice.smith+promo@example.co.jp"
_PHONE = "+1 202-555-0123"
_JP_PHONE = "090-1234-5678"
_SSN = "123-45-6789"
_CARD = "4111 1111 1111 1111"
_AKID = "AKIAIOSFODNN7EXAMPLE"
_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3OCJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"


_CASES: list[tuple[str, Any, str]] = [
    # 1. Email nested one level deep in a dict
    (
        "nested_email",
        {"user": {"contact": _EMAIL}},
        _EMAIL,
    ),
    # 2. Email inside an array leaf
    (
        "email_in_array",
        {"recipients": ["admin@echoroo.test", "bob@example.org"]},
        "admin@echoroo.test",
    ),
    # 3. Fullwidth (Unicode homoglyph) email — defeats naive ASCII-only regex
    (
        "fullwidth_email",
        {"who": "ａｌｉｃｅ＠ｅｘａｍｐｌｅ．ｃｏｍ"},  # noqa: RUF001
        "ａｌｉｃｅ＠ｅｘａｍｐｌｅ．ｃｏｍ",  # noqa: RUF001
    ),
    # 4. URL-encoded email inside a tracking link parameter
    (
        "url_encoded_email",
        {"next": "https://echoroo.app/?u=alice%40example.com"},
        "alice%40example.com",
    ),
    # 5. Base64-encoded credential blob
    (
        "base64_jwt",
        {
            "payload": base64.b64encode(_JWT.encode()).decode(),
        },
        base64.b64encode(_JWT.encode()).decode(),
    ),
    # 6. Null-byte truncation attempt (sanitizer must strip control chars
    #    before matching so the trailing email still redacts).
    (
        "null_byte_truncation",
        {"raw": f"safe\x00{_EMAIL}"},
        _EMAIL,
    ),
    # 7. Control-char interleaving inside phone number
    (
        "control_char_phone",
        {"phone": "\x07" + _PHONE + "\x1b"},
        _PHONE,
    ),
    # 8. Deeply nested array-of-dicts with credit card
    (
        "deep_nested_card",
        {"events": [{"payments": [{"card_number": _CARD}]}]},
        _CARD,
    ),
    # 9. Bearer token in a header-style value
    (
        "bearer_token",
        {"authz": f"Bearer {_JWT}"},
        _JWT,
    ),
    # 10. AWS access key ID leaked in free-form text
    (
        "aws_access_key",
        {"note": f"deploy key {_AKID} rotated"},
        _AKID,
    ),
    # 11. Japanese phone number, mixed separators
    (
        "jp_phone",
        {"tel": _JP_PHONE},
        _JP_PHONE,
    ),
    # 12. US SSN surrounded by punctuation
    (
        "us_ssn",
        {"note": f"ssn={_SSN};end"},
        _SSN,
    ),
    # 13. URL-encoded phone inside JSON string
    (
        "url_encoded_phone",
        {"url": "https://x/?phone=%2B1%20202-555-0123"},
        "%2B1%20202-555-0123",
    ),
]


@pytest.mark.parametrize(
    ("case_id", "payload", "forbidden"),
    [pytest.param(*c, id=c[0]) for c in _CASES],
)
def test_sanitize_value_redacts_pii(case_id: str, payload: Any, forbidden: str) -> None:
    sanitised = sanitize_value(payload)
    _assert_no_raw_leak(sanitised, forbidden)


@pytest.mark.parametrize(
    ("case_id", "payload", "forbidden"),
    [pytest.param(*c, id=c[0]) for c in _CASES],
)
def test_auditlogsanitizer_redacts_pii(case_id: str, payload: Any, forbidden: str) -> None:
    model = AuditLogSanitizer(detail=payload, before=payload, after=payload)
    _assert_no_raw_leak(model.detail, forbidden)
    _assert_no_raw_leak(model.before, forbidden)
    _assert_no_raw_leak(model.after, forbidden)


def test_leaf_becomes_redaction_marker() -> None:
    out = sanitize_value({"email": _EMAIL})
    _assert_is_redaction(out["email"])


def test_non_pii_string_is_unchanged() -> None:
    payload = {"event": "member_added", "count": 3, "flag": True, "empty": ""}
    out = sanitize_value(payload)
    assert out == payload


def test_user_id_uuid_is_not_redacted() -> None:
    # FR-091a §c: raw UUID user_id values are permitted.
    uuid_val = "11111111-2222-3333-4444-555555555555"
    out = sanitize_value({"owner_id": uuid_val})
    assert out["owner_id"] == uuid_val


def test_sanitizer_handles_null_before_after() -> None:
    model = AuditLogSanitizer(detail={"ok": True}, before=None, after=None)
    assert model.before is None
    assert model.after is None


def test_sanitizer_rejects_non_dict_detail() -> None:
    with pytest.raises(ValidationError):
        AuditLogSanitizer(detail="not-a-dict")  # type: ignore[arg-type]


def test_sanitizer_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AuditLogSanitizer(detail={}, extra_field="x")  # type: ignore[call-arg]


def test_sanitized_output_is_json_serialisable() -> None:
    payload = {"emails": [_EMAIL, "b@example.org"], "note": "hello"}
    out = sanitize_value(payload)
    # Must round-trip through JSON so it can be stored in JSONB.
    encoded = json.dumps(out)
    decoded = json.loads(encoded)
    _assert_no_raw_leak(decoded, _EMAIL)


# ---------------------------------------------------------------------------
# Phase 2.10 #3 — PII embedded in dict KEYS must also be redacted.
# Previously the sanitizer only walked dict values; an attacker / buggy
# caller passing PII in the key position bypassed the guard entirely.
# ---------------------------------------------------------------------------


def _assert_no_raw_key_leak(tree: Any, forbidden: str) -> None:
    """Walk the structure and fail if ``forbidden`` appears in any KEY."""

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str):
                    assert forbidden not in k, (
                        f"raw PII leak in dict KEY: {forbidden!r} found in {k!r}"
                    )
                _walk(v)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(tree)


def test_redacts_top_level_email_key() -> None:
    """An email used as a top-level dict key must be replaced with a marker."""
    payload = {_EMAIL: {"role": "admin"}}
    out = sanitize_value(payload)
    assert _EMAIL not in out
    _assert_no_raw_key_leak(out, _EMAIL)
    # Marker must follow the documented shape.
    assert any(k.startswith("__redacted_key_") for k in out)
    # The value (which is itself non-PII) is preserved.
    marker_key = next(k for k in out if k.startswith("__redacted_key_"))
    assert out[marker_key] == {"role": "admin"}


def test_redacts_nested_dict_key_with_email() -> None:
    """PII keys at any depth must be redacted."""
    payload = {"audit": {"contacts": {_EMAIL: "primary"}}}
    out = sanitize_value(payload)
    _assert_no_raw_key_leak(out, _EMAIL)
    inner = out["audit"]["contacts"]
    assert _EMAIL not in inner
    assert any(k.startswith("__redacted_key_") for k in inner)


def test_redacts_url_encoded_key() -> None:
    """URL-encoded PII key must be caught by the URL-decode pass."""
    encoded = "alice%40example.com"
    payload = {encoded: "value"}
    out = sanitize_value(payload)
    _assert_no_raw_key_leak(out, encoded)
    assert encoded not in out
    assert any(k.startswith("__redacted_key_") for k in out)


def test_redacts_base64_encoded_key() -> None:
    """Base64-encoded PII key must be caught by the base64-decode pass."""
    import base64 as _b64

    encoded = _b64.b64encode(_EMAIL.encode()).decode()
    payload = {encoded: "value"}
    out = sanitize_value(payload)
    _assert_no_raw_key_leak(out, encoded)
    assert encoded not in out
    assert any(k.startswith("__redacted_key_") for k in out)


def test_redacts_both_key_and_value_when_both_are_pii() -> None:
    """PII in both key AND value must yield a marker key + redaction marker value."""
    other_email = "bob@example.org"
    payload = {_EMAIL: other_email}
    out = sanitize_value(payload)
    _assert_no_raw_key_leak(out, _EMAIL)
    _assert_no_raw_leak(out, _EMAIL)
    _assert_no_raw_leak(out, other_email)
    assert _EMAIL not in out
    marker_key = next(k for k in out if k.startswith("__redacted_key_"))
    # Value is replaced with the standard redaction dict marker.
    _assert_is_redaction(out[marker_key])


def test_redacted_key_marker_is_stable_for_same_input() -> None:
    """Two payloads with the same PII key produce the same marker (cardinality)."""
    out_a = sanitize_value({_EMAIL: 1})
    out_b = sanitize_value({_EMAIL: 2})
    marker_a = next(k for k in out_a if k.startswith("__redacted_key_"))
    marker_b = next(k for k in out_b if k.startswith("__redacted_key_"))
    assert marker_a == marker_b


def test_non_pii_keys_are_preserved_verbatim() -> None:
    """Existing key-name semantics must not break for safe keys."""
    payload = {"event": "x", "count": 5, "nested": {"safe_key": "safe_value"}}
    out = sanitize_value(payload)
    assert out == payload


# ---------------------------------------------------------------------------
# Phase 2.10 #4 — keyed-hash redaction + HASH_VERSION == "v2"
# ---------------------------------------------------------------------------


def test_hash_version_is_v2_indicating_keyed_hash_migration() -> None:
    """HASH_VERSION bumped from v1 (unkeyed sha256, deprecated) to v2."""
    assert HASH_VERSION == "v2"


def test_redaction_hash_uses_injected_hash_fn_rather_than_default() -> None:
    """Explicit ``hash_fn`` overrides the (patched) default."""
    marker_bytes = b"override-key"

    def other_hash(value: str) -> str:
        return hashlib.sha256(marker_bytes + value.encode()).hexdigest()

    out = sanitize_value({"email": _EMAIL}, hash_fn=other_hash)
    _assert_is_redaction(out["email"])
    assert out["email"]["hash"] == other_hash(_EMAIL)
    # Explicit override must differ from the autouse fake.
    assert out["email"]["hash"] != _fake_keyed_hash(_EMAIL)


def test_redaction_hash_is_keyed_not_plain_sha256() -> None:
    """Plain sha256(email) must no longer appear in the redaction marker.

    The keyed hash uses a secret prepended to the message; the resulting
    digest is indistinguishable from random to an attacker who does not
    know the key, defeating dictionary attacks on low-entropy PII
    values.
    """
    out = sanitize_value({"email": _EMAIL})
    plain_digest = hashlib.sha256(_EMAIL.encode()).hexdigest()
    assert out["email"]["hash"] != plain_digest
    # Our autouse stub concatenates a specific test key; verify exact match.
    assert out["email"]["hash"] == _fake_keyed_hash(_EMAIL)


def test_pydantic_model_also_uses_keyed_hash() -> None:
    """AuditLogSanitizer runs via sanitize_value so keyed-hash propagates."""
    model = AuditLogSanitizer(detail={"email": _EMAIL})
    assert model.detail["email"]["hash"] == _fake_keyed_hash(_EMAIL)
    assert model.detail["email"]["hash_version"] == "v2"
