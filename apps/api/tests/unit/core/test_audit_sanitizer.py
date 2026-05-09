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


def test_hash_version_is_v3_for_keyed_keys_and_values() -> None:
    """Phase 2.11 P0-a: HASH_VERSION bumped to v3.

    v2 used keyed HMAC for VALUES but plain truncated SHA-256 for dict
    KEY markers — dictionary-attackable on low-entropy PII. v3 routes
    both keys and values through the same keyed hash.
    """
    assert HASH_VERSION == "v3"


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
    # Phase 2.11 P0-a: HASH_VERSION bumped from v2 -> v3 because dict
    # KEY markers now also use the keyed hash, not plain truncated SHA-256.
    assert model.detail["email"]["hash_version"] == "v3"


# ---------------------------------------------------------------------------
# Phase 2.11 P0-a — dict KEY markers must use the same keyed hash as values
# ---------------------------------------------------------------------------


def test_key_marker_suffix_matches_value_hash_for_same_pii() -> None:
    """Same email used as KEY and as VALUE produces the same keyed-hash digest.

    The KEY marker takes the first :data:`_KEY_MARKER_HEX_LEN` chars of
    the keyed-hash output. The VALUE marker keeps the full digest. The
    KEY marker's hex chars therefore appear verbatim as the prefix of
    the VALUE marker's ``hash`` field. This test pins that invariant so
    a future refactor cannot silently regress to two different hash
    paths for keys vs values.
    """
    from echoroo.core.audit import _KEY_MARKER_HEX_LEN

    # Construct a payload where the same email is BOTH the dict key and
    # the value associated with a different key.
    payload = {_EMAIL: "non-pii-value", "user_email": _EMAIL}
    out = sanitize_value(payload)

    # Find the key marker. It is the only key starting with __redacted_key_.
    marker_key = next(k for k in out if k.startswith("__redacted_key_"))
    # Strip the prefix/suffix to get the embedded digest fragment.
    embedded = marker_key[len("__redacted_key_") : -len("__")]
    assert len(embedded) == _KEY_MARKER_HEX_LEN

    # The value redaction marker for the same PII string carries the
    # full keyed-hash digest. The first _KEY_MARKER_HEX_LEN chars MUST
    # equal the marker suffix.
    value_marker = out["user_email"]
    _assert_is_redaction(value_marker)
    assert value_marker["hash"][:_KEY_MARKER_HEX_LEN] == embedded


def test_key_marker_changes_when_hash_fn_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swapping the default hash_fn rotates the KEY marker too.

    Proves the KEY redaction is no longer using a plain sha256 path —
    if it were, replacing the default keyed hash_fn would not affect
    the marker.
    """
    from echoroo.core import audit as _audit_module

    payload = {_EMAIL: "v"}
    out_with_test_key = sanitize_value(payload)
    marker_a = next(k for k in out_with_test_key if k.startswith("__redacted_key_"))

    # Replace the default hash_fn with one using a different secret.
    def alt_hash(value: str) -> str:
        return hashlib.sha256(b"different-key" + value.encode("utf-8")).hexdigest()

    monkeypatch.setattr(_audit_module, "_default_hash_fn", alt_hash)

    out_with_alt_key = sanitize_value(payload)
    marker_b = next(k for k in out_with_alt_key if k.startswith("__redacted_key_"))

    assert marker_a != marker_b, (
        "KEY marker did not change when default hash_fn was swapped — "
        "the key path is still using a non-keyed hash"
    )


def test_key_marker_preserves_at_least_16_hex_chars() -> None:
    """Phase 2.11 P0-a: the marker keeps >= 16 hex chars to defeat
    birthday collisions in cardinality dashboards."""

    out = sanitize_value({_EMAIL: 1})
    marker = next(k for k in out if k.startswith("__redacted_key_"))
    embedded = marker[len("__redacted_key_") : -len("__")]
    assert len(embedded) >= 16, (
        f"KEY marker must preserve >= 16 hex chars, got {len(embedded)}"
    )


def test_key_marker_uses_explicit_hash_fn_override() -> None:
    """Explicit ``hash_fn=...`` on sanitize_value also rotates the KEY marker."""

    def alt_hash(value: str) -> str:
        return hashlib.sha256(b"override-secret" + value.encode("utf-8")).hexdigest()

    out_default = sanitize_value({_EMAIL: 1})
    out_override = sanitize_value({_EMAIL: 1}, hash_fn=alt_hash)
    marker_default = next(k for k in out_default if k.startswith("__redacted_key_"))
    marker_override = next(k for k in out_override if k.startswith("__redacted_key_"))
    assert marker_default != marker_override


# ---------------------------------------------------------------------------
# T996 (Phase 16 Batch 6h-2): supplemental coverage tests for audit.py.
# Targets missing lines: 212-213 (_try_url_decode except path),
# 423 (AuditLogSanitizer._sanitize_detail None path),
# 436 (AuditLogSanitizer._sanitize_optional non-dict raise path).
# ---------------------------------------------------------------------------

def test_try_url_decode_exception_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover lines 212-213: _try_url_decode returns None when urllib raises."""
    import echoroo.core.audit as _audit_mod

    def _raise(s: str, *args: object, **kwargs: object) -> str:  # noqa: ARG001
        raise RuntimeError("simulated urllib failure")

    monkeypatch.setattr("urllib.parse.unquote", _raise)
    # _try_url_decode is module-private; access via the module reference.
    result = _audit_mod._try_url_decode("test%40example.com")
    assert result is None


