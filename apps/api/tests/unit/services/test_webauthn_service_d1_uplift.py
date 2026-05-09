"""Phase 17 §D-1 mutation uplift for ``echoroo.services.webauthn_service``.

Baseline (PR #53 CI run 25592148927): 122 killed / 162 survived (43.0%).
Surviving mutant concentration:

* ``complete_authentication``  — 92 (57%)
* ``complete_registration``    — 30 (19%)
* ``_load_challenge``          — 21 (13%)
* ``begin_registration``       — 12  (7%)
* ``_delete_challenge``        —  4
* ``_redis``                   —  2
* ``_store_challenge``         —  1

These tests pin the load-bearing branches, kwargs, constants and boundaries
that mutmut's operators routinely flip:

* WebAuthn ``verify_*_response`` keyword arguments (challenge / origin /
  rp_id / public_key / sign_count==0 zero-trick).
* sign-counter monotonic comparison (``<=`` vs ``<``, ``!= 0`` vs ``== 0``).
* Redis key namespace / prefix ordering and TTL value.
* Challenge load decoding path (``bytes`` vs ``str`` vs ``None``).
* Audit ordering (verify-then-record), payload shape and replay branch.
* Credential descriptor / transport mapping and SPKI conversion path.

All tests use ``fakeredis.aioredis`` for the Redis layer and monkeypatch
the ``webauthn`` library symbols imported into ``webauthn_service`` so
mutations to ``verify_*_response`` argument passing surface as test
failures here rather than as a (much harder to detect) live ceremony
failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import fakeredis.aioredis
import pytest
from webauthn.authentication.verify_authentication_response import VerifiedAuthentication
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
)
from webauthn.helpers.structs import (
    AttestationFormat,
    AuthenticatorTransport,
    CredentialDeviceType,
    PublicKeyCredentialType,
)
from webauthn.registration.verify_registration_response import VerifiedRegistration

from echoroo.core.settings import get_settings
from echoroo.services import webauthn_service as webauthn_module
from echoroo.services.webauthn_service import (
    StoredCredential,
    WebAuthnChallengeNotFoundError,
    WebAuthnDuplicateCredentialError,
    WebAuthnError,
    WebAuthnReplayDetectedError,
    WebAuthnService,
    WebAuthnVerificationError,
)

# Capture the original ``_record_audit_event`` BEFORE the autouse fixture
# replaces it so the audit-merge contract test below can restore the real
# method and exercise the production merge body.
_ORIGINAL_RECORD_AUDIT_EVENT = WebAuthnService._record_audit_event

# ---------------------------------------------------------------------------
# Shared fixtures (mirror tests/unit/services/test_webauthn_service.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _settings_and_audit(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin RP id / name / origins / TTL and stub audit writer.

    The fixture clears ``get_settings`` cache on both setup and teardown so a
    monkeypatched env from one test cannot leak into the next via lru_cache.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("ECHOROO_WEBAUTHN_RP_ID", "example.com")
    monkeypatch.setenv("ECHOROO_WEBAUTHN_RP_NAME", "Echoroo Test")
    monkeypatch.setenv(
        "ECHOROO_WEBAUTHN_ORIGINS",
        "https://admin.example.com,http://localhost:3000",
    )
    monkeypatch.setenv("ECHOROO_WEBAUTHN_CHALLENGE_TTL_SECONDS", "300")

    async def no_audit(self: WebAuthnService, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", no_audit)
    yield
    # Drop the test-scoped settings cache after monkeypatch restores the env so
    # the next test re-reads the real environment, not our test values.
    get_settings.cache_clear()


@pytest.fixture
def redis() -> fakeredis.aioredis.FakeRedis:
    """Return a fresh fake Redis with response decoding enabled."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _registration_response(
    credential_id: bytes = b"credential-id",
    *,
    name: str | None = "YubiKey 5 NFC",
    transports: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal py_webauthn-shaped registration JSON payload."""
    encoded_id = bytes_to_base64url(credential_id)
    payload: dict[str, Any] = {
        "id": encoded_id,
        "rawId": encoded_id,
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(b"{}"),
            "attestationObject": bytes_to_base64url(b"attestation"),
            "transports": transports if transports is not None else ["usb", "nfc"],
        },
    }
    if name is not None:
        payload["name"] = name
    return payload


def _authentication_response(credential_id: bytes = b"credential-id") -> dict[str, Any]:
    """Build a minimal py_webauthn-shaped authentication JSON payload."""
    encoded_id = bytes_to_base64url(credential_id)
    return {
        "id": encoded_id,
        "rawId": encoded_id,
        "type": "public-key",
        "response": {
            "clientDataJSON": bytes_to_base64url(b"{}"),
            "authenticatorData": bytes_to_base64url(b"authenticator-data"),
            "signature": bytes_to_base64url(b"signature"),
        },
    }


def _verified_registration(
    *,
    credential_id: bytes = b"credential-id",
    public_key: bytes = b"public-key",
    sign_count: int = 1,
    aaguid: str = "00000000-0000-0000-0000-000000000000",
) -> VerifiedRegistration:
    """Build a stub VerifiedRegistration result."""
    return VerifiedRegistration(
        credential_id=credential_id,
        credential_public_key=public_key,
        sign_count=sign_count,
        aaguid=aaguid,
        fmt=AttestationFormat.PACKED,
        credential_type=PublicKeyCredentialType.PUBLIC_KEY,
        user_verified=True,
        attestation_object=b"attestation",
        credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
        credential_backed_up=False,
    )


def _verified_authentication(
    *,
    credential_id: bytes = b"credential-id",
    new_sign_count: int = 2,
) -> VerifiedAuthentication:
    """Build a stub VerifiedAuthentication result."""
    return VerifiedAuthentication(
        credential_id=credential_id,
        new_sign_count=new_sign_count,
        credential_device_type=CredentialDeviceType.SINGLE_DEVICE,
        credential_backed_up=False,
        user_verified=True,
    )


def _stored_credential(
    *,
    credential_id: bytes = b"credential-id",
    public_key: bytes = b"public-key",
    cose_public_key: bytes | None = None,
    sign_count: int = 1,
    transports: list[str] | None = None,
) -> StoredCredential:
    """Build a StoredCredential dict for tests."""
    payload: StoredCredential = {
        "credential_id": bytes_to_base64url(credential_id),
        "public_key": bytes_to_base64url(public_key),
        "sign_count": sign_count,
        "transports": transports if transports is not None else ["usb"],
        "aaguid": bytes_to_base64url(b"\x00" * 16),
        "name": "YubiKey 5 NFC",
        "registered_at": "2026-01-01T00:00:00Z",
        "last_used_at": None,
    }
    if cose_public_key is not None:
        payload["cose_public_key"] = bytes_to_base64url(cose_public_key)
    return payload


async def _seed_challenge(
    redis: fakeredis.aioredis.FakeRedis,
    key: str,
    challenge: bytes = b"challenge",
) -> None:
    """Pre-populate a base64url-encoded challenge under ``key``."""
    await redis.set(key, bytes_to_base64url(challenge), ex=300)


# ---------------------------------------------------------------------------
# Section A: redis key namespace / helpers (kills _redis / _store /
# _delete / _load / key-builder mutants)
# ---------------------------------------------------------------------------


def test_registration_key_uses_reg_namespace_prefix() -> None:
    """Registration Redis key MUST be ``webauthn:reg:<uuid>`` exactly."""
    user_id = UUID("11111111-1111-1111-1111-111111111111")
    assert WebAuthnService._registration_key(user_id) == f"webauthn:reg:{user_id}"


def test_authentication_key_uses_auth_namespace_prefix() -> None:
    """Authentication Redis key MUST be ``webauthn:auth:<uuid>`` exactly."""
    user_id = UUID("22222222-2222-2222-2222-222222222222")
    assert WebAuthnService._authentication_key(user_id) == f"webauthn:auth:{user_id}"


def test_registration_and_authentication_keys_differ_for_same_user() -> None:
    """Reg/auth namespaces never collide — separate ceremony channels."""
    user_id = uuid4()
    assert (
        WebAuthnService._registration_key(user_id)
        != WebAuthnService._authentication_key(user_id)
    )


def test_registration_key_changes_when_user_id_changes() -> None:
    """Different users MUST produce different registration keys."""
    a = WebAuthnService._registration_key(uuid4())
    b = WebAuthnService._registration_key(uuid4())
    assert a != b


@pytest.mark.asyncio
async def test_redis_lazy_loads_via_get_redis_connection_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_redis`` MUST hydrate via get_redis_connection when redis is None."""
    sentinel = fakeredis.aioredis.FakeRedis(decode_responses=True)

    async def _fake_get_conn() -> Any:
        return sentinel

    monkeypatch.setattr(webauthn_module, "get_redis_connection", _fake_get_conn)
    service = WebAuthnService(redis=None)
    resolved = await service._redis()
    assert resolved is sentinel
    assert service.redis is sentinel


