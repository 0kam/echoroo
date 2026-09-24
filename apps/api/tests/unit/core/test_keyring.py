"""Tests for the unused local keyring slice."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from echoroo.core import keyring


def _material(label: str) -> bytes:
    """Return deterministic non-public test material."""

    return hashlib.sha256(f"test-keyring:{label}".encode()).digest()


def _document(entries: dict[str, tuple[str, bytes, str | None]] | None = None) -> dict[str, object]:
    entries = entries or {
        "totp-wrap-current": ("totp-wrap", _material("totp-current"), None),
        "totp-wrap-old": ("totp-wrap", _material("totp-old"), None),
        "pii-hmac-current": ("pii-hmac", _material("pii-current"), None),
        "pii-hmac-v2": ("pii-hmac", _material("pii-v2"), None),
        "audit-hmac-current": ("audit-hmac", _material("audit-current"), None),
    }
    return {
        "format": 1,
        "keys": {
            key_id: {
                "purpose": purpose,
                "material": base64.b64encode(material).decode("ascii"),
                "created": created or "2026-09-24",
            }
            for key_id, (purpose, material, created) in entries.items()
        },
    }


@pytest.fixture
def ring() -> keyring.Keyring:
    """Return a complete test keyring."""

    return keyring.Keyring.from_dict(_document())


def _write_ring(path: Path, ring: keyring.Keyring, mode: int = 0o400) -> None:
    """Write one test ring with the production-readable mode."""

    path.write_text(json.dumps(ring.to_dict()), encoding="utf-8")
    path.chmod(mode)


def test_hmac_known_answer_and_verification(ring: keyring.Keyring) -> None:
    """HMAC matches hashlib's independent implementation and a fixed vector."""

    message = b"echoroo-keyring-known-answer"
    fixed_key = bytes(range(32))
    vector_ring = keyring.Keyring.from_dict(
        _document({"pii-fixed": ("pii-hmac", fixed_key, "2026-09-24")})
    )
    expected = "93ada1a10094224630069ec841618546b67802f9ee200afb9de45e9a426b376d"
    assert vector_ring.hmac_hex("pii-fixed", message, "pii-hmac") == expected
    assert (
        vector_ring.hmac_hex("pii-fixed", message, "pii-hmac")
        == hmac.new(fixed_key, message, hashlib.sha256).hexdigest()
    )
    assert vector_ring.verify_hmac_hex("pii-fixed", message, expected, "pii-hmac")
    assert not vector_ring.verify_hmac_hex("pii-fixed", message, "0" * 64, "pii-hmac")
    assert ring.hmac_hex("pii-hmac-current", b"message", "pii-hmac")


@pytest.mark.parametrize("expected_hex", ["é" * 64, "a" * 63, "a" * 65, "A" * 64, "g" * 64])
def test_malformed_hmacs_are_rejected(expected_hex: str, ring: keyring.Keyring) -> None:
    """Verification rejects non-canonical MAC strings before compare_digest."""

    assert not ring.verify_hmac_hex("pii-hmac-current", b"message", expected_hex, "pii-hmac")


def test_hmac_rejects_wrapping_purpose_for_compute_and_verify(ring: keyring.Keyring) -> None:
    """HMAC operations accept only their two dedicated purposes."""

    with pytest.raises(keyring.KeyringKeyError):
        ring.hmac_hex("totp-wrap-current", b"message", "totp-wrap")  # type: ignore[arg-type]
    with pytest.raises(keyring.KeyringKeyError):
        ring.verify_hmac_hex(
            "totp-wrap-current",
            b"message",
            "0" * 64,
            "totp-wrap",  # type: ignore[arg-type]
        )