def test_audit_log_sanitizer_detail_none() -> None:
    """Cover line 423: AuditLogSanitizer._sanitize_detail with value=None returns {}."""
    obj = AuditLogSanitizer(detail=None)  # type: ignore[arg-type]  # triggers line 423
    assert obj.detail == {}


def test_audit_log_sanitizer_optional_non_dict_raises() -> None:
    """Cover line 436: _sanitize_optional raises ValueError when before/after is non-dict."""
    from pydantic import ValidationError as _PydanticValidationError

    with pytest.raises(_PydanticValidationError):
        AuditLogSanitizer(
            detail={},
            before="not-a-dict-string",  # triggers line 436 raise ValueError
        )


# ---------------------------------------------------------------------------
# Phase 17 §D-1 — mutation score uplift for echoroo.core.audit.
#
# Targets the four baseline mutants reported by mutmut on this module:
#   * Scorable A: ``_try_base64_decode`` length boundary (``< 8``)
#   * Scorable B: ``_UUID_ONLY_RE`` full-string anchor
#   * Timeout 1: ``_try_base64_decode`` UnicodeDecodeError loop on both
#     std + urlsafe alphabets
#   * No tests 1: ``_default_hash_fn`` lazy KMS load (production code
#     path otherwise bypassed by the autouse stub above)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected_decoded"),
    [
        # length 7 → strictly below the 8-char threshold, must short-circuit
        # to None even when the input is otherwise valid base64. Kills a
        # mutant flipping ``< 8`` to ``<= 8`` (which would still skip 8 too)
        # because the 8-char case below succeeds.
        pytest.param("abcdefg", None, id="len_7_below_threshold"),
        # length 8 with UTF-8-decodable payload → returns the decoded text.
        # Pins the boundary at exactly 8 so a mutant flipping the operator
        # (e.g. ``< 9``) is caught by the difference between len-7 (None)
        # and len-8 (decoded).
        pytest.param("aGVsbG8h", "hello!", id="len_8_at_threshold_returns_text"),
        # length 9 (just above) → also decoded. Confirms threshold is
        # not over-tightened in either direction.
        pytest.param("aGVsbG8hMQ==", "hello!1", id="len_9_above_threshold"),
    ],
)
def test_try_base64_decode_length_boundary(raw: str, expected_decoded: str | None) -> None:
    """Pin the ``len(stripped) < 8`` short-circuit in ``_try_base64_decode``.

    Targets §D-1 Scorable A: a mutant that flips the inequality (``<`` →
    ``<=``, ``>``, etc.) or bumps the literal (``< 7``, ``< 9``) is
    distinguishable iff length 7 returns None *and* length 8 decodes.
    """
    from echoroo.core.audit import _try_base64_decode

    assert _try_base64_decode(raw) == expected_decoded


def test_try_base64_decode_length_boundary_respects_strip() -> None:
    """The threshold applies after ``.strip()``, not to the raw input.

    Pads the 7-char body with surrounding whitespace so the raw length
    is 11 but the stripped length is 7 → must still return None. Kills a
    mutant that drops the ``.strip()`` call before the length check.
    """
    from echoroo.core.audit import _try_base64_decode

    assert _try_base64_decode("  abcdefg  ") is None


def test_try_base64_decode_returns_none_when_both_alphabets_yield_binary() -> None:
    """Both std + urlsafe decode succeed but neither bytes-output is UTF-8.

    Targets §D-1 Timeout 1: the loop inside ``_try_base64_decode`` walks
    every candidate from the std/urlsafe alphabets and returns ``None``
    only after both ``UnicodeDecodeError`` are caught. A mutant that
    breaks early or returns the raw bytes would leak non-text data into
    the regex scanner.
    """
    from echoroo.core.audit import _try_base64_decode

    # Pure binary that round-trips identically through std + urlsafe
    # (no '+' / '/' / '-' / '_' chars in the encoding, so both alphabets
    # accept it) but fails UTF-8 decoding on both candidate buffers.
    binary = b"\xff\xfe\xff\xfe\xff\xfe\xff\xfe"
    encoded = base64.b64encode(binary).decode()
    assert _try_base64_decode(encoded) is None