@pytest.mark.asyncio
async def test_redis_returns_existing_handle_without_new_connection(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_redis`` MUST NOT call get_redis_connection if redis already set."""
    called = False

    async def _fake_get_conn() -> Any:
        nonlocal called
        called = True
        return fakeredis.aioredis.FakeRedis()

    monkeypatch.setattr(webauthn_module, "get_redis_connection", _fake_get_conn)
    service = WebAuthnService(redis)
    resolved = await service._redis()
    assert resolved is redis
    assert called is False


@pytest.mark.asyncio
async def test_store_challenge_writes_base64url_value_under_key(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_store_challenge`` writes base64url-encoded payload at ``key``."""
    service = WebAuthnService(redis)
    challenge = b"raw-challenge-bytes"
    await service._store_challenge("webauthn:reg:K", challenge)
    stored = await redis.get("webauthn:reg:K")
    assert stored == bytes_to_base64url(challenge)


@pytest.mark.asyncio
async def test_store_challenge_sets_ttl_from_settings(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_store_challenge`` TTL MUST be the configured value (300s).

    Asserted to within the smallest tolerance that survives fakeredis clock
    granularity (an off-by-one TTL mutant changes 300 -> 299/301 outside the
    accepted set, while clock skew during a sub-second test stays inside it).
    """
    service = WebAuthnService(redis)
    await service._store_challenge("webauthn:reg:T", b"x")
    ttl = await redis.ttl("webauthn:reg:T")
    # Production sets ex=settings.webauthn_challenge_ttl_seconds (=300).
    # fakeredis may report 300 or 299 depending on its quantization.
    assert ttl in {299, 300}


@pytest.mark.asyncio
async def test_store_challenge_wraps_redis_failure_as_webauthn_error() -> None:
    """``_store_challenge`` re-raises any exception as WebAuthnError."""

    class Boom:
        async def set(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("set kaboom")

    service = WebAuthnService(Boom())  # type: ignore[arg-type]
    with pytest.raises(WebAuthnError, match="Redis challenge state"):
        await service._store_challenge("k", b"v")


@pytest.mark.asyncio
async def test_load_challenge_returns_decoded_bytes_for_str_value(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_load_challenge`` decodes a base64url ``str`` to raw bytes."""
    service = WebAuthnService(redis)
    raw = b"hello-challenge"
    await redis.set("k", bytes_to_base64url(raw))
    out = await service._load_challenge("k", user_id=uuid4())
    assert out == raw


@pytest.mark.asyncio
async def test_load_challenge_decodes_bytes_value_via_ascii() -> None:
    """``_load_challenge`` decodes ``bytes`` payload via ASCII first."""

    raw = b"abc-bytes-challenge"

    class BytesGetter:
        async def get(self, _name: str) -> bytes:
            return bytes_to_base64url(raw).encode("ascii")

    service = WebAuthnService(BytesGetter())  # type: ignore[arg-type]
    out = await service._load_challenge("k", user_id=uuid4())
    assert out == raw


@pytest.mark.asyncio
async def test_load_challenge_raises_not_found_when_value_is_none(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_load_challenge`` MUST raise ChallengeNotFound on missing key."""
    service = WebAuthnService(redis)
    with pytest.raises(WebAuthnChallengeNotFoundError):
        await service._load_challenge("absent-key", user_id=uuid4())


@pytest.mark.asyncio
async def test_load_challenge_does_not_swallow_explicit_none() -> None:
    """``None`` from ``redis.get`` MUST hit the missing-challenge branch."""

    class NoneGetter:
        async def get(self, _name: str) -> None:
            return None

    service = WebAuthnService(NoneGetter())  # type: ignore[arg-type]
    with pytest.raises(WebAuthnChallengeNotFoundError):
        await service._load_challenge("k", user_id=uuid4())


@pytest.mark.asyncio
async def test_load_challenge_wraps_get_failure_as_webauthn_error() -> None:
    """Redis GET errors propagate as WebAuthnError, not as raw exception."""

    class Boom:
        async def get(self, _name: str) -> Any:
            raise ConnectionError("get boom")

    service = WebAuthnService(Boom())  # type: ignore[arg-type]
    with pytest.raises(WebAuthnError, match="Redis challenge state"):
        await service._load_challenge("k", user_id=uuid4())


@pytest.mark.asyncio
async def test_delete_challenge_removes_key(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_delete_challenge`` removes the exact key from Redis."""
    service = WebAuthnService(redis)
    await redis.set("kkk", "v")
    await service._delete_challenge("kkk")
    assert await redis.get("kkk") is None


@pytest.mark.asyncio
async def test_delete_challenge_only_targets_named_key(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_delete_challenge`` does not affect unrelated keys."""
    service = WebAuthnService(redis)
    await redis.set("a", "1")
    await redis.set("b", "2")
    await service._delete_challenge("a")
    assert await redis.get("a") is None
    assert await redis.get("b") == "2"


@pytest.mark.asyncio
async def test_delete_challenge_wraps_failure_as_webauthn_error() -> None:
    """``_delete_challenge`` re-raises Redis errors as WebAuthnError."""

    class Boom:
        async def delete(self, *_args: Any) -> int:
            raise RuntimeError("delete kaboom")

    service = WebAuthnService(Boom())  # type: ignore[arg-type]
    with pytest.raises(WebAuthnError, match="Redis challenge state"):
        await service._delete_challenge("k")


# ---------------------------------------------------------------------------
# Section B: begin_registration (12 surviving mutants)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_begin_registration_passes_rp_id_rp_name_and_user_email_to_options(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``begin_registration`` MUST forward exact RP id / name / user fields."""
    spy: dict[str, Any] = {}
    real = webauthn_module.generate_registration_options

    def _spy_options(**kwargs: Any) -> Any:
        spy.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(webauthn_module, "generate_registration_options", _spy_options)

    user_id = uuid4()
    service = WebAuthnService(redis)
    await service.begin_registration(
        user_id=user_id,
        user_email="alice@example.com",
        existing_credentials=[],
    )

    assert spy["rp_id"] == "example.com"
    assert spy["rp_name"] == "Echoroo Test"
    assert spy["user_name"] == "alice@example.com"
    assert spy["user_display_name"] == "alice@example.com"
    assert spy["user_id"] == user_id.bytes


@pytest.mark.asyncio
async def test_begin_registration_excludes_each_existing_credential(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Existing credentials are forwarded as ``exclude_credentials`` 1:1."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    creds = [
        _stored_credential(credential_id=b"a"),
        _stored_credential(credential_id=b"b"),
    ]
    options = await service.begin_registration(
        user_id=user_id,
        user_email="x@example.com",
        existing_credentials=creds,
    )
    assert options.exclude_credentials is not None
    descriptor_ids = [d.id for d in options.exclude_credentials]
    assert descriptor_ids == [
        base64url_to_bytes(creds[0]["credential_id"]),
        base64url_to_bytes(creds[1]["credential_id"]),
    ]


@pytest.mark.asyncio
async def test_begin_registration_persists_challenge_under_registration_key(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``begin_registration`` writes challenge under ``webauthn:reg:<uuid>``."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    options = await service.begin_registration(
        user_id=user_id,
        user_email="alice@example.com",
        existing_credentials=[],
    )
    stored = await redis.get(f"webauthn:reg:{user_id}")
    assert stored is not None
    assert base64url_to_bytes(stored) == options.challenge


@pytest.mark.asyncio
async def test_begin_registration_does_not_write_authentication_key(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``begin_registration`` MUST NOT touch the auth namespace."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await service.begin_registration(
        user_id=user_id,
        user_email="x@example.com",
        existing_credentials=[],
    )
    assert await redis.get(f"webauthn:auth:{user_id}") is None


@pytest.mark.asyncio
async def test_begin_registration_records_audit_event_with_excluded_count(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Audit event payload contains exact existing-credential count."""
    captured: dict[str, Any] = {}

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)
    service = WebAuthnService(redis)
    user_id = uuid4()
    await service.begin_registration(
        user_id=user_id,
        user_email="x@example.com",
        existing_credentials=[
            _stored_credential(credential_id=b"a"),
            _stored_credential(credential_id=b"b"),
            _stored_credential(credential_id=b"c"),
        ],
    )
    assert captured["actor_id"] == user_id
    assert captured["action"] == "webauthn.registration_started"
    assert captured["detail"] == {"excluded_credentials": 3}


@pytest.mark.asyncio
async def test_begin_registration_zero_existing_credentials_audits_zero(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """0 existing creds MUST audit ``excluded_credentials=0`` exactly."""
    captured: dict[str, Any] = {}

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)
    service = WebAuthnService(redis)
    await service.begin_registration(
        user_id=uuid4(),
        user_email="x@example.com",
        existing_credentials=[],
    )
    assert captured["detail"] == {"excluded_credentials": 0}


# ---------------------------------------------------------------------------
# Section C: complete_registration (30 surviving mutants)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_registration_forwards_challenge_to_verify(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """The exact decoded challenge MUST reach verify_registration_response."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id), b"my-challenge")
    captured: dict[str, Any] = {}

    def _verify(**kwargs: Any) -> VerifiedRegistration:
        captured.update(kwargs)
        return _verified_registration()

    monkeypatch.setattr(webauthn_module, "verify_registration_response", _verify)
    monkeypatch.setattr(
        WebAuthnService,
        "_spki_public_key",
        staticmethod(lambda _cose_public_key: b"spki-public-key"),
    )

    await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    # Strict set equality on the kwargs surface so that any mutant which adds
    # / drops an argument (or smuggles in an extra kwarg) trips this test.
    assert set(captured.keys()) == {
        "credential",
        "expected_challenge",
        "expected_rp_id",
        "expected_origin",
    }
    assert captured["expected_challenge"] == b"my-challenge"
    assert captured["expected_rp_id"] == "example.com"
    assert captured["expected_origin"] == [
        "https://admin.example.com",
        "http://localhost:3000",
    ]


@pytest.mark.asyncio
async def test_complete_registration_returns_credential_id_base64url_of_verified_id(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """credential_id MUST equal base64url(verified.credential_id)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kw: _verified_registration(credential_id=b"my-cred-bytes"),
    )
    monkeypatch.setattr(
        WebAuthnService,
        "_spki_public_key",
        staticmethod(lambda _cose_public_key: b"spki"),
    )

    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(b"my-cred-bytes"),
        existing_credentials=[],
    )
    assert cred["credential_id"] == bytes_to_base64url(b"my-cred-bytes")


@pytest.mark.asyncio
async def test_complete_registration_stores_both_spki_and_cose_keys(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``public_key`` (SPKI) and ``cose_public_key`` MUST both be base64url."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kw: _verified_registration(public_key=b"COSE-RAW"),
    )
    monkeypatch.setattr(
        WebAuthnService,
        "_spki_public_key",
        staticmethod(lambda _cose: b"SPKI-DERIVED"),
    )

    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert cred["public_key"] == bytes_to_base64url(b"SPKI-DERIVED")
    assert cred["cose_public_key"] == bytes_to_base64url(b"COSE-RAW")
    assert cred["public_key"] != cred["cose_public_key"]


@pytest.mark.asyncio
async def test_complete_registration_preserves_sign_count_from_verified_struct(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """sign_count is verbatim from VerifiedRegistration, not coerced."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kw: _verified_registration(sign_count=42),
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert cred["sign_count"] == 42


@pytest.mark.asyncio
async def test_complete_registration_initializes_last_used_at_to_none(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A freshly registered credential MUST have ``last_used_at == None``."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert cred["last_used_at"] is None


@pytest.mark.asyncio
async def test_complete_registration_registered_at_is_iso_z(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``registered_at`` MUST be RFC3339 UTC ending in ``Z``."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert cred["registered_at"].endswith("Z")
    assert "+00:00" not in cred["registered_at"]


@pytest.mark.asyncio
async def test_complete_registration_uses_response_transports_not_request_inputs(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """transports come from the parsed credential response (usb,nfc here)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(transports=["usb", "nfc"]),
        existing_credentials=[],
    )
    assert set(cred["transports"]) == {"usb", "nfc"}


@pytest.mark.asyncio
async def test_complete_registration_falls_back_to_default_name_when_blank(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Empty / missing ``name`` MUST fall back to ``Security key``."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(name=None),
        existing_credentials=[],
    )
    assert cred["name"] == "Security key"


@pytest.mark.asyncio
async def test_complete_registration_uses_label_when_name_absent(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``label`` is honored as a fallback for credential name."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    payload = _registration_response(name=None)
    payload["label"] = "  Personal Yubi  "
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=payload,
        existing_credentials=[],
    )
    assert cred["name"] == "Personal Yubi"


@pytest.mark.asyncio
async def test_complete_registration_deletes_challenge_on_success(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """On success the registration challenge key MUST be deleted."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._registration_key(user_id)
    await _seed_challenge(redis, key)
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert await redis.get(key) is None


@pytest.mark.asyncio
async def test_complete_registration_keeps_challenge_when_duplicate_credential(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Duplicate credential rejection occurs BEFORE challenge deletion."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._registration_key(user_id)
    await _seed_challenge(redis, key)
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    with pytest.raises(WebAuthnDuplicateCredentialError):
        await service.complete_registration(
            user_id=user_id,
            registration_response=_registration_response(),
            existing_credentials=[_stored_credential()],
        )
    assert await redis.get(key) is not None


@pytest.mark.asyncio
async def test_complete_registration_audit_action_after_persistence_success(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Audit event ``webauthn.registration_completed`` MUST be emitted."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    captured: list[dict[str, Any]] = []

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)
    monkeypatch.setattr(
        webauthn_module, "verify_registration_response", lambda **_kw: _verified_registration()
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert captured[-1]["action"] == "webauthn.registration_completed"
    assert captured[-1]["actor_id"] == user_id
    assert captured[-1]["detail"]["credential_id"] == bytes_to_base64url(b"credential-id")


@pytest.mark.asyncio
async def test_complete_registration_aaguid_translates_uuid_to_base64url(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A canonical UUID aaguid MUST be base64url-encoded (16 bytes)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kw: _verified_registration(
            aaguid="11111111-1111-1111-1111-111111111111"
        ),
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert cred["aaguid"] == bytes_to_base64url(
        UUID("11111111-1111-1111-1111-111111111111").bytes
    )


@pytest.mark.asyncio
async def test_complete_registration_aaguid_passthrough_when_not_uuid(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Non-UUID aaguid value passes through unchanged."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kw: _verified_registration(aaguid="not-a-uuid"),
    )
    monkeypatch.setattr(
        WebAuthnService, "_spki_public_key", staticmethod(lambda _c: b"x")
    )
    cred = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )
    assert cred["aaguid"] == "not-a-uuid"


# ---------------------------------------------------------------------------
# Section D: complete_authentication (92 surviving — primary battlefield)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_authentication_forwards_challenge_origin_rpid_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Verify call MUST receive exact challenge / origin / rp_id values.

    Asserts the *complete* kwargs surface (set equality + value identity) so
    both extra-arg and missing-arg mutations on
    ``verify_authentication_response`` flip this test.
    """
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id), b"AUTH-C")
    captured: dict[str, Any] = {}

    def _verify(**kwargs: Any) -> VerifiedAuthentication:
        captured.update(kwargs)
        return _verified_authentication(new_sign_count=2)

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", _verify)
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[
            _stored_credential(sign_count=1, cose_public_key=b"COSEbytes"),
        ],
    )
    # Set equality pins the exact kwargs surface — a mutant adding/removing
    # any kwarg (e.g. injecting require_user_verification) trips this.
    assert set(captured.keys()) == {
        "credential",
        "expected_challenge",
        "expected_rp_id",
        "expected_origin",
        "credential_public_key",
        "credential_current_sign_count",
    }
    assert captured["expected_challenge"] == b"AUTH-C"
    assert captured["expected_rp_id"] == "example.com"
    assert captured["expected_origin"] == [
        "https://admin.example.com",
        "http://localhost:3000",
    ]
    assert captured["credential_public_key"] == b"COSEbytes"
    # The "zero trick" — the service intentionally forwards 0 so it can run
    # its own counter regression check after py_webauthn signature verify.
    assert captured["credential_current_sign_count"] == 0


@pytest.mark.asyncio
async def test_complete_authentication_passes_zero_for_current_sign_count(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``credential_current_sign_count`` MUST be ``0`` (zero-trick)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: dict[str, Any] = {}

    def _verify(**kwargs: Any) -> VerifiedAuthentication:
        captured.update(kwargs)
        return _verified_authentication(new_sign_count=99)

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", _verify)
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=42)],
    )
    assert captured["credential_current_sign_count"] == 0


@pytest.mark.asyncio
async def test_complete_authentication_passes_credential_public_key_bytes(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``credential_public_key`` MUST be derived from the stored credential."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: dict[str, Any] = {}

    def _verify(**kwargs: Any) -> VerifiedAuthentication:
        captured.update(kwargs)
        return _verified_authentication(new_sign_count=2)

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", _verify)
    cred = _stored_credential(cose_public_key=b"COSEbytes", sign_count=1)
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[cred],
    )
    assert captured["credential_public_key"] == b"COSEbytes"


@pytest.mark.asyncio
async def test_complete_authentication_falls_back_to_public_key_when_no_cose(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Without ``cose_public_key`` the verifier sees the legacy SPKI bytes."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: dict[str, Any] = {}

    def _verify(**kwargs: Any) -> VerifiedAuthentication:
        captured.update(kwargs)
        return _verified_authentication(new_sign_count=2)

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", _verify)
    cred = _stored_credential(public_key=b"LEGACY-SPKI", sign_count=1)
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[cred],
    )
    assert captured["credential_public_key"] == b"LEGACY-SPKI"


@pytest.mark.asyncio
async def test_complete_authentication_unknown_credential_audits_and_raises(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Unknown credential id MUST audit ``unknown_credential`` and reject."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: list[dict[str, Any]] = []

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)

    with pytest.raises(WebAuthnVerificationError, match="not registered"):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(b"unknown"),
            existing_credentials=[_stored_credential(credential_id=b"different")],
        )
    assert any(
        c["action"] == "webauthn.authentication_failed"
        and c["detail"]["reason"] == "unknown_credential"
        for c in captured
    )


@pytest.mark.asyncio
async def test_complete_authentication_malformed_response_audits_and_raises(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Malformed JSON MUST audit ``malformed_response`` and reject."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: list[dict[str, Any]] = []

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)

    def _raise(_payload: dict[str, Any]) -> Any:
        raise InvalidAuthenticationResponse("bad shape")

    monkeypatch.setattr(
        webauthn_module, "parse_authentication_credential_json", _raise
    )

    with pytest.raises(WebAuthnVerificationError, match="malformed"):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential()],
        )
    assert captured[-1]["action"] == "webauthn.authentication_failed"
    assert captured[-1]["detail"] == {"reason": "malformed_response"}


@pytest.mark.asyncio
async def test_complete_authentication_bad_signature_audits_verification_failed(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A failed signature MUST audit ``verification_failed``."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: list[dict[str, Any]] = []

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: (_ for _ in ()).throw(InvalidAuthenticationResponse("x")),
    )
    with pytest.raises(WebAuthnVerificationError, match="rejected"):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential()],
        )
    assert captured[-1]["action"] == "webauthn.authentication_failed"
    assert captured[-1]["detail"]["reason"] == "verification_failed"


@pytest.mark.parametrize(
    ("old_sc", "new_sc"),
    [
        (1, 1),  # equal -> regression
        (5, 4),  # decreased -> regression
        (10, 1),  # decreased big -> regression
    ],
)
@pytest.mark.asyncio
async def test_complete_authentication_replay_when_counter_not_strictly_greater(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
    old_sc: int,
    new_sc: int,
) -> None:
    """new <= old (and new != 0) MUST raise WebAuthnReplayDetectedError."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=new_sc),
    )
    with pytest.raises(WebAuthnReplayDetectedError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential(sign_count=old_sc)],
        )


@pytest.mark.parametrize(
    ("old_sc", "new_sc"),
    [
        (0, 1),
        (1, 2),
        (5, 6),
        (99, 100),
    ],
)
@pytest.mark.asyncio
async def test_complete_authentication_accepts_strictly_greater_counter(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
    old_sc: int,
    new_sc: int,
) -> None:
    """new > old MUST proceed (returns updated credential, no replay)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=new_sc),
    )
    updated = await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=old_sc)],
    )
    assert updated["sign_count"] == new_sc


@pytest.mark.parametrize(
    ("old_sign_count", "new_sign_count", "expected_replay"),
    [
        # Pure zero-counter authenticator (Yubico-style): both 0 -> accept.
        (0, 0, False),
        # Counter previously advanced but now reports 0: per WebAuthn spec the
        # service treats new == 0 as "no usable counter" -> accept (NOT replay).
        # This case is the load-bearing one that kills mutants flipping the
        # ``and new_sign_count != 0`` guard to ``or`` / dropping the clause.
        (5, 0, False),
        # Counter unchanged but non-zero: replay.
        (5, 5, True),
        # Counter increased by 1: accept.
        (5, 6, False),
        # Counter regressed but non-zero: replay.
        (5, 4, True),
    ],
)
@pytest.mark.asyncio
async def test_complete_authentication_zero_counter_and_boundary_cases(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
    old_sign_count: int,
    new_sign_count: int,
    expected_replay: bool,
) -> None:
    """Boundary table for the ``new <= old AND new != 0`` replay guard.

    Concentrates the comparison-direction / equality / zero-trick mutants in
    a single parametrized table so each branch flip is killed by at least
    one row.
    """
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=new_sign_count),
    )

    if expected_replay:
        with pytest.raises(WebAuthnReplayDetectedError):
            await service.complete_authentication(
                user_id=user_id,
                authentication_response=_authentication_response(),
                existing_credentials=[_stored_credential(sign_count=old_sign_count)],
            )
    else:
        updated = await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential(sign_count=old_sign_count)],
        )
        assert updated["sign_count"] == new_sign_count


@pytest.mark.asyncio
async def test_complete_authentication_replay_audit_payload_includes_old_and_new(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Replay audit MUST contain both ``old_sign_count`` and ``new_sign_count``."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: list[dict[str, Any]] = []

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=4),
    )
    with pytest.raises(WebAuthnReplayDetectedError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential(sign_count=10)],
        )
    last = captured[-1]
    assert last["action"] == "webauthn.replay_detected"
    assert last["detail"]["old_sign_count"] == 10
    assert last["detail"]["new_sign_count"] == 4


@pytest.mark.asyncio
async def test_complete_authentication_returns_copy_does_not_mutate_existing(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Returned credential MUST be a copy; original sign_count untouched."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=99),
    )
    original = _stored_credential(sign_count=1)
    updated = await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[original],
    )
    assert original["sign_count"] == 1
    assert updated["sign_count"] == 99
    assert updated is not original


@pytest.mark.asyncio
async def test_complete_authentication_last_used_at_set_to_iso_z_on_success(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``last_used_at`` MUST be ISO-Z timestamped on successful auth."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=2),
    )
    updated = await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=1)],
    )
    assert updated["last_used_at"] is not None
    assert updated["last_used_at"].endswith("Z")


@pytest.mark.asyncio
async def test_complete_authentication_deletes_challenge_only_on_success(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """The auth challenge MUST be deleted only on a non-replay success."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._authentication_key(user_id)
    await _seed_challenge(redis, key)
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=2),
    )
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=1)],
    )
    assert await redis.get(key) is None


@pytest.mark.asyncio
async def test_complete_authentication_keeps_challenge_when_replay(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A replay-detected attempt MUST NOT delete the challenge."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._authentication_key(user_id)
    await _seed_challenge(redis, key)
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=1),
    )
    with pytest.raises(WebAuthnReplayDetectedError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential(sign_count=5)],
        )
    assert await redis.get(key) is not None


@pytest.mark.asyncio
async def test_complete_authentication_keeps_challenge_when_unknown_credential(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Unknown credential MUST NOT delete the challenge."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._authentication_key(user_id)
    await _seed_challenge(redis, key)
    with pytest.raises(WebAuthnVerificationError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(b"unknown-id"),
            existing_credentials=[_stored_credential(credential_id=b"other")],
        )
    assert await redis.get(key) is not None


@pytest.mark.asyncio
async def test_complete_authentication_audit_completed_includes_credential_id_and_count(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Audit ``authentication_completed`` MUST include cred_id + new sc."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: list[dict[str, Any]] = []

    async def audit(self: WebAuthnService, **kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(WebAuthnService, "_record_audit_event", audit)
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=7),
    )
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=1)],
    )
    last = captured[-1]
    assert last["action"] == "webauthn.authentication_completed"
    assert last["detail"]["new_sign_count"] == 7
    assert last["detail"]["credential_id"] == bytes_to_base64url(b"credential-id")