def test_wrap_unwrap_and_rewrap(ring: keyring.Keyring) -> None:
    """Wrapped DEKs use the specified wire format and return bytearrays."""

    dek = b"D" * 32
    blob = ring.wrap(dek, "totp-wrap-current")
    assert blob[:3] == b"EKR"
    assert blob[3] == 1
    assert blob[4] == len("totp-wrap-current")
    unwrapped = ring.unwrap(blob, "totp-wrap-current")
    assert isinstance(unwrapped, bytearray)
    assert unwrapped == bytearray(dek)

    rewrapped = ring.rewrap(blob, "totp-wrap-current", "totp-wrap-old")
    assert ring.unwrap(rewrapped, "totp-wrap-old") == bytearray(dek)
    with pytest.raises(keyring.KeyringKeyError):
        ring.unwrap(rewrapped, "totp-wrap-current")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", 2),
        ("format", True),
        ("keys", []),
    ],
)
def test_document_rejects_bad_top_level(field: str, value: object) -> None:
    """Only format 1 and an object-valued key map are accepted."""

    document = _document()
    document[field] = value
    with pytest.raises(keyring.KeyringConfigError):
        keyring.Keyring.from_dict(document)


@pytest.mark.parametrize(
    "document",
    [
        '{"format":1,"format":1,"keys":{}}',
        (
            '{"format":1,"keys":{'
            '"duplicate-id":{"purpose":"pii-hmac","material":"'
            + base64.b64encode(_material("duplicate-id")).decode("ascii")
            + '","created":"2026-09-24"},'
            '"duplicate-id":{"purpose":"pii-hmac","material":"'
            + base64.b64encode(_material("duplicate-id-2")).decode("ascii")
            + '","created":"2026-09-24"}}}'
        ),
        (
            '{"format":1,"keys":{"entry":{"purpose":"pii-hmac","material":"'
            + base64.b64encode(_material("duplicate-field")).decode("ascii")
            + '","material":"'
            + base64.b64encode(_material("duplicate-field-2")).decode("ascii")
            + '","created":"2026-09-24"}}}'
        ),
    ],
)
def test_json_rejects_duplicate_members_at_each_nesting_level(document: str) -> None:
    """Duplicate top-level, key-map and entry members never get last-value wins."""

    with pytest.raises(keyring.KeyringConfigError, match="duplicate") as raised:
        keyring.Keyring.from_json(document)
    assert "duplicate-id" not in str(raised.value)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda document: document["keys"].update(
            {"Bad_id": document["keys"].pop("totp-wrap-current")}
        ),
        lambda document: document["keys"]["totp-wrap-current"].update({"purpose": "unknown"}),
        lambda document: document["keys"]["totp-wrap-current"].update({"material": "not-base64"}),
        lambda document: document["keys"]["totp-wrap-current"].update(
            {"material": base64.b64encode(b"short").decode("ascii")}
        ),
        lambda document: document["keys"]["totp-wrap-current"].update({"created": "not-a-date"}),
    ],
)
def test_document_rejects_bad_entries(mutator: object) -> None:
    """Entry id, purpose, material and creation-date validation is strict."""

    document = _document()
    mutator(document)  # type: ignore[operator]
    with pytest.raises(keyring.KeyringConfigError):
        keyring.Keyring.from_dict(document)


def test_shared_material_is_rejected() -> None:
    """Two ids may not carry the same material."""

    shared = _material("shared")
    document = _document(
        {
            "first": ("pii-hmac", shared, None),
            "second": ("audit-hmac", shared, None),
        }
    )
    with pytest.raises(keyring.KeyringConfigError, match="shared"):
        keyring.Keyring.from_dict(document)


@pytest.mark.parametrize(
    "alias",
    [
        "alias/echoroo-totp-dek",
        "alias/echoroo-invitation-hmac",
        "alias/echoroo-pii-hash-hmac",
        "alias/echoroo-audit-chain-hmac",
    ],
)
def test_public_material_is_rejected_under_any_id(alias: str) -> None:
    """Every former deterministic public key is denied, regardless of role."""

    material = hashlib.sha256(f"echoroo-dev-kms-fixed-material-v1:{alias}".encode()).digest()
    document = _document({"unselected-looking-id": ("pii-hmac", material, None)})
    with pytest.raises(keyring.KeyringConfigError, match="public"):
        keyring.Keyring.from_dict(document)


