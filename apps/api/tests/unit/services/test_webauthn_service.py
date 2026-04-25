from __future__ import annotations

from typing import Any
from uuid import uuid4

import fakeredis.aioredis
import pytest
from webauthn.authentication.verify_authentication_response import VerifiedAuthentication
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse
from webauthn.helpers.structs import (
    AttestationFormat,
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


@pytest.fixture(autouse=True)
def _settings_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
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


@pytest.fixture
def redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


def _registration_response(credential_id: bytes = b"credential-id") -> dict[str, Any]:
    encoded_id = bytes_to_base64url(credential_id)
    return {
        "id": encoded_id,
        "rawId": encoded_id,
        "type": "public-key",
        "name": "YubiKey 5 NFC",
        "response": {
            "clientDataJSON": bytes_to_base64url(b"{}"),
            "attestationObject": bytes_to_base64url(b"attestation"),
            "transports": ["usb", "nfc"],
        },
    }


def _authentication_response(credential_id: bytes = b"credential-id") -> dict[str, Any]:
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
) -> VerifiedRegistration:
    return VerifiedRegistration(
        credential_id=credential_id,
        credential_public_key=public_key,
        sign_count=sign_count,
        aaguid="00000000-0000-0000-0000-000000000000",
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
    sign_count: int = 1,
) -> StoredCredential:
    return {
        "credential_id": bytes_to_base64url(credential_id),
        "public_key": bytes_to_base64url(public_key),
        "sign_count": sign_count,
        "transports": ["usb"],
        "aaguid": bytes_to_base64url(b"\x00" * 16),
        "name": "YubiKey 5 NFC",
        "registered_at": "2026-01-01T00:00:00Z",
        "last_used_at": None,
    }


async def _seed_challenge(
    redis: fakeredis.aioredis.FakeRedis,
    key: str,
    challenge: bytes = b"challenge",
) -> None:
    await redis.set(key, bytes_to_base64url(challenge), ex=300)