@pytest.mark.asyncio
async def test_complete_authentication_uses_authentication_key_not_registration(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A challenge under reg key MUST NOT satisfy auth (separate namespaces)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    # Seed only registration key — auth must NOT find anything.
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kw: _verified_authentication(new_sign_count=2),
    )
    with pytest.raises(WebAuthnChallengeNotFoundError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential(sign_count=1)],
        )


@pytest.mark.asyncio
async def test_complete_authentication_picks_correct_credential_when_multiple_exist(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Among multiple stored creds the right one MUST be selected by id."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    captured: dict[str, Any] = {}

    def _verify(**kwargs: Any) -> VerifiedAuthentication:
        captured.update(kwargs)
        return _verified_authentication(new_sign_count=5)

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", _verify)

    creds: list[StoredCredential] = [
        _stored_credential(
            credential_id=b"first",
            cose_public_key=b"FIRST-COSE",
            sign_count=10,
        ),
        _stored_credential(
            credential_id=b"second",
            cose_public_key=b"SECOND-COSE",
            sign_count=2,
        ),
    ]
    updated = await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(b"second"),
        existing_credentials=creds,
    )
    assert captured["credential_public_key"] == b"SECOND-COSE"
    assert updated["credential_id"] == bytes_to_base64url(b"second")