@pytest.mark.parametrize("key_id", ["", "UPPER", "with_under", "x" * 65, "contains space"])
def test_key_id_syntax_is_rejected(key_id: str) -> None:
    """Key ids use only the documented lowercase character set."""

    document = _document({key_id: ("pii-hmac", _material("bad-id"), None)})
    with pytest.raises(keyring.KeyringConfigError):
        keyring.Keyring.from_dict(document)


@pytest.mark.parametrize("offset", [0, 3])
def test_bad_magic_or_version_is_rejected(ring: keyring.Keyring, offset: int) -> None:
    """Magic and format version are authenticated parser inputs."""

    blob = bytearray(ring.wrap(b"D" * 32, "totp-wrap-current"))
    blob[offset] ^= 1
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(blob), "totp-wrap-current")


def test_wrapped_blob_rejections(ring: keyring.Keyring) -> None:
    """Invalid id, lengths, trailing data and unknown keys fail closed."""

    blob = ring.wrap(b"D" * 32, "totp-wrap-current")
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(blob[:-1], "totp-wrap-current")
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(blob + b"trailing", "totp-wrap-current")

    bad_id = bytearray(blob)
    bad_id[4] = 0
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(bad_id), "totp-wrap-current")

    oversized_id = bytearray(blob)
    oversized_id[4] = 65
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(oversized_id), "totp-wrap-current")

    invalid_id = bytearray(blob)
    invalid_id[5] = ord("_")
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(invalid_id), "totp-wrap-current")

    unknown_header = bytearray(blob)
    unknown_id = b"unknown-key-12345"
    unknown_header[4] = len(unknown_id)
    unknown_header[5 : 5 + len(unknown_id)] = unknown_id
    with pytest.raises(keyring.KeyringKeyError):
        ring.unwrap(bytes(unknown_header), unknown_id.decode("ascii"))