@pytest.mark.asyncio
async def test_begin_registration_stores_challenge_with_ttl_and_returns_rp_options(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    existing = [_stored_credential()]
    service = WebAuthnService(redis)

    options = await service.begin_registration(
        user_id=user_id,
        user_email="root@example.com",
        existing_credentials=existing,
    )

    key = service._registration_key(user_id)
    stored_challenge = await redis.get(key)
    assert stored_challenge is not None
    assert base64url_to_bytes(stored_challenge) == options.challenge
    assert 0 < await redis.ttl(key) <= 300
    assert options.rp.id == "example.com"
    assert options.rp.name == "Echoroo Test"
    assert options.user.id == user_id.bytes
    assert options.exclude_credentials is not None
    assert options.exclude_credentials[0].id == base64url_to_bytes(existing[0]["credential_id"])


@pytest.mark.asyncio
async def test_complete_registration_returns_stored_credential_and_deletes_challenge(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kwargs: _verified_registration(),
    )
    monkeypatch.setattr(
        WebAuthnService,
        "_spki_public_key",
        staticmethod(lambda _cose_public_key: b"spki-public-key"),
    )

    credential = await service.complete_registration(
        user_id=user_id,
        registration_response=_registration_response(),
        existing_credentials=[],
    )

    assert credential["credential_id"] == bytes_to_base64url(b"credential-id")
    assert credential["public_key"] == bytes_to_base64url(b"spki-public-key")
    assert credential["cose_public_key"] == bytes_to_base64url(b"public-key")
    assert credential["sign_count"] == 1
    assert credential["transports"] == ["usb", "nfc"]
    assert credential["name"] == "YubiKey 5 NFC"
    assert credential["registered_at"].endswith("Z")
    assert credential["last_used_at"] is None
    assert await redis.get(service._registration_key(user_id)) is None


@pytest.mark.asyncio
async def test_complete_registration_raises_when_challenge_missing(
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    service = WebAuthnService(redis)

    with pytest.raises(WebAuthnChallengeNotFoundError):
        await service.complete_registration(
            user_id=uuid4(),
            registration_response=_registration_response(),
        )


@pytest.mark.asyncio
async def test_complete_registration_keeps_challenge_when_webauthn_rejects(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._registration_key(user_id)
    await _seed_challenge(redis, key)

    def reject(**_kwargs: Any) -> VerifiedRegistration:
        raise InvalidRegistrationResponse("bad attestation")

    monkeypatch.setattr(webauthn_module, "verify_registration_response", reject)

    with pytest.raises(WebAuthnVerificationError):
        await service.complete_registration(
            user_id=user_id,
            registration_response=_registration_response(),
        )

    assert await redis.get(key) is not None


@pytest.mark.asyncio
async def test_complete_registration_rejects_duplicate_credential(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._registration_key(user_id))
    existing = [_stored_credential()]
    monkeypatch.setattr(
        webauthn_module,
        "verify_registration_response",
        lambda **_kwargs: _verified_registration(),
    )

    with pytest.raises(WebAuthnDuplicateCredentialError):
        await service.complete_registration(
            user_id=user_id,
            registration_response=_registration_response(),
            existing_credentials=existing,
        )


@pytest.mark.asyncio
async def test_complete_authentication_updates_sign_count_and_last_used_at(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._authentication_key(user_id)
    await _seed_challenge(redis, key)
    existing = [_stored_credential(sign_count=1)]
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kwargs: _verified_authentication(new_sign_count=2),
    )

    updated = await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=existing,
    )

    assert updated["credential_id"] == existing[0]["credential_id"]
    assert updated["sign_count"] == 2
    assert updated["last_used_at"] is not None
    assert updated["last_used_at"].endswith("Z")
    assert existing[0]["sign_count"] == 1
    assert await redis.get(key) is None


@pytest.mark.asyncio
async def test_complete_authentication_raises_replay_detected_on_counter_regression(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    key = service._authentication_key(user_id)
    await _seed_challenge(redis, key)
    monkeypatch.setattr(
        webauthn_module,
        "verify_authentication_response",
        lambda **_kwargs: _verified_authentication(new_sign_count=4),
    )

    with pytest.raises(WebAuthnReplayDetectedError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential(sign_count=5)],
        )

    assert await redis.get(key) is not None


@pytest.mark.asyncio
async def test_audit_event_is_called_after_verify_decision(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    order: list[str] = []

    def verify(**_kwargs: Any) -> VerifiedAuthentication:
        order.append("verified")
        return _verified_authentication(new_sign_count=2)

    async def audit(**kwargs: Any) -> None:
        assert order == ["verified"]
        order.append(kwargs["action"])

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", verify)
    monkeypatch.setattr(service, "_record_audit_event", audit)

    await service.complete_authentication(
        user_id=user_id,
        authentication_response=_authentication_response(),
        existing_credentials=[_stored_credential(sign_count=1)],
    )

    assert order == ["verified", "webauthn.authentication_completed"]


@pytest.mark.asyncio
async def test_complete_authentication_audits_signature_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user_id = uuid4()
    service = WebAuthnService(redis)
    await _seed_challenge(redis, service._authentication_key(user_id))
    audit_actions: list[str] = []

    def reject(**_kwargs: Any) -> VerifiedAuthentication:
        raise InvalidAuthenticationResponse("bad signature")

    async def audit(**kwargs: Any) -> None:
        audit_actions.append(kwargs["action"])

    monkeypatch.setattr(webauthn_module, "verify_authentication_response", reject)
    monkeypatch.setattr(service, "_record_audit_event", audit)

    with pytest.raises(WebAuthnVerificationError):
        await service.complete_authentication(
            user_id=user_id,
            authentication_response=_authentication_response(),
            existing_credentials=[_stored_credential()],
        )

    assert audit_actions == ["webauthn.authentication_failed"]


@pytest.mark.asyncio
async def test_redis_down_fails_closed() -> None:
    class DownRedis:
        async def set(self, name: str, value: str | bytes, ex: int | None = None) -> bool:
            raise ConnectionError("redis down")

    service = WebAuthnService(DownRedis())

    with pytest.raises(WebAuthnError, match="Redis challenge state"):
        await service.begin_registration(
            user_id=uuid4(),
            user_email="root@example.com",
            existing_credentials=[],
        )