# ---------------------------------------------------------------------------
# Section E: helpers — find_credential / transports / spki_public_key
# ---------------------------------------------------------------------------


def test_find_credential_returns_match_by_credential_id() -> None:
    """``_find_credential`` returns the credential with the matching id."""
    creds = [
        _stored_credential(credential_id=b"x"),
        _stored_credential(credential_id=b"y"),
    ]
    out = WebAuthnService._find_credential(bytes_to_base64url(b"y"), creds)
    assert out is creds[1]


def test_find_credential_returns_none_when_no_match() -> None:
    """``_find_credential`` returns None for unknown ids."""
    out = WebAuthnService._find_credential("absent", [_stored_credential()])
    assert out is None


def test_find_credential_empty_list_returns_none() -> None:
    """Empty credential list yields None."""
    assert WebAuthnService._find_credential("anything", []) is None


def test_credential_public_key_for_verify_prefers_cose_when_present() -> None:
    """When ``cose_public_key`` is present it MUST be returned (not SPKI)."""
    cred = _stored_credential(public_key=b"SPKI", cose_public_key=b"COSE")
    out = WebAuthnService._credential_public_key_for_verify(cred)
    assert out == b"COSE"


def test_credential_public_key_for_verify_falls_back_to_public_key() -> None:
    """Without ``cose_public_key`` the legacy ``public_key`` is returned."""
    cred = _stored_credential(public_key=b"LEGACY")
    out = WebAuthnService._credential_public_key_for_verify(cred)
    assert out == b"LEGACY"