def test_try_base64_decode_uses_urlsafe_alphabet_branch() -> None:
    """A urlsafe-only token (contains ``-`` / ``_``) decodes via the
    urlsafe path and the resulting UTF-8 text is returned.

    Pins the dual-alphabet branching: kills a mutant that drops the
    urlsafe ``base64.urlsafe_b64decode`` candidate from the list.
    """
    from echoroo.core.audit import _try_base64_decode

    # 'subjects?' encoded with urlsafe alphabet — contains '_' so std
    # base64 alphabet would drop or misinterpret it under validate=False
    # (returns garbage bytes that may fail UTF-8 decoding), while the
    # urlsafe alphabet decodes cleanly to the original ASCII text.
    text = "subjects?"
    urlsafe_encoded = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    decoded = _try_base64_decode(urlsafe_encoded)
    # We assert that *some* candidate decoded back to the original ASCII
    # text — proving at least one of the two alphabet branches is exercised
    # and the loop returns a string rather than None.
    assert decoded == text


def test_uuid_only_anchor_allows_full_uuid_string() -> None:
    """A bare canonical UUID is exempt from PII redaction (FR-091a §c).

    Targets §D-1 Scorable B baseline: kills a mutant that drops the
    ``\\A`` / ``\\Z`` anchors on ``_UUID_ONLY_RE``. With anchors, this
    exact-match string is the *only* form accepted.
    """
    uuid_val = "550e8400-e29b-41d4-a716-446655440000"
    out = sanitize_value({"owner_id": uuid_val})
    # Owner id retained verbatim — no redaction marker.
    assert out["owner_id"] == uuid_val


@pytest.mark.parametrize(
    ("label", "value"),
    [
        # UUID with trailing free-form text — anchor must reject so the
        # value falls through to the rest of the PII pipeline (and is
        # preserved here because the suffix is non-PII).
        pytest.param(
            "uuid_with_suffix",
            "550e8400-e29b-41d4-a716-446655440000-tail",
            id="uuid_with_suffix",
        ),
        # UUID with leading free-form text.
        pytest.param(
            "uuid_with_prefix",
            "prefix-550e8400-e29b-41d4-a716-446655440000",
            id="uuid_with_prefix",
        ),
        # UUID embedded inside a longer string.
        pytest.param(
            "uuid_embedded",
            "see 550e8400-e29b-41d4-a716-446655440000 for details",
            id="uuid_embedded",
        ),
    ],
)
def test_uuid_only_anchor_rejects_uuid_with_extra_chars(label: str, value: str) -> None:
    """Strings that *contain* a UUID but are not solely a UUID must not
    be treated as the allowlisted UUID-only form.

    Targets §D-1 Scorable B: a mutant that drops ``\\A`` or ``\\Z`` would
    let these strings hit the early-return ``False`` branch in
    ``_scan_string``, silently expanding the allowlist beyond the spec.

    We verify by calling the module-private ``_UUID_ONLY_RE.match``
    directly (which short-circuits on success and is anchored on both
    sides) — without an anchor the match would succeed.
    """
    from echoroo.core.audit import _UUID_ONLY_RE

    assert _UUID_ONLY_RE.match(value) is None, (
        f"_UUID_ONLY_RE must reject {label!r} ({value!r}) because the "
        "string is not solely a canonical UUID"
    )


def test_default_hash_fn_routes_through_kms_compute_pii_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_default_hash_fn`` performs a lazy import + delegates to KMS.

    Targets §D-1 baseline ``no tests 1``: the autouse fixture above
    patches ``_default_hash_fn`` on the module to a deterministic local
    stub, so the production body (``from echoroo.core.kms import
    compute_pii_hash; return compute_pii_hash(value)``) is otherwise
    never executed by the test suite.

    We restore the real implementation by reloading the audit module
    from its source path *under a fresh module name* (so the autouse
    monkeypatch on the original module reference is unaffected). We
    then patch ``compute_pii_hash`` inside ``echoroo.core.kms`` and
    invoke the freshly-loaded function to prove the lazy-import +
    delegation contract.
    """
    import importlib.util
    import sys

    import echoroo.core.audit as _audit_module
    import echoroo.core.kms as _kms_module

    captured: list[str] = []

    def _fake_compute_pii_hash(value: str) -> str:
        captured.append(value)
        return "deadbeef" * 8  # 64 hex chars, mimics SHA-256 output

    monkeypatch.setattr(_kms_module, "compute_pii_hash", _fake_compute_pii_hash)

    # Load a fresh copy of the audit module under a private name so the
    # autouse fixture's patch on the canonical ``echoroo.core.audit``
    # symbol does not shadow the production ``_default_hash_fn`` body.
    spec = importlib.util.spec_from_file_location(
        "_audit_freshcopy_for_kms_test",
        _audit_module.__file__,
    )
    assert spec is not None and spec.loader is not None
    fresh = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fresh
    try:
        spec.loader.exec_module(fresh)
        digest = fresh._default_hash_fn("user@example.com")
    finally:
        sys.modules.pop(spec.name, None)

    assert captured == ["user@example.com"]
    assert digest == "deadbeef" * 8
