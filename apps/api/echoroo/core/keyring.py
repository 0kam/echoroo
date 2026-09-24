"""Local keyring helpers for wrapping DEKs and computing keyed hashes."""

from __future__ import annotations

import base64
import binascii
import ctypes
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from echoroo.core.settings import get_settings

Purpose = Literal["totp-wrap", "pii-hmac", "audit-hmac"]

_PURPOSES = frozenset(("totp-wrap", "pii-hmac", "audit-hmac"))
_KEY_ID_PATTERN = re.compile(r"^[a-z0-9-]{1,64}$")
_CREATED_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEK_SIZE = 32
_NONCE_SIZE = 12
_TAG_SIZE = 16
_MAGIC = b"EKR"
_FORMAT_VERSION = 1
_AAD_PREFIX = b"echoroo:totp-wrap:"
_PR_SET_DUMPABLE = 4
_PR_GET_DUMPABLE = 3

# sha256(material) for material=sha256(("echoroo-dev-kms-fixed-material-v1:"+
# alias).encode()).digest(), as derived by the former local KMS seed script
# for alias/echoroo-totp-dek, alias/echoroo-invitation-hmac,
# alias/echoroo-pii-hash-hmac and alias/echoroo-audit-chain-hmac.
_PUBLIC_MATERIAL_DENYLIST = frozenset(
    {
        "91d6ec928022ade38371313810f752b77ba028120e0d1a64b44e88fbce6d0403",
        "6d0511b498a0ea00be98a48646108b753c2511bc5f0bfb321f155e868e0a4e7e",
        "33dfd2af6a29bbe7d0537e133b74c2dc165f048992707cc625f1900ad6ac31f2",
        "db60d61f9dfa2f8e3f5adc8b7d72b01d177222db93f47043a05edb2e8912f81f",
    }
)


class KeyringError(Exception):
    """Base error for the local keyring API."""


class KeyringConfigError(KeyringError):
    """The keyring file or its configuration is invalid."""


class KeyringKeyError(KeyringError):
    """A key is unknown or has the wrong purpose."""


class KeyringAuthError(KeyringError):
    """Authenticated keyring data could not be verified."""


@dataclass(frozen=True, slots=True)
class KeyEntry:
    """One validated keyring entry."""

    purpose: Purpose
    material: bytes = field(repr=False)
    created: str

    def __repr__(self) -> str:
        """Return a representation without key material."""

        return (
            f"KeyEntry(purpose={self.purpose!r}, created={self.created!r}, "
            f"fingerprint={hashlib.sha256(self.material).hexdigest()[:16]!r})"
        )


def _wipe(buffer: bytearray) -> None:
    """Overwrite a temporary byte buffer best effort."""

    for index in range(len(buffer)):
        buffer[index] = 0


def _validate_key_id(key_id: object, *, error_type: type[KeyringError]) -> str:
    if not isinstance(key_id, str) or _KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise error_type("key id has invalid syntax")
    return key_id


def _validate_created(created: object) -> str:
    if not isinstance(created, str) or _CREATED_PATTERN.fullmatch(created) is None:
        raise KeyringConfigError("key creation date is invalid")
    try:
        date.fromisoformat(created)
    except ValueError as exc:
        raise KeyringConfigError("key creation date is invalid") from exc
    return created


def _validate_purpose(purpose: object) -> Purpose:
    if not isinstance(purpose, str) or purpose not in _PURPOSES:
        raise KeyringConfigError("key purpose is unknown")
    return cast(Purpose, purpose)


def _decode_material(value: object) -> bytes:
    if not isinstance(value, str):
        raise KeyringConfigError("key material is invalid")
    try:
        material = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise KeyringConfigError("key material is invalid") from exc
    if len(material) != _DEK_SIZE:
        raise KeyringConfigError("key material is invalid")
    return material