def test_credential_public_key_for_verify_treats_empty_cose_as_falsey() -> None:
    """An empty cose value MUST fall back to public_key (truthiness)."""
    cred = _stored_credential(public_key=b"PK")
    cred["cose_public_key"] = ""
    out = WebAuthnService._credential_public_key_for_verify(cred)
    assert out == b"PK"


def test_stored_transports_filters_unknown_values() -> None:
    """Unknown transport tokens MUST be silently dropped."""
    out = WebAuthnService._stored_transports(["usb", "telepathy", "nfc"])
    assert out is not None
    assert {t.value for t in out} == {"usb", "nfc"}


def test_stored_transports_returns_none_when_all_invalid() -> None:
    """All-invalid transports MUST collapse to ``None``."""
    out = WebAuthnService._stored_transports(["telepathy", "ouija"])
    assert out is None


def test_stored_transports_empty_input_returns_none() -> None:
    """Empty input MUST return ``None`` (not empty list)."""
    assert WebAuthnService._stored_transports([]) is None


def test_transport_values_returns_empty_list_for_none() -> None:
    """``None`` input MUST yield ``[]`` (not None)."""
    assert WebAuthnService._transport_values(None) == []


def test_transport_values_serializes_enum_values() -> None:
    """Enum members MUST serialize to their string ``.value``."""
    out = WebAuthnService._transport_values(
        [AuthenticatorTransport.USB, AuthenticatorTransport.NFC]
    )
    assert out == ["usb", "nfc"]