def test_fixed_nonce_wire_vector_uses_literal_aad(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wire format binds the literal header and AAD and returns a bytearray."""

    fixed_key = bytes(range(32))
    nonce = bytes(range(12))
    dek = b"D" * 32
    vector_ring = keyring.Keyring.from_dict(
        _document({"totp-fixed": ("totp-wrap", fixed_key, "2026-09-24")})
    )
    monkeypatch.setattr(keyring.os, "urandom", lambda _size: nonce)

    header = b"EKR\x01\ntotp-fixed"
    aad = b"echoroo:totp-wrap:EKR\x01\ntotp-fixed"
    expected = bytes.fromhex(
        "454b52010a746f74702d6669786564000102030405060708090a"
        "0b0346925f81a1865fc905d3cff5ad3c29c792c370b43f1b387c"
        "23a1c1592d44f6134292fedf26c6bf93c2ec05af3af48a"
    )
    assert expected == header + nonce + AESGCM(fixed_key).encrypt(nonce, dek, aad)
    assert vector_ring.wrap(dek, "totp-fixed") == expected
    unwrapped = vector_ring.unwrap(expected, "totp-fixed")
    assert isinstance(unwrapped, bytearray)
    assert unwrapped == bytearray(dek)


def test_header_nonce_and_ciphertext_tamper_fail_auth(ring: keyring.Keyring) -> None:
    """Tampering with authenticated data raises the auth error."""

    header_ring = keyring.Keyring.from_dict(
        _document(
            {
                "totp-wrap-current": ("totp-wrap", _material("header-current"), None),
                "totp-wrap-another": ("totp-wrap", _material("header-another"), None),
            }
        )
    )
    blob = bytearray(header_ring.wrap(b"D" * 32, "totp-wrap-current"))
    replacement = b"totp-wrap-another"
    blob[5 : 5 + len(replacement)] = replacement
    with pytest.raises(keyring.KeyringAuthError):
        header_ring.unwrap(bytes(blob), "totp-wrap-another")

    nonce_tampered = bytearray(ring.wrap(b"D" * 32, "totp-wrap-current"))
    nonce_tampered[5 + len("totp-wrap-current")] ^= 1
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(nonce_tampered), "totp-wrap-current")

    ciphertext_tampered = bytearray(ring.wrap(b"D" * 32, "totp-wrap-current"))
    ciphertext_tampered[-1] ^= 1
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(ciphertext_tampered), "totp-wrap-current")


def test_wrap_wipes_plaintext_when_nonce_generation_fails(
    ring: keyring.Keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nonce failure still wipes the plaintext copy allocated for the attempt."""

    observed: list[tuple[int, bytes]] = []
    original_wipe = keyring._wipe

    def observe_wipe(buffer: bytearray) -> None:
        original_wipe(buffer)
        observed.append((len(buffer), bytes(buffer)))

    def fail_nonce(_size: int) -> bytes:
        raise OSError("injected nonce failure")

    monkeypatch.setattr(keyring, "_wipe", observe_wipe)
    monkeypatch.setattr(keyring.os, "urandom", fail_nonce)
    with pytest.raises(OSError, match="nonce failure"):
        ring.wrap(b"D" * 32, "totp-wrap-current")

    assert (32, b"\0" * 32) in observed


def test_wrong_key_and_purpose_are_rejected(ring: keyring.Keyring) -> None:
    """Operations cannot use unknown, differently purposed, or mismatched ids."""

    with pytest.raises(keyring.KeyringKeyError):
        ring.wrap(b"D" * 32, "pii-hmac-current")
    with pytest.raises(keyring.KeyringKeyError):
        ring.hmac_hex("totp-wrap-current", b"message", "pii-hmac")
    blob = ring.wrap(b"D" * 32, "totp-wrap-current")
    with pytest.raises(keyring.KeyringKeyError):
        ring.unwrap(blob, "totp-wrap-old")
    with pytest.raises(keyring.KeyringKeyError):
        ring.unwrap(blob, "missing")


def test_selectors_validate_roles_versions_and_conflicts(ring: keyring.Keyring) -> None:
    """Selectors enforce role purposes, presence, pairing and uniqueness."""

    valid = keyring.Selectors(
        totp_key="totp-wrap-current",
        totp_version=2,
        totp_key_old="totp-wrap-old",
        totp_version_old=1,
        pii_key="pii-hmac-current",
        pii_key_v2="pii-hmac-v2",
        audit_key="audit-hmac-current",
    )
    valid.validate(ring)

    cases = [
        keyring.Selectors(pii_key="pii-hmac-current", audit_key="audit-hmac-current"),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            pii_key="totp-wrap-current",
            audit_key="audit-hmac-current",
        ),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            totp_key_old="totp-wrap-old",
            pii_key="pii-hmac-current",
            audit_key="audit-hmac-current",
        ),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            totp_version=0,
            pii_key="pii-hmac-current",
            audit_key="audit-hmac-current",
        ),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            totp_version=1,
            totp_key_old="totp-wrap-old",
            totp_version_old=1,
            pii_key="pii-hmac-current",
            audit_key="audit-hmac-current",
        ),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            pii_key="pii-hmac-current",
            pii_key_v2="totp-wrap-old",
            audit_key="audit-hmac-current",
        ),
    ]
    for selectors in cases:
        with pytest.raises(keyring.KeyringConfigError):
            selectors.validate(ring)


