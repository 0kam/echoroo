"""Two-factor authentication service.

TOTP secret envelope layout in ``users.two_factor_secret_encrypted``:

    len(wrapped_dek):4LE | wrapped_dek | nonce:12 | ciphertext

The ciphertext is AES-256-GCM over the UTF-8 bytes of the TOTP base32
secret. Each record gets a fresh 32-byte DEK, wrapped by KMS before
storage and zeroized after use.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import string
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID

import pyotp
import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from argon2.low_level import Type as Argon2Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core import kms
from echoroo.core.database import AsyncSessionLocal
from echoroo.core.redis import get_redis_connection
from echoroo.models.user import User
from echoroo.services.audit_service import AuditLogService

ISSUER_NAME = "Echoroo"
TOTP_SECRET_LENGTH = 32
TOTP_VALID_WINDOW = 1
TOTP_DEK_VERSION = 1  # TODO: read current 2FA DEK rotation version from settings.
AES_GCM_NONCE_BYTES = 12
AES_256_KEY_BYTES = 32
WRAPPED_DEK_LEN_BYTES = 4

BACKUP_CODE_COUNT = 8
BACKUP_CODE_LENGTH = 12
BACKUP_CODE_ALPHABET = "".join(
    ch for ch in string.ascii_uppercase + "234567" if ch not in {"I", "L", "O", "U", "0", "1"}
)

TOTP_FAIL_LIMIT = 5
TOTP_FAIL_WINDOW_SECONDS = 15 * 60
TOTP_LOCK_THRESHOLD = 10
TOTP_LOCK_SECONDS = 15 * 60
BACKUP_FAIL_LIMIT = 3
BACKUP_FAIL_WINDOW_SECONDS = 60 * 60
RESET_COOLDOWN = timedelta(hours=72)

_AUDIT_REQUEST_ID = "internal"
_AUDIT_IP = "0.0.0.0"
_AUDIT_USER_AGENT = ""

_backup_code_hasher = PasswordHasher(
    memory_cost=65536,
    time_cost=3,
    parallelism=4,
    type=Argon2Type.ID,
)


class TwoFactorError(Exception):
    """Base class for two-factor authentication errors."""


class TwoFactorAlreadyEnabledError(TwoFactorError):
    """Raised when enrollment is attempted for an already-enabled user."""


class TwoFactorNotEnabledError(TwoFactorError):
    """Raised when verification is attempted before 2FA is enabled."""


class TwoFactorInvalidCodeError(TwoFactorError):
    """Raised when a setup or recovery code is invalid."""


class TwoFactorRateLimitedError(TwoFactorError):
    """Raised when too many verification failures occur in a rate window."""


class TwoFactorLockedError(TwoFactorError):
    """Raised when consecutive verification failures trigger lockout."""


@dataclass(frozen=True)
class TwoFactorEnrollmentArtifacts:
    """TOTP setup artifacts shown once during enrollment."""

    secret: str
    provisioning_uri: str


class _RedisRateLimiter(Protocol):
    async def incr(self, name: str) -> int: ...

    async def expire(self, name: str, time: int) -> bool: ...

    async def get(self, name: str) -> str | bytes | int | None: ...

    async def set(self, name: str, value: str | int, ex: int | None = None) -> bool | None: ...

    async def delete(self, *names: str) -> int: ...


def _zeroize(buffer: bytearray) -> None:
    for i in range(len(buffer)):
        buffer[i] = 0


def _security_stamp() -> str:
    stamp = secrets.token_urlsafe(48)
    if len(stamp) != 64:  # Defensive guard for the VARCHAR(64) contract.
        raise RuntimeError("generated security_stamp does not fit users.security_stamp")
    return stamp


def _user_lock_key(user_id: UUID) -> int:
    digest = hashlib.sha256(f"2fa-setup:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _normalize_totp_code(code: str) -> str:
    return code.strip().replace(" ", "")


def _normalize_backup_code(code: str) -> str:
    return code.strip().replace("-", "").replace(" ", "").upper()


def _totp(secret: str) -> pyotp.TOTP:
    return pyotp.TOTP(secret, digits=6, interval=30)


def _encrypt_totp_secret(secret: str) -> bytes:
    dek = bytearray(os.urandom(AES_256_KEY_BYTES))
    try:
        nonce = os.urandom(AES_GCM_NONCE_BYTES)
        wrapped_dek = kms.wrap_dek(bytes(dek))
        ciphertext = AESGCM(bytes(dek)).encrypt(nonce, secret.encode("utf-8"), None)
        return (
            struct.pack("<I", len(wrapped_dek))
            + wrapped_dek
            + nonce
            + ciphertext
        )
    finally:
        _zeroize(dek)
        del dek


def _decrypt_totp_secret(payload: bytes) -> str:
    if len(payload) < WRAPPED_DEK_LEN_BYTES + AES_GCM_NONCE_BYTES:
        raise TwoFactorError("encrypted TOTP secret payload is malformed")

    wrapped_len = struct.unpack("<I", payload[:WRAPPED_DEK_LEN_BYTES])[0]
    wrapped_start = WRAPPED_DEK_LEN_BYTES
    wrapped_end = wrapped_start + wrapped_len
    nonce_end = wrapped_end + AES_GCM_NONCE_BYTES
    if wrapped_len <= 0 or len(payload) <= nonce_end:
        raise TwoFactorError("encrypted TOTP secret payload is malformed")

    wrapped_dek = payload[wrapped_start:wrapped_end]
    nonce = payload[wrapped_end:nonce_end]
    ciphertext = payload[nonce_end:]

    dek = bytearray(kms.unwrap_dek(wrapped_dek))
    try:
        plaintext = AESGCM(bytes(dek)).decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    finally:
        _zeroize(dek)
        del dek


def _generate_backup_code() -> str:
    return "".join(secrets.choice(BACKUP_CODE_ALPHABET) for _ in range(BACKUP_CODE_LENGTH))


def _hash_backup_code(code: str) -> str:
    return _backup_code_hasher.hash(_normalize_backup_code(code))


def _verify_backup_hash(code: str, hashed: str) -> bool:
    try:
        return bool(_backup_code_hasher.verify(hashed, _normalize_backup_code(code)))
    except (
        argon2_exceptions.VerificationError,
        argon2_exceptions.VerifyMismatchError,
        argon2_exceptions.InvalidHashError,
    ):
        return False


class TwoFactorService:
    """Service-layer primitives for TOTP enrollment, verification, and reset."""

    def __init__(self, db: AsyncSession, redis: Redis | _RedisRateLimiter | None = None) -> None:
        self.db = db
        self.redis = redis

    async def begin_enrollment(self, user: User) -> TwoFactorEnrollmentArtifacts:
        """Generate TOTP secret and provisioning URI without persisting user 2FA state."""
        if user.two_factor_enabled:
            raise TwoFactorAlreadyEnabledError("two-factor authentication is already enabled")

        secret = pyotp.random_base32(length=TOTP_SECRET_LENGTH)
        provisioning_uri = _totp(secret).provisioning_uri(
            name=user.email,
            issuer_name=ISSUER_NAME,
        )
        await self._record_audit_event(
            actor_id=user.id,
            target_user=user,
            action="two_factor.enroll_initiated",
            detail={"target_user_id": str(user.id)},
        )
        return TwoFactorEnrollmentArtifacts(secret=secret, provisioning_uri=provisioning_uri)

    async def confirm_enrollment(self, user: User, secret: str, totp_code: str) -> list[str]:
        """Verify first TOTP code, persist encrypted secret, and return backup codes."""
        if user.two_factor_enabled:
            raise TwoFactorAlreadyEnabledError("two-factor authentication is already enabled")

        await self._take_setup_lock(user.id)

        if not _totp(secret).verify(_normalize_totp_code(totp_code), valid_window=TOTP_VALID_WINDOW):
            await self._record_audit_event(
                actor_id=user.id,
                target_user=user,
                action="two_factor.verify_failed",
                detail={"phase": "enrollment_confirm"},
            )
            raise TwoFactorInvalidCodeError("invalid TOTP code")

        backup_codes = [_generate_backup_code() for _ in range(BACKUP_CODE_COUNT)]
        hashed_codes = [_hash_backup_code(code) for code in backup_codes]

        user.two_factor_secret_encrypted = _encrypt_totp_secret(secret)
        user.two_factor_secret_dek_version = TOTP_DEK_VERSION
        user.two_factor_backup_codes_hashed = hashed_codes
        user.two_factor_enabled = True
        self.rotate_security_stamp(user)
        self.db.add(user)

        await self._clear_totp_failures(user.id)
        await self._record_audit_event(
            actor_id=user.id,
            target_user=user,
            action="two_factor.enroll_confirmed",
            detail={"backup_code_count": len(backup_codes), "dek_version": TOTP_DEK_VERSION},
        )
        await self._record_audit_event(
            actor_id=user.id,
            target_user=user,
            action="two_factor.backup_code_remaining",
            detail={"remaining": len(backup_codes)},
        )
        await self.db.commit()
        return backup_codes

    async def verify_totp(self, user: User, code: str) -> bool:
        """Verify a TOTP code with Redis-backed failure limits and lockout."""
        if not user.two_factor_enabled or not user.two_factor_secret_encrypted:
            raise TwoFactorNotEnabledError("two-factor authentication is not enabled")

        await self._raise_if_totp_locked(user.id)
        secret = _decrypt_totp_secret(user.two_factor_secret_encrypted)
        if _totp(secret).verify(_normalize_totp_code(code), valid_window=TOTP_VALID_WINDOW):
            await self._clear_totp_failures(user.id)
            return True

        fail_count = await self._increment_failures(
            self._totp_fail_key(user.id),
            TOTP_FAIL_WINDOW_SECONDS,
        )
        consecutive_count = await self._increment_failures(
            self._totp_consecutive_key(user.id),
            TOTP_LOCK_SECONDS,
        )
        if consecutive_count >= TOTP_LOCK_THRESHOLD:
            redis = await self._redis()
            await redis.set(self._totp_lock_key(user.id), "1", ex=TOTP_LOCK_SECONDS)
            await self._record_audit_event(
                actor_id=user.id,
                target_user=user,
                action="two_factor.verify_failed",
                detail={"method": "totp", "failure_count": consecutive_count, "locked": True},
            )
            raise TwoFactorLockedError("too many consecutive TOTP failures")
        if fail_count > TOTP_FAIL_LIMIT:
            raise TwoFactorRateLimitedError("too many TOTP verification failures")

        if fail_count in {1, TOTP_FAIL_LIMIT}:
            await self._record_audit_event(
                actor_id=user.id,
                target_user=user,
                action="two_factor.verify_failed",
                detail={"method": "totp", "failure_count": fail_count},
            )
        return False

    async def verify_backup_code(self, user: User, code: str) -> bool:
        """Verify and atomically consume a backup code.

        Strategy: lock the user row with ``SELECT ... FOR UPDATE``, read the
        current backup-code hash array after the lock is held, then issue an
        ``UPDATE`` guarded by ``two_factor_backup_codes_hashed = original``.
        This preserves one-time use under concurrent submissions.
        """
        if not user.two_factor_enabled:
            raise TwoFactorNotEnabledError("two-factor authentication is not enabled")

        result = await self.db.execute(select(User).where(User.id == user.id).with_for_update())
        locked_user = result.scalar_one_or_none()
        if locked_user is None:
            raise TwoFactorNotEnabledError("two-factor user row was not found")

        original_codes = list(locked_user.two_factor_backup_codes_hashed or [])
        matched_hash: str | None = None
        for hashed in original_codes:
            if _verify_backup_hash(code, hashed):
                matched_hash = hashed
                break

        if matched_hash is None:
            fail_count = await self._increment_failures(
                self._backup_fail_key(user.id),
                BACKUP_FAIL_WINDOW_SECONDS,
            )
            if fail_count > BACKUP_FAIL_LIMIT:
                raise TwoFactorRateLimitedError("too many backup-code verification failures")
            if fail_count in {1, BACKUP_FAIL_LIMIT}:
                await self._record_audit_event(
                    actor_id=user.id,
                    target_user=user,
                    action="two_factor.verify_failed",
                    detail={"method": "backup_code", "failure_count": fail_count},
                )
            return False

        remaining = [hashed for hashed in original_codes if hashed != matched_hash]
        update_result = await self.db.execute(
            update(User)
            .where(
                User.id == user.id,
                User.two_factor_backup_codes_hashed == original_codes,
            )
            .values(two_factor_backup_codes_hashed=remaining)
        )
        rowcount = getattr(update_result, "rowcount", 0)
        if rowcount != 1:
            raise TwoFactorInvalidCodeError("backup code was already consumed")

        locked_user.two_factor_backup_codes_hashed = remaining
        user.two_factor_backup_codes_hashed = remaining
        await self._clear_backup_failures(user.id)
        await self._record_audit_event(
            actor_id=user.id,
            target_user=user,
            action="two_factor.backup_code_consumed",
            detail={"remaining": len(remaining)},
        )
        await self._record_audit_event(
            actor_id=user.id,
            target_user=user,
            action="two_factor.backup_code_remaining",
            detail={"remaining": len(remaining)},
        )
        await self.db.commit()
        return True

    async def reset_user_two_factor(self, user: User, *, actor_id: UUID, reason: str) -> None:
        """Admin-driven 2FA reset primitive."""
        await self._record_audit_event(
            actor_id=actor_id,
            target_user=user,
            action="two_factor.reset_initiated",
            detail={"target_user_id": str(user.id), "reason": reason},
        )
        user.two_factor_secret_encrypted = None
        user.two_factor_secret_dek_version = None
        user.two_factor_backup_codes_hashed = None
        user.two_factor_enabled = False
        user.two_factor_reset_cooldown_until = datetime.now(UTC) + RESET_COOLDOWN
        self.rotate_security_stamp(user)
        self.db.add(user)
        await self._clear_totp_failures(user.id)
        await self._clear_backup_failures(user.id)
        await self._record_audit_event(
            actor_id=actor_id,
            target_user=user,
            action="two_factor.reset_completed",
            detail={"target_user_id": str(user.id), "reason": reason, "cooldown_hours": 72},
        )
        await self.db.commit()

    @staticmethod
    def is_two_factor_required(user: User) -> bool:
        """Return True when the user must complete first-login 2FA enrollment."""
        return not user.two_factor_enabled

    @staticmethod
    def rotate_security_stamp(user: User) -> None:
        """Rotate ``users.security_stamp`` to revoke refresh tokens via stamp checks."""
        user.security_stamp = _security_stamp()

    async def _redis(self) -> _RedisRateLimiter:
        if self.redis is None:
            self.redis = await get_redis_connection()
        return cast(_RedisRateLimiter, self.redis)

    async def _increment_failures(self, key: str, ttl_seconds: int) -> int:
        redis = await self._redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, ttl_seconds)
        return int(count)

    async def _raise_if_totp_locked(self, user_id: UUID) -> None:
        redis = await self._redis()
        if await redis.get(self._totp_lock_key(user_id)) is not None:
            raise TwoFactorLockedError("TOTP verification is temporarily locked")

    async def _clear_totp_failures(self, user_id: UUID) -> None:
        redis = await self._redis()
        await redis.delete(
            self._totp_fail_key(user_id),
            self._totp_consecutive_key(user_id),
            self._totp_lock_key(user_id),
        )

    async def _clear_backup_failures(self, user_id: UUID) -> None:
        redis = await self._redis()
        await redis.delete(self._backup_fail_key(user_id))

    async def _take_setup_lock(self, user_id: UUID) -> None:
        await self.db.execute(
            sa.text("SELECT pg_advisory_xact_lock(:key)").bindparams(key=_user_lock_key(user_id))
        )

    async def _record_audit_event(
        self,
        *,
        actor_id: UUID,
        target_user: User,
        action: str,
        detail: dict[str, Any],
    ) -> None:
        async with AsyncSessionLocal() as audit_session:
            try:
                audit = AuditLogService(audit_session)
                await audit.write_platform_event(
                    actor_user_id=actor_id,
                    action=action,
                    request_id=_AUDIT_REQUEST_ID,
                    ip=_AUDIT_IP,
                    user_agent=_AUDIT_USER_AGENT,
                    detail={"target_user_id": str(target_user.id), **detail},
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise

    @staticmethod
    def _totp_fail_key(user_id: UUID) -> str:
        return f"2fa:totp_fail:{user_id}"

    @staticmethod
    def _totp_consecutive_key(user_id: UUID) -> str:
        return f"2fa:totp_consecutive_fail:{user_id}"

    @staticmethod
    def _totp_lock_key(user_id: UUID) -> str:
        return f"2fa:totp_lock:{user_id}"

    @staticmethod
    def _backup_fail_key(user_id: UUID) -> str:
        return f"2fa:backup_fail:{user_id}"


__all__ = [
    "TwoFactorAlreadyEnabledError",
    "TwoFactorEnrollmentArtifacts",
    "TwoFactorError",
    "TwoFactorInvalidCodeError",
    "TwoFactorLockedError",
    "TwoFactorNotEnabledError",
    "TwoFactorRateLimitedError",
    "TwoFactorService",
]