def test_credential_descriptors_preserves_order_and_decodes_id() -> None:
    """``_credential_descriptors`` keeps order and decodes base64url ids."""
    creds = [
        _stored_credential(credential_id=b"a"),
        _stored_credential(credential_id=b"b"),
    ]
    out = WebAuthnService._credential_descriptors(creds)
    assert [d.id for d in out] == [b"a", b"b"]


def test_credential_name_strips_whitespace() -> None:
    """``_credential_name`` strips leading/trailing whitespace."""
    assert WebAuthnService._credential_name({"name": "  Yubi  "}) == "Yubi"


def test_credential_name_returns_default_when_only_whitespace() -> None:
    """Whitespace-only name MUST fall back to default."""
    assert WebAuthnService._credential_name({"name": "   "}) == "Security key"


def test_credential_name_returns_default_when_missing() -> None:
    """Missing both name and label MUST fall back to default."""
    assert WebAuthnService._credential_name({}) == "Security key"


def test_credential_name_label_used_when_name_blank() -> None:
    """``label`` is honored when ``name`` is empty."""
    assert WebAuthnService._credential_name({"name": "", "label": "Alt"}) == "Alt"


def test_aaguid_to_base64url_uses_uuid_bytes_for_canonical_form() -> None:
    """A canonical UUID MUST encode to the base64url of its 16 raw bytes."""
    out = WebAuthnService._aaguid_to_base64url("11111111-1111-1111-1111-111111111111")
    assert out == bytes_to_base64url(
        UUID("11111111-1111-1111-1111-111111111111").bytes
    )


