"""Model-agnostic WebAuthn service primitives for superuser hardware keys."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, NotRequired, Protocol, TypedDict, cast
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from redis.asyncio import Redis
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    decode_credential_public_key,
    decoded_public_key_to_cryptography,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorTransport,
    PublicKeyCredentialCreationOptions,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRequestOptions,
    UserVerificationRequirement,
)

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.services.audit_service import AuditLogService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_AUDIT_REQUEST_ID = "internal"
_AUDIT_IP = "0.0.0.0"
_AUDIT_USER_AGENT = ""


class StoredCredential(TypedDict):
    """JSONB-safe WebAuthn credential record owned by the caller."""

    credential_id: str
    public_key: str
    sign_count: int
    transports: list[str]
    aaguid: str
    name: str
    registered_at: str
    last_used_at: str | None
    cose_public_key: NotRequired[str]


class WebAuthnError(Exception):
    """Base class for WebAuthn service errors."""


class WebAuthnChallengeNotFoundError(WebAuthnError):
    """Raised when the Redis challenge expired or was never issued."""


class WebAuthnVerificationError(WebAuthnError):
    """Raised when py_webauthn rejects the ceremony response."""


class WebAuthnDuplicateCredentialError(WebAuthnError):
    """Raised when a registration returns an already-stored credential ID."""


class WebAuthnReplayDetectedError(WebAuthnError):
    """Raised when an authenticator sign counter regresses."""


class _RedisChallengeStore(Protocol):
    async def get(self, name: str) -> str | bytes | int | None: ...

    async def set(self, name: str, value: str | bytes, ex: int | None = None) -> bool | None: ...

    async def delete(self, *names: str) -> int: ...


class WebAuthnService:
    """Stateless py_webauthn wrapper. Caller owns credential persistence."""

    def __init__(
        self,
        redis: Redis | _RedisChallengeStore | None = None,
        *,
        audit_log_factory: Callable[[AsyncSession], AuditLogService] | None = None,
    ) -> None:
        self.redis = redis
        self.settings = get_settings()
        # Dependency-injection seam for tests. When ``None`` the module-level
        # ``AuditLogService`` is resolved at call time (see
        # ``_record_audit_event``) so existing monkeypatch-based tests keep
        # working. An injected factory MUST build an ``AuditLogService`` on
        # the FRESH session passed to it — the SERIALIZABLE upgrade has to be
        # the first statement on the audit connection.
        self._audit_log_factory = audit_log_factory

    async def begin_registration(
        self,
        *,
        user_id: UUID,
        user_email: str,
        existing_credentials: Sequence[StoredCredential],
    ) -> PublicKeyCredentialCreationOptions:
        """Generate registration options and store a one-time challenge in Redis."""
        options = generate_registration_options(
            rp_id=self.settings.webauthn_rp_id,
            rp_name=self.settings.webauthn_rp_name,
            user_name=user_email,
            user_id=user_id.bytes,
            user_display_name=user_email,
            exclude_credentials=self._credential_descriptors(existing_credentials),
        )
        await self._store_challenge(self._registration_key(user_id), options.challenge)
        await self._record_audit_event(
            actor_id=user_id,
            action="webauthn.registration_started",
            detail={"excluded_credentials": len(existing_credentials)},
        )
        return options

    async def complete_registration(
        self,
        *,
        user_id: UUID,
        registration_response: dict[str, Any],
        existing_credentials: Sequence[StoredCredential] = (),
    ) -> StoredCredential:
        """Verify registration and return a credential dict ready for persistence.

        ``existing_credentials`` is optional for backwards-compatible call sites, but
        callers should pass it so duplicate IDs can be rejected after verification.

        Note: this method emits a ``webauthn.registration_completed`` audit event
        before returning. If the caller subsequently fails to persist the returned
        ``StoredCredential``, the caller MUST emit a compensating audit event such
        as ``webauthn.registration_persistence_failed`` so the audit log accurately
        reflects the final state.
        """
        challenge = await self._load_challenge(self._registration_key(user_id), user_id=user_id)
        try:
            credential = parse_registration_credential_json(registration_response)
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.settings.webauthn_rp_id,
                expected_origin=self.settings.webauthn_origins,
            )
        except WebAuthnException as exc:
            raise WebAuthnVerificationError("WebAuthn registration response was rejected") from exc

        credential_id = bytes_to_base64url(verified.credential_id)
        if any(stored["credential_id"] == credential_id for stored in existing_credentials):
            raise WebAuthnDuplicateCredentialError("WebAuthn credential is already registered")

        stored_credential: StoredCredential = {
            "credential_id": credential_id,
            "public_key": bytes_to_base64url(self._spki_public_key(verified.credential_public_key)),
            "cose_public_key": bytes_to_base64url(verified.credential_public_key),
            "sign_count": verified.sign_count,
            "transports": self._transport_values(credential.response.transports),
            "aaguid": self._aaguid_to_base64url(verified.aaguid),
            "name": self._credential_name(registration_response),
            "registered_at": self._utc_now_iso(),
            "last_used_at": None,
        }
        await self._delete_challenge(self._registration_key(user_id))
        await self._record_audit_event(
            actor_id=user_id,
            action="webauthn.registration_completed",
            detail={"credential_id": credential_id},
        )
        return stored_credential

    async def begin_authentication(
        self,
        *,
        user_id: UUID,
        existing_credentials: Sequence[StoredCredential],
    ) -> PublicKeyCredentialRequestOptions:
        """Generate authentication options scoped to this user's credentials only."""
        options = generate_authentication_options(
            rp_id=self.settings.webauthn_rp_id,
            allow_credentials=self._credential_descriptors(existing_credentials),
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        await self._store_challenge(self._authentication_key(user_id), options.challenge)
        await self._record_audit_event(
            actor_id=user_id,
            action="webauthn.authentication_started",
            detail={"allowed_credentials": len(existing_credentials)},
        )
        return options

    async def complete_authentication(
        self,
        *,
        user_id: UUID,
        authentication_response: dict[str, Any],
        existing_credentials: Sequence[StoredCredential],
    ) -> StoredCredential:
        """Verify authentication and return the updated credential record.

        Note: this method emits a ``webauthn.authentication_completed`` audit event
        before returning. If the caller subsequently fails to persist the returned
        ``StoredCredential``, the caller MUST emit a compensating audit event such
        as ``webauthn.authentication_persistence_failed`` so the audit log
        accurately reflects the final state.
        """
        challenge = await self._load_challenge(self._authentication_key(user_id), user_id=user_id)
        try:
            credential = parse_authentication_credential_json(authentication_response)
        except WebAuthnException as exc:
            await self._record_audit_event(
                actor_id=user_id,
                action="webauthn.authentication_failed",
                detail={"reason": "malformed_response"},
            )
            raise WebAuthnVerificationError("WebAuthn authentication response is malformed") from exc

        credential_id = bytes_to_base64url(credential.raw_id)
        stored_credential = self._find_credential(credential_id, existing_credentials)
        if stored_credential is None:
            await self._record_audit_event(
                actor_id=user_id,
                action="webauthn.authentication_failed",
                detail={"credential_id": credential_id, "reason": "unknown_credential"},
            )
            raise WebAuthnVerificationError("WebAuthn credential is not registered for this user")

        old_sign_count = int(stored_credential["sign_count"])
        try:
            verified = verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self.settings.webauthn_rp_id,
                expected_origin=self.settings.webauthn_origins,
                credential_public_key=self._credential_public_key_for_verify(stored_credential),
                # Pass zero so py_webauthn verifies the signature and this service can
                # emit a replay-specific audit event/error after inspecting the counter.
                credential_current_sign_count=0,
            )
        except WebAuthnException as exc:
            await self._record_audit_event(
                actor_id=user_id,
                action="webauthn.authentication_failed",
                detail={"credential_id": credential_id, "reason": "verification_failed"},
            )
            raise WebAuthnVerificationError("WebAuthn authentication response was rejected") from exc

        new_sign_count = verified.new_sign_count
        # Some authenticators always report 0; WebAuthn treats that as no usable counter.
        if new_sign_count <= old_sign_count and new_sign_count != 0:
            await self._record_audit_event(
                actor_id=user_id,
                action="webauthn.replay_detected",
                detail={
                    "credential_id": credential_id,
                    "old_sign_count": old_sign_count,
                    "new_sign_count": new_sign_count,
                },
            )
            raise WebAuthnReplayDetectedError("WebAuthn sign counter regressed")

        updated = cast(StoredCredential, dict(stored_credential))
        updated["sign_count"] = new_sign_count
        updated["last_used_at"] = self._utc_now_iso()
        await self._delete_challenge(self._authentication_key(user_id))
        await self._record_audit_event(
            actor_id=user_id,
            action="webauthn.authentication_completed",
            detail={"credential_id": credential_id, "new_sign_count": new_sign_count},
        )
        return updated

    async def _redis(self) -> _RedisChallengeStore:
        if self.redis is None:
            self.redis = await get_redis_connection()
        return cast(_RedisChallengeStore, self.redis)

    async def _store_challenge(self, key: str, challenge: bytes) -> None:
        try:
            redis = await self._redis()
            await redis.set(
                key,
                bytes_to_base64url(challenge),
                ex=self.settings.webauthn_challenge_ttl_seconds,
            )
        except Exception as exc:
            raise WebAuthnError("Redis challenge state is unavailable") from exc

    async def _load_challenge(self, key: str, *, user_id: UUID) -> bytes:
        try:
            redis = await self._redis()
            value = await redis.get(key)
        except Exception as exc:
            raise WebAuthnError("Redis challenge state is unavailable") from exc

        if value is None:
            logger.info("WebAuthn challenge missing or expired for user_id=%s", user_id)
            raise WebAuthnChallengeNotFoundError("WebAuthn challenge expired or was not issued")
        if isinstance(value, bytes):
            value = value.decode("ascii")
        return base64url_to_bytes(str(value))

    async def _delete_challenge(self, key: str) -> None:
        try:
            redis = await self._redis()
            await redis.delete(key)
        except Exception as exc:
            raise WebAuthnError("Redis challenge state is unavailable") from exc

    async def _record_audit_event(
        self,
        *,
        actor_id: UUID,
        action: str,
        detail: dict[str, Any],
    ) -> None:
        async with AsyncSessionLocal() as audit_session:
            try:
                factory = self._audit_log_factory or AuditLogService
                audit = factory(audit_session)
                await audit.write_platform_event(
                    actor_user_id=actor_id,
                    action=action,
                    request_id=_AUDIT_REQUEST_ID,
                    ip=_AUDIT_IP,
                    user_agent=_AUDIT_USER_AGENT,
                    detail={"target_user_id": str(actor_id), **detail},
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise

    @staticmethod
    def _credential_descriptors(
        credentials: Sequence[StoredCredential],
    ) -> list[PublicKeyCredentialDescriptor]:
        return [
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(credential["credential_id"]),
                transports=WebAuthnService._stored_transports(credential["transports"]),
            )
            for credential in credentials
        ]

    @staticmethod
    def _stored_transports(transports: Sequence[str]) -> list[AuthenticatorTransport] | None:
        values: list[AuthenticatorTransport] = []
        for transport in transports:
            try:
                values.append(AuthenticatorTransport(transport))
            except ValueError:
                continue
        return values or None

    @staticmethod
    def _transport_values(transports: Sequence[AuthenticatorTransport] | None) -> list[str]:
        if transports is None:
            return []
        return [transport.value for transport in transports]

    @staticmethod
    def _find_credential(
        credential_id: str,
        credentials: Sequence[StoredCredential],
    ) -> StoredCredential | None:
        for credential in credentials:
            if credential["credential_id"] == credential_id:
                return credential
        return None

    @staticmethod
    def _credential_public_key_for_verify(credential: StoredCredential) -> bytes:
        return base64url_to_bytes(credential.get("cose_public_key") or credential["public_key"])

    @staticmethod
    def _spki_public_key(cose_public_key: bytes) -> bytes:
        decoded_public_key = decode_credential_public_key(cose_public_key)
        crypto_public_key = decoded_public_key_to_cryptography(decoded_public_key)
        return crypto_public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    @staticmethod
    def _credential_name(registration_response: dict[str, Any]) -> str:
        name = registration_response.get("name") or registration_response.get("label")
        if isinstance(name, str) and name.strip():
            return name.strip()
        return "Security key"

    @staticmethod
    def _aaguid_to_base64url(aaguid: str) -> str:
        try:
            return bytes_to_base64url(UUID(aaguid).bytes)
        except ValueError:
            return aaguid

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _registration_key(user_id: UUID) -> str:
        return f"webauthn:reg:{user_id}"

    @staticmethod
    def _authentication_key(user_id: UUID) -> str:
        return f"webauthn:auth:{user_id}"


__all__ = [
    "StoredCredential",
    "WebAuthnChallengeNotFoundError",
    "WebAuthnDuplicateCredentialError",
    "WebAuthnError",
    "WebAuthnReplayDetectedError",
    "WebAuthnService",
    "WebAuthnVerificationError",
]
