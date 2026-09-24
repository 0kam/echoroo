"""Tests for the unused local keyring slice."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

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


def test_wrap_unwrap_and_rewrap(ring: keyring.Keyring) -> None:
    """Wrapped DEKs use the specified wire format and return bytearrays."""

    dek = b"D" * 32
    blob = ring.wrap(dek, "totp-wrap-current")
    assert blob[:3] == b"EKR"
    assert blob[3] == 1
    assert blob[4] == len("totp-wrap-current")
    assert ring.unwrap(blob, "totp-wrap-current") == bytearray(dek)

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
        ring.unwrap(blob + b"trailing", "totp-wrap-current")

    bad_id = bytearray(blob)
    bad_id[4] = 0
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(bad_id), "totp-wrap-current")

    unknown_header = bytearray(blob)
    unknown_id = b"unknown-key-12345"
    unknown_header[4] = len(unknown_id)
    unknown_header[5 : 5 + len(unknown_id)] = unknown_id
    with pytest.raises(keyring.KeyringKeyError):
        ring.unwrap(bytes(unknown_header), "unknown-key")


def test_header_nonce_and_ciphertext_tamper_fail_auth(ring: keyring.Keyring) -> None:
    """Tampering with authenticated data raises the auth error."""

    blob = bytearray(ring.wrap(b"D" * 32, "totp-wrap-current"))
    blob[3] ^= 1
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(blob), "totp-wrap-current")

    nonce_tampered = bytearray(ring.wrap(b"D" * 32, "totp-wrap-current"))
    nonce_tampered[5 + len("totp-wrap-current")] ^= 1
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(nonce_tampered), "totp-wrap-current")

    ciphertext_tampered = bytearray(ring.wrap(b"D" * 32, "totp-wrap-current"))
    ciphertext_tampered[-1] ^= 1
    with pytest.raises(keyring.KeyringAuthError):
        ring.unwrap(bytes(ciphertext_tampered), "totp-wrap-current")


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
        with pytest.raises(keyring.KeyringError):
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


def test_cache_can_be_reset(
    tmp_path: Path, ring: keyring.Keyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The module cache loads once and reset_cache permits a fresh load."""

    path = tmp_path / "ring.json"
    _write_ring(path, ring)
    monkeypatch.setattr(
        keyring, "get_settings", lambda: type("SettingsStub", (), {"KEYRING_FILE": str(path)})()
    )
    keyring.reset_cache()
    try:
        first = keyring.get_keyring()
        assert keyring.get_keyring() is first
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
    assert encoded not in repr(ring)
    assert plaintext not in repr(ring).encode()