def test_file_loading_modes_and_symlinks(tmp_path: Path, ring: keyring.Keyring) -> None:
    """Only regular 0400/0600 files are loadable."""

    path = tmp_path / "ring.json"
    _write_ring(path, ring, 0o600)
    assert keyring.load_keyring(path).key_ids == ring.key_ids

    path.chmod(0o640)
    with pytest.raises(keyring.KeyringConfigError):
        keyring.load_keyring(path)

    path.chmod(0o400)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(keyring.KeyringConfigError):
        keyring.load_keyring(link)

    with pytest.raises(keyring.KeyringConfigError):
        keyring.load_keyring(tmp_path / "missing.json")


_SELECTOR_SETTINGS = {
    "KEYRING_TOTP_KEY": "totp-wrap-current",
    "KEYRING_TOTP_KEY_VERSION": 2,
    "KEYRING_TOTP_KEY_OLD": "totp-wrap-old",
    "KEYRING_TOTP_KEY_VERSION_OLD": 1,
    "KEYRING_PII_KEY": "pii-hmac-current",
    "KEYRING_PII_KEY_V2": None,
    "KEYRING_AUDIT_KEY": "audit-hmac-current",
}


def _use_settings(monkeypatch: pytest.MonkeyPatch, path: Path, **overrides: object) -> None:
    values = {"KEYRING_FILE": str(path), **_SELECTOR_SETTINGS, **overrides}
    monkeypatch.setattr(keyring, "get_settings", lambda: type("SettingsStub", (), values)())
    keyring.reset_cache()