@dataclass(frozen=True, slots=True, init=False)
class Keyring:
    """Immutable collection of validated named 256-bit keys."""

    _entries: Mapping[str, KeyEntry] = field(repr=False)

    def __init__(self, document: Mapping[str, object]) -> None:
        parsed = self._parse_document(document)
        object.__setattr__(self, "_entries", parsed)

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> Keyring:
        """Parse and validate a JSON-compatible keyring document."""

        return cls(document)

    @classmethod
    def from_json(cls, document: str | bytes) -> Keyring:
        """Parse and validate a JSON keyring document."""

        try:
            value = json.loads(document)
        except (TypeError, ValueError) as exc:
            raise KeyringConfigError("keyring JSON is invalid") from exc
        if not isinstance(value, Mapping):
            raise KeyringConfigError("keyring JSON must be an object")
        return cls(value)

    @classmethod
    def _from_entries(cls, entries: Mapping[str, KeyEntry]) -> Keyring:
        document: dict[str, object] = {
            "format": 1,
            "keys": {
                key_id: {
                    "purpose": entry.purpose,
                    "material": base64.b64encode(entry.material).decode("ascii"),
                    "created": entry.created,
                }
                for key_id, entry in entries.items()
            },
        }
        return cls(document)

    @staticmethod
    def _parse_document(document: Mapping[str, object]) -> Mapping[str, KeyEntry]:
        if not isinstance(document, Mapping):
            raise KeyringConfigError("keyring document must be an object")
        format_value = document.get("format")
        if (
            not isinstance(format_value, int)
            or isinstance(format_value, bool)
            or format_value != _FORMAT_VERSION
        ):
            raise KeyringConfigError("keyring format is unsupported")
        raw_keys = document.get("keys")
        if not isinstance(raw_keys, Mapping):
            raise KeyringConfigError("keyring keys must be an object")

        entries: dict[str, KeyEntry] = {}
        materials: set[bytes] = set()
        for raw_key_id, raw_entry in raw_keys.items():
            key_id = _validate_key_id(raw_key_id, error_type=KeyringConfigError)
            if not isinstance(raw_entry, Mapping):
                raise KeyringConfigError("keyring entry is invalid")
            purpose = _validate_purpose(raw_entry.get("purpose"))
            material = _decode_material(raw_entry.get("material"))
            created = _validate_created(raw_entry.get("created"))
            if material in materials:
                raise KeyringConfigError("keyring contains shared key material")
            if hashlib.sha256(material).hexdigest() in _PUBLIC_MATERIAL_DENYLIST:
                raise KeyringConfigError("keyring contains public key material")
            materials.add(material)
            entries[key_id] = KeyEntry(purpose=purpose, material=material, created=created)
        return MappingProxyType(entries)

    @property
    def keys(self) -> Mapping[str, KeyEntry]:
        """Return the immutable key entries."""

        return self._entries

    @property
    def key_ids(self) -> tuple[str, ...]:
        """Return key ids in file order."""

        return tuple(self._entries)

    def __repr__(self) -> str:
        """Return a representation containing ids and safe fingerprints only."""

        fingerprints = {
            key_id: hashlib.sha256(entry.material).hexdigest()[:16]
            for key_id, entry in self._entries.items()
        }
        return f"Keyring(keys={fingerprints!r})"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-compatible copy of the keyring."""

        return {
            "format": 1,
            "keys": {
                key_id: {
                    "purpose": entry.purpose,
                    "material": base64.b64encode(entry.material).decode("ascii"),
                    "created": entry.created,
                }
                for key_id, entry in self._entries.items()
            },
        }

    def _entry(self, key_id: str) -> KeyEntry:
        try:
            return self._entries[key_id]
        except KeyError as exc:
            raise KeyringKeyError("unknown key id") from exc

    def _purpose_entry(self, key_id: str, purpose: Purpose) -> KeyEntry:
        _validate_key_id(key_id, error_type=KeyringKeyError)
        if purpose not in _PURPOSES:
            raise KeyringKeyError("key purpose is unknown")
        entry = self._entry(key_id)
        if entry.purpose != purpose:
            raise KeyringKeyError("key purpose does not match operation")
        return entry

    def fingerprint(self, key_id: str) -> str:
        """Return the first 16 hex characters of a key fingerprint."""

        entry = self._entry(_validate_key_id(key_id, error_type=KeyringKeyError))
        return hashlib.sha256(entry.material).hexdigest()[:16]

    def wrap(self, dek: bytes | bytearray, key_id: str) -> bytes:
        """Wrap one 32-byte DEK under a TOTP wrapping key."""

        entry = self._purpose_entry(key_id, "totp-wrap")
        if not isinstance(dek, (bytes, bytearray)) or len(dek) != _DEK_SIZE:
            raise KeyringAuthError("DEK must be exactly 32 bytes")

        plaintext = bytearray(dek)
        nonce = bytearray(os.urandom(_NONCE_SIZE))
        header = _header(key_id)
        try:
            encrypted = AESGCM(entry.material).encrypt(
                bytes(nonce), bytes(plaintext), _AAD_PREFIX + header
            )
            return header + bytes(nonce) + encrypted
        finally:
            _wipe(plaintext)
            _wipe(nonce)

    def unwrap(self, blob: bytes, expected_key_id: str) -> bytearray:
        """Unwrap a DEK and bind it to the expected key id."""

        expected_key_id = _validate_key_id(expected_key_id, error_type=KeyringKeyError)
        header, key_id, nonce, ciphertext = _parse_blob(blob)
        if key_id != expected_key_id:
            raise KeyringKeyError("wrapped key id does not match expected key id")
        entry = self._purpose_entry(key_id, "totp-wrap")
        try:
            plaintext = AESGCM(entry.material).decrypt(nonce, ciphertext, _AAD_PREFIX + header)
        except InvalidTag as exc:
            raise KeyringAuthError("wrapped DEK authentication failed") from exc
        if len(plaintext) != _DEK_SIZE:
            plaintext_buffer = bytearray(plaintext)
            _wipe(plaintext_buffer)
            raise KeyringAuthError("wrapped DEK has an invalid length")
        return bytearray(plaintext)

    def rewrap(self, blob: bytes, source_key_id: str, target_key_id: str) -> bytes:
        """Rewrap a DEK from one TOTP key to another."""

        self._purpose_entry(source_key_id, "totp-wrap")
        self._purpose_entry(target_key_id, "totp-wrap")
        dek = self.unwrap(blob, source_key_id)
        try:
            return self.wrap(dek, target_key_id)
        finally:
            _wipe(dek)

    def hmac_hex(self, key_id: str, message: bytes, purpose: Purpose) -> str:
        """Compute a lowercase HMAC-SHA256 hex digest."""

        entry = self._purpose_entry(key_id, purpose)
        if not isinstance(message, bytes):
            raise KeyringAuthError("HMAC message must be bytes")
        return hmac.new(entry.material, message, hashlib.sha256).hexdigest()

    def verify_hmac_hex(
        self, key_id: str, message: bytes, expected_hex: str, purpose: Purpose
    ) -> bool:
        """Verify a lowercase HMAC-SHA256 hex digest in constant time."""

        actual = self.hmac_hex(key_id, message, purpose)
        if not isinstance(expected_hex, str):
            return False
        return hmac.compare_digest(actual, expected_hex)


def _header(key_id: str) -> bytes:
    """Build the authenticated wrapped-DEK header."""

    key_id = _validate_key_id(key_id, error_type=KeyringKeyError)
    encoded = key_id.encode("ascii")
    return _MAGIC + bytes((_FORMAT_VERSION, len(encoded))) + encoded


def _parse_blob(blob: bytes) -> tuple[bytes, str, bytes, bytes]:
    if not isinstance(blob, bytes) or len(blob) < 5 + _NONCE_SIZE + _DEK_SIZE + _TAG_SIZE:
        raise KeyringAuthError("wrapped DEK has an invalid format")
    if blob[:3] != _MAGIC or blob[3] != _FORMAT_VERSION:
        raise KeyringAuthError("wrapped DEK header is invalid")
    key_id_length = blob[4]
    if key_id_length < 1 or key_id_length > 64:
        raise KeyringAuthError("wrapped DEK key id length is invalid")
    header_length = 5 + key_id_length
    expected_length = header_length + _NONCE_SIZE + _DEK_SIZE + _TAG_SIZE
    if len(blob) != expected_length:
        raise KeyringAuthError("wrapped DEK length is invalid")
    header = blob[:header_length]
    try:
        key_id = blob[5:header_length].decode("ascii")
    except UnicodeDecodeError as exc:
        raise KeyringAuthError("wrapped DEK key id is invalid") from exc
    if _KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise KeyringAuthError("wrapped DEK key id is invalid")
    nonce_start = header_length
    nonce = blob[nonce_start : nonce_start + _NONCE_SIZE]
    ciphertext = blob[nonce_start + _NONCE_SIZE :]
    return header, key_id, nonce, ciphertext


@dataclass(frozen=True, slots=True)
class Selectors:
    """Settings-selected key ids and TOTP versions."""

    totp_key: str | None = None
    totp_version: int = 1
    totp_key_old: str | None = None
    totp_version_old: int | None = None
    pii_key: str | None = None
    pii_key_v2: str | None = None
    audit_key: str | None = None

    def validate(self, keyring: Keyring) -> None:
        """Validate selected ids, purposes, versions and role conflicts."""

        if self.totp_key is None or not self.totp_key:
            raise KeyringConfigError("TOTP key selector is required")
        if self.pii_key is None or not self.pii_key:
            raise KeyringConfigError("PII key selector is required")
        if self.audit_key is None or not self.audit_key:
            raise KeyringConfigError("audit key selector is required")
        if (
            not isinstance(self.totp_version, int)
            or isinstance(self.totp_version, bool)
            or self.totp_version <= 0
        ):
            raise KeyringConfigError("TOTP key version must be positive")

        old_key_set = self.totp_key_old is not None
        old_version_set = self.totp_version_old is not None
        if old_key_set != old_version_set:
            raise KeyringConfigError("old TOTP key and version must be set together")
        if old_version_set and (
            not isinstance(self.totp_version_old, int)
            or isinstance(self.totp_version_old, bool)
            or self.totp_version_old <= 0
        ):
            raise KeyringConfigError("old TOTP key version must be positive")
        if old_version_set and self.totp_version_old == self.totp_version:
            raise KeyringConfigError("TOTP key versions must be distinct")

        selected: list[tuple[str, Purpose]] = [
            (self.totp_key, "totp-wrap"),
            (self.pii_key, "pii-hmac"),
            (self.audit_key, "audit-hmac"),
        ]
        if self.totp_key_old is not None:
            selected.append((self.totp_key_old, "totp-wrap"))
        if self.pii_key_v2 is not None:
            if not self.pii_key_v2:
                raise KeyringConfigError("PII v2 key selector must not be empty")
            selected.append((self.pii_key_v2, "pii-hmac"))

        seen: set[str] = set()
        for key_id, purpose in selected:
            if not key_id:
                raise KeyringConfigError("key selectors must not be empty")
            if key_id in seen:
                raise KeyringConfigError("a key id is selected for multiple roles")
            seen.add(key_id)
            validated_id = _validate_key_id(key_id, error_type=KeyringConfigError)
            keyring._purpose_entry(validated_id, purpose)


def load_keyring(path: str | os.PathLike[str]) -> Keyring:
    """Read, validate and return a keyring file."""

    keyring_path = Path(path)
    descriptor: int | None = None
    try:
        path_stat = keyring_path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            raise KeyringConfigError("keyring path must not be a symlink")
        if not stat.S_ISREG(path_stat.st_mode):
            raise KeyringConfigError("keyring path is not a regular file")
        if stat.S_IMODE(path_stat.st_mode) not in (0o400, 0o600):
            raise KeyringConfigError("keyring file mode must be 0400 or 0600")
        descriptor = os.open(keyring_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened_stat = os.fstat(descriptor)
        if stat.S_ISLNK(opened_stat.st_mode) or not stat.S_ISREG(opened_stat.st_mode):
            raise KeyringConfigError("keyring path is not a regular file")
        if stat.S_IMODE(opened_stat.st_mode) not in (0o400, 0o600):
            raise KeyringConfigError("keyring file mode must be 0400 or 0600")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    except KeyringConfigError:
        raise
    except OSError as exc:
        raise KeyringConfigError("keyring file is missing or unreadable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)

    try:
        return Keyring.from_json(b"".join(chunks))
    except KeyringConfigError:
        raise
    except Exception as exc:  # pragma: no cover - defensive parser boundary
        raise KeyringConfigError("keyring file is invalid") from exc


_KEYRING_CACHE: Keyring | None = None


def get_keyring() -> Keyring:
    """Load and cache the configured keyring."""

    global _KEYRING_CACHE
    if _KEYRING_CACHE is None:
        harden_process()
        _KEYRING_CACHE = load_keyring(get_settings().KEYRING_FILE)
    return _KEYRING_CACHE


def reset_cache() -> None:
    """Clear the process-local keyring cache."""

    global _KEYRING_CACHE
    _KEYRING_CACHE = None


def _prctl(option: int) -> int:
    """Call Linux ``prctl`` and return its result."""

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.argtypes = [
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        ]
        prctl.restype = ctypes.c_int
        return int(prctl(option, 0, 0, 0, 0))
    except (AttributeError, OSError) as exc:
        raise KeyringConfigError("process dumpability control is unavailable") from exc


def harden_process() -> None:
    """Disable Linux core dumps and same-UID ptrace access."""

    if not sys.platform.startswith("linux"):
        return
    if _prctl(_PR_SET_DUMPABLE) != 0:
        raise KeyringConfigError("could not disable process dumpability")


def is_dumpable() -> bool:
    """Return the Linux process dumpability flag."""

    if not sys.platform.startswith("linux"):
        return True
    value = _prctl(_PR_GET_DUMPABLE)
    if value < 0:
        raise KeyringConfigError("could not read process dumpability")
    return bool(value)


__all__ = [
    "KeyEntry",
    "Keyring",
    "KeyringAuthError",
    "KeyringConfigError",
    "KeyringError",
    "KeyringKeyError",
    "Purpose",
    "Selectors",
    "get_keyring",
    "harden_process",
    "is_dumpable",
    "load_keyring",
    "reset_cache",
]