def test_aaguid_to_base64url_passes_invalid_through() -> None:
    """Non-UUID strings MUST be returned unchanged."""
    assert WebAuthnService._aaguid_to_base64url("xx") == "xx"


def test_utc_now_iso_returns_z_suffix_not_plus_offset() -> None:
    """``_utc_now_iso`` MUST end with ``Z`` and NOT contain ``+00:00``."""
    out = WebAuthnService._utc_now_iso()
    assert out.endswith("Z")
    assert "+00:00" not in out


# ---------------------------------------------------------------------------
# Section F: integration glue — _record_audit_event ordering invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_authentication_audit_runs_after_verify(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Audit on success runs strictly after verify (decision recorded post-fact)."""
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    seq: list[str] = []

    def _verify(**_kw: Any) -> VerifiedAuthentication:
        seq.append("verify")
        return _verified_authentication(new_sign_count=2)

    async def _audit(**kwargs: Any) -> None:
        seq.append(f"audit:{kwargs['action']}")

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", _verify)
    monkeypatch.setattr(service, "_record_audit_event", _audit)
    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=1)],
    )
    assert seq == ["verify", "audit:webauthn.authentication_completed"]


@pytest.mark.asyncio
async def test_begin_registration_audit_call_uses_raw_detail_payload(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Caller (``begin_registration``) passes the raw detail dict to audit.

    This pins the *caller-side* contract: the dict handed to
    ``_record_audit_event`` is ``{"excluded_credentials": N}`` only — the
    ``target_user_id`` merge is the responsibility of ``_record_audit_event``
    itself and is verified by the dedicated audit-merge test below.
    """
    user_id = uuid4()
    service = WebAuthnService(redis)
    captured = AsyncMock()
    monkeypatch.setattr(WebAuthnService, "_record_audit_event", captured)

    await service.begin_registration(
        user_id=user_id,
        user_email="x@example.com",
        existing_credentials=[],
    )
    captured.assert_awaited()
    call_kwargs = captured.await_args_list[0].kwargs
    assert call_kwargs["actor_id"] == user_id
    assert call_kwargs["action"] == "webauthn.registration_started"
    # Detail is the raw payload from the caller — no target_user_id yet.
    assert call_kwargs["detail"] == {"excluded_credentials": 0}
    assert "target_user_id" not in call_kwargs["detail"]


@pytest.mark.asyncio
async def test_record_audit_event_merges_target_user_id_into_detail(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``_record_audit_event`` MUST merge ``target_user_id`` into ``detail``.

    Exercises the real ``_record_audit_event`` body (we explicitly do NOT
    monkeypatch it here) by stubbing ``AsyncSessionLocal`` and capturing
    ``AuditLogService.write_platform_event`` so the merge contract surfaces
    as a test failure.
    """
    # The autouse fixture replaced ``_record_audit_event`` with a no-op via
    # ``monkeypatch.setattr``; restore the captured original here so this
    # test exercises the real merge body. ``monkeypatch.setattr`` undoes
    # this restore at teardown automatically.
    monkeypatch.setattr(
        WebAuthnService,
        "_record_audit_event",
        _ORIGINAL_RECORD_AUDIT_EVENT,
    )

    captured: dict[str, Any] = {}

    class _FakeAuditLogService:
        def __init__(self, _session: Any) -> None:
            pass

        async def write_platform_event(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *_exc: Any) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    def _fake_session_local() -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(webauthn_module, "AsyncSessionLocal", _fake_session_local)
    monkeypatch.setattr(webauthn_module, "AuditLogService", _FakeAuditLogService)

    user_id = uuid4()
    service = WebAuthnService(redis)
    await service._record_audit_event(
        actor_id=user_id,
        action="webauthn.test_event",
        detail={"k": "v"},
    )
    # The merge contract: the inner call sees detail merged with
    # target_user_id (string form of actor_id), preserving original keys.
    assert captured["actor_user_id"] == user_id
    assert captured["action"] == "webauthn.test_event"
    assert captured["detail"] == {"target_user_id": str(user_id), "k": "v"}