def test_cache_can_be_reset(
    tmp_path: Path, ring: keyring.Keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module cache loads once and reset_cache permits a fresh load."""

    path = tmp_path / "ring.json"
    _write_ring(path, ring)
    _use_settings(monkeypatch, path)
    try:
        first = keyring.get_keyring()
        assert keyring.get_keyring() is first
        assert keyring.get_selectors().totp_key == "totp-wrap-current"
        keyring.reset_cache()
        assert keyring.get_keyring() is not first
    finally:
        keyring.reset_cache()


def test_get_keyring_validates_selectors(
    tmp_path: Path, ring: keyring.Keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loading refuses selectors that do not fit the ring, and caches nothing."""

    path = tmp_path / "ring.json"
    _write_ring(path, ring)
    _use_settings(monkeypatch, path, KEYRING_AUDIT_KEY="pii-hmac-v2")
    try:
        with pytest.raises(keyring.KeyringConfigError):
            keyring.get_keyring()
        with pytest.raises(keyring.KeyringConfigError):
            keyring.keyring_status()
    finally:
        keyring.reset_cache()


def test_keyring_status_describes_loaded_state_without_material(
    tmp_path: Path, ring: keyring.Keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status names selections and fingerprints; its state changes with the ring."""

    path = tmp_path / "ring.json"
    _write_ring(path, ring)
    _use_settings(monkeypatch, path)
    try:
        status = keyring.keyring_status()
        assert status["selected"] == {
            "totp": {
                "id": "totp-wrap-current",
                "fingerprint": ring.fingerprint("totp-wrap-current"),
            },
            "totp_old": {"id": "totp-wrap-old", "fingerprint": ring.fingerprint("totp-wrap-old")},
            "pii": {"id": "pii-hmac-current", "fingerprint": ring.fingerprint("pii-hmac-current")},
            "audit": {
                "id": "audit-hmac-current",
                "fingerprint": ring.fingerprint("audit-hmac-current"),
            },
        }
        assert status["totp_version"] == 2
        assert status["totp_version_old"] == 1
        assert status["key_ids"] == sorted(ring.key_ids)
        assert isinstance(status["state"], str) and len(status["state"]) == 16
        rendered = json.dumps(status)
        for entry in ring.keys.values():
            assert base64.b64encode(entry.material).decode("ascii") not in rendered
            assert entry.material.hex() not in rendered

        # A different selection (same ring) yields a different state.
        _use_settings(
            monkeypatch, path, KEYRING_TOTP_KEY_OLD=None, KEYRING_TOTP_KEY_VERSION_OLD=None
        )
        assert keyring.keyring_status()["state"] != status["state"]

        # The same selection over a ring with one more key yields a different state.
        document = _document()
        document["keys"]["pii-hmac-later"] = {  # type: ignore[index]
            "purpose": "pii-hmac",
            "material": base64.b64encode(_material("pii-later")).decode("ascii"),
            "created": "2026-09-24",
        }
        larger = tmp_path / "larger.json"
        _write_ring(larger, keyring.Keyring.from_dict(document))
        _use_settings(monkeypatch, larger)
        assert keyring.keyring_status()["state"] != status["state"]
    finally:
        keyring.reset_cache()


def test_harden_process_sets_not_dumpable() -> None:
    """Linux keyring processes disable dumpability."""

    if not sys.platform.startswith("linux"):
        pytest.skip("Linux prctl is not available")
    keyring.harden_process()
    assert not keyring.is_dumpable()


def test_errors_and_representations_are_secret_free(ring: keyring.Keyring) -> None:
    """Key material and plaintext never enter keyring errors or reprs."""

    material = _material("secret-check")
    plaintext = b"plaintext-dek-for-error-check" * 2
    encoded = base64.b64encode(material).decode("ascii")
    secret_ring = keyring.Keyring.from_dict(_document({"secret-key": ("pii-hmac", material, None)}))
    secret_entry = secret_ring.keys["secret-key"]
    errors: list[BaseException] = []
    for action in (
        lambda: keyring.Keyring.from_dict(_document({"bad_id": ("pii-hmac", material, None)})),
        lambda: ring.wrap(plaintext, "totp-wrap-current"),
        lambda: ring.wrap(b"D" * 32, "pii-hmac-current"),
        lambda: ring.unwrap(b"invalid", "totp-wrap-current"),
        lambda: ring.hmac_hex("totp-wrap-current", b"message", "pii-hmac"),
    ):
        with pytest.raises(keyring.KeyringError) as raised:
            action()
        errors.append(raised.value)

    for error in errors:
        assert encoded not in str(error)
        assert encoded not in repr(error)
        assert plaintext not in str(error).encode()
        assert plaintext not in repr(error).encode()
    for rendered in (repr(secret_ring), repr(secret_entry)):
        assert material not in rendered.encode()
        assert repr(material) not in rendered
        assert material.hex() not in rendered
        assert encoded not in rendered


def _entry(
    purpose: str = "totp-wrap", material: object = None, created: object = "2026-09-24"
) -> dict[str, object]:
    return {
        "purpose": purpose,
        "material": base64.b64encode(_material("entry")).decode("ascii")
        if material is None
        else material,
        "created": created,
    }


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"format": 1, "keys": {"totp-wrap-a": 1}},
        {"format": 1, "keys": {"totp-wrap-a": _entry(created="2026/09/24")}},
        {"format": 1, "keys": {"totp-wrap-a": _entry(created="2026-02-30")}},
        {"format": 1, "keys": {"totp-wrap-a": _entry(material=123)}},
        {"format": 1, "keys": {"totp-wrap-a": _entry(material="!!not-base64!!")}},
        {
            "format": 1,
            "keys": {"totp-wrap-a": _entry(material=base64.b64encode(b"x" * 16).decode("ascii"))},
        },
    ],
)
def test_document_rejections(document: object) -> None:
    """Malformed documents, entries, dates and materials are configuration errors."""

    with pytest.raises(keyring.KeyringConfigError):
        keyring.Keyring.from_dict(document)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["{", "[]", b"\xff\xfe"])
def test_json_rejections(raw: str | bytes) -> None:
    with pytest.raises(keyring.KeyringConfigError):
        keyring.Keyring.from_json(raw)


def test_operation_input_rejections(ring: keyring.Keyring) -> None:
    """Unknown purposes, non-bytes messages and undecodable ids are rejected."""

    with pytest.raises(keyring.KeyringKeyError):
        ring._purpose_entry("totp-wrap-current", "bogus")  # type: ignore[arg-type]
    with pytest.raises(keyring.KeyringAuthError):
        ring.hmac_hex("pii-hmac-current", "text", "pii-hmac")  # type: ignore[arg-type]

    header = b"EKR\x01" + bytes([2]) + b"\xff\xfe"
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(header + b"\x00" * 12 + b"\x00" * 48, "totp-wrap-current")


def test_unwrap_rejects_authenticated_dek_of_wrong_length(ring: keyring.Keyring) -> None:
    """A correctly authenticated blob whose plaintext is not 32 bytes is refused."""

    key_id = "totp-wrap-current"
    header = b"EKR\x01" + bytes([len(key_id)]) + key_id.encode("ascii")
    nonce = b"\x01" * 12
    ciphertext = AESGCM(_material("totp-current")).encrypt(
        nonce, b"x" * 16, b"echoroo:totp-wrap:" + header
    )
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(header + nonce + ciphertext, key_id)


@pytest.mark.parametrize(
    "selectors",
    [
        keyring.Selectors(totp_key="totp-wrap-current", audit_key="audit-hmac-current"),
        keyring.Selectors(totp_key="totp-wrap-current", pii_key="pii-hmac-current"),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            totp_key_old="totp-wrap-old",
            totp_version_old=0,
            pii_key="pii-hmac-current",
            audit_key="audit-hmac-current",
        ),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            pii_key="pii-hmac-current",
            pii_key_v2="",
            audit_key="audit-hmac-current",
        ),
        keyring.Selectors(
            totp_key="totp-wrap-current",
            totp_key_old="",
            totp_version_old=2,
            pii_key="pii-hmac-current",
            audit_key="audit-hmac-current",
        ),
    ],
)
def test_selector_rejections(ring: keyring.Keyring, selectors: keyring.Selectors) -> None:
    with pytest.raises(keyring.KeyringConfigError):
        selectors.validate(ring)


def test_load_rejects_non_regular_files_and_opened_file_changes(
    tmp_path: Path, ring: keyring.Keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directories are refused, and the opened descriptor is re-checked."""

    with pytest.raises(keyring.KeyringConfigError):
        keyring.load_keyring(tmp_path)

    path = tmp_path / "ring.json"
    _write_ring(path, ring)
    real_fstat = keyring.os.fstat

    def _fstat_with_mode(mode: int) -> object:
        def _fake(descriptor: int) -> object:
            result = real_fstat(descriptor)
            values = list(result)
            values[0] = mode
            return keyring.os.stat_result(values)

        return _fake

    monkeypatch.setattr(keyring.os, "fstat", _fstat_with_mode(0o040700))
    with pytest.raises(keyring.KeyringConfigError):
        keyring.load_keyring(path)
    monkeypatch.setattr(keyring.os, "fstat", _fstat_with_mode(0o100644))
    with pytest.raises(keyring.KeyringConfigError):
        keyring.load_keyring(path)


def test_dumpability_controls_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """prctl failures raise configuration errors; other platforms skip hardening."""

    def _no_libc(*_args: object, **_kwargs: object) -> object:
        raise OSError("no libc")

    monkeypatch.setattr(keyring.ctypes, "CDLL", _no_libc)
    with pytest.raises(keyring.KeyringConfigError):
        keyring._prctl(3)
    monkeypatch.undo()

    monkeypatch.setattr(keyring, "_prctl", lambda _option: -1)
    monkeypatch.setattr(keyring.sys, "platform", "linux")
    with pytest.raises(keyring.KeyringConfigError):
        keyring.harden_process()
    with pytest.raises(keyring.KeyringConfigError):
        keyring.is_dumpable()

    monkeypatch.setattr(keyring.sys, "platform", "darwin")
    keyring.harden_process()
    assert keyring.is_dumpable()
