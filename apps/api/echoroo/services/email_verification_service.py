"""Email verification token issue and consume service."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.email_verification_token import EmailVerificationToken
from echoroo.models.user import User
from echoroo.repositories.email_verification_token import (
    EmailVerificationTokenRepository,
)
from echoroo.repositories.user import UserRepository
from echoroo.services.account_security_tokens import (
    generate_account_security_token,
    hash_account_security_token,
)
from echoroo.services.outbox_service import enqueue

EMAIL_VERIFICATION_EVENT_TYPE = "auth.email_verification.requested"
EMAIL_VERIFICATION_PURPOSE = "verify_email"
EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION = "v1"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class EmailVerificationError(Exception):
    """Raised for audit-safe email verification failures."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IssuedEmailVerificationToken:
    """Newly issued raw token plus its queued outbox row."""

    token: str
    outbox_event_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class EmailVerificationResult:
    """Successful email verification result."""

    user_id: UUID
    email: str
    email_verified_at: datetime
    user: User


@dataclass(frozen=True)
class SameEmailInvitationVerificationResult:
    """Outcome of marking a user verified from a same-email invitation."""

    verified: bool
    email_verified_at: datetime | None


def normalize_email_for_verification(email: str) -> str:
    """Normalize an email address using the first-party auth policy."""
    normalized = unicodedata.normalize("NFKC", email).strip()
    try:
        validated = validate_email(
            normalized,
            allow_smtputf8=True,
            check_deliverability=False,
        )
    except EmailNotValidError:
        return normalized.lower()
    return validated.normalized.lower()


def _safe_hash(value: str | None) -> str | None:
    if not value:
        return None
    key = get_settings().web_session_secret
    if isinstance(key, str):
        key = key.encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _outbox_token_key() -> bytes:
    secret = get_settings().web_session_secret
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    return hashlib.sha256(secret + b":email-verification-outbox:v1").digest()


def seal_email_verification_outbox_token(token: str) -> str:
    """Encrypt a raw verification token for transient outbox delivery."""
    if not _TOKEN_RE.fullmatch(token):
        raise ValueError("email verification token has invalid shape")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_outbox_token_key()).encrypt(nonce, token.encode("ascii"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def unseal_email_verification_outbox_token(sealed: str) -> str:
    """Decrypt an outbox token envelope and validate the recovered token."""
    try:
        raw = base64.urlsafe_b64decode(sealed.encode("ascii"))
        nonce = raw[:12]
        ciphertext = raw[12:]
        token = AESGCM(_outbox_token_key()).decrypt(nonce, ciphertext, None).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        raise EmailVerificationError("ERR_EMAIL_VERIFICATION_OUTBOX_TOKEN_INVALID") from exc
    if not _TOKEN_RE.fullmatch(token):
        raise EmailVerificationError("ERR_EMAIL_VERIFICATION_OUTBOX_TOKEN_INVALID")
    return token


class EmailVerificationService:
    """Owns issuing and consuming single-use email verification tokens."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tokens = EmailVerificationTokenRepository(db)
        self.users = UserRepository(db)
        self._consume_lock = asyncio.Lock()

    async def issue_verification_token(
        self,
        *,
        user: User,
        email: str,
        ip: str | None = None,
        user_agent: str | None = None,
        expires_at: datetime | None = None,
    ) -> IssuedEmailVerificationToken:
        """Issue a new token, supersede older active tokens, and enqueue email."""
        now = datetime.now(UTC)
        normalized_email = normalize_email_for_verification(email)
        token = generate_account_security_token()
        token_hash = hash_account_security_token(token)
        resolved_expires_at = expires_at or (
            now + timedelta(seconds=get_settings().EMAIL_VERIFICATION_TOKEN_TTL_SECONDS)
        )

        await self.tokens.supersede_active_for_user(
            user_id=user.id,
            purpose=EMAIL_VERIFICATION_PURPOSE,
            superseded_at=now,
        )
        row = EmailVerificationToken(
            user_id=user.id,
            email_normalized=normalized_email,
            token_hash=token_hash,
            purpose=EMAIL_VERIFICATION_PURPOSE,
            expires_at=resolved_expires_at,
            created_ip_hash=_safe_hash(ip),
            created_user_agent_hash=_safe_hash(user_agent),
        )
        await self.tokens.create(row)

        outbox_event_id = await enqueue(
            self.db,
            event_type=EMAIL_VERIFICATION_EVENT_TYPE,
            payload={
                "user_id": str(user.id),
                "token_id": str(row.id),
                "email_hash": _safe_hash(normalized_email),
                "token_hash_prefix": token_hash[:12],
                "token_envelope": seal_email_verification_outbox_token(token),
                "token_envelope_version": EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
                "purpose": EMAIL_VERIFICATION_PURPOSE,
                "requested_at": now.isoformat(),
            },
            idempotency_key=f"email-verification:{user.id}:{token_hash[:16]}",
        )
        return IssuedEmailVerificationToken(
            token=token,
            outbox_event_id=outbox_event_id,
            expires_at=resolved_expires_at,
        )

    async def verify_token(self, token: str) -> EmailVerificationResult:
        """Consume a verification token and mark the bound account verified."""
        async with self._consume_lock:
            if not _TOKEN_RE.fullmatch(token):
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_INVALID")

            token_hash = hash_account_security_token(token)
            row = await self.tokens.get_by_token_hash_for_update(token_hash)
            if row is None:
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_INVALID")
            if row.purpose != EMAIL_VERIFICATION_PURPOSE:
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_INVALID")
            if row.consumed_at is not None or row.superseded_at is not None:
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_REUSED")

            now = datetime.now(UTC)
            if _ensure_aware(row.expires_at) <= now:
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_EXPIRED")

            user = await self.users.get_by_id(row.user_id)
            if user is None or user.deleted_at is not None:
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_INVALID")
            if normalize_email_for_verification(user.email) != row.email_normalized:
                raise EmailVerificationError("ERR_EMAIL_VERIFICATION_INVALID")

            verified_at = user.email_verified_at or now
            user.email_verified_at = verified_at
            row.consumed_at = now
            row.updated_at = now
            self.db.add(user)
            self.db.add(row)
            await self.db.flush()
            return EmailVerificationResult(
                user_id=user.id,
                email=user.email,
                email_verified_at=verified_at,
                user=user,
            )

    async def mark_verified_from_same_email_invitation(
        self,
        *,
        user: User,
        invitation_email: str | None,
        accepted_at: datetime,
    ) -> SameEmailInvitationVerificationResult:
        """Mark ``user`` verified when an accepted invitation used the same email."""
        if invitation_email is None:
            return SameEmailInvitationVerificationResult(
                verified=False,
                email_verified_at=user.email_verified_at,
            )
        if normalize_email_for_verification(user.email) != normalize_email_for_verification(
            invitation_email
        ):
            return SameEmailInvitationVerificationResult(
                verified=False,
                email_verified_at=user.email_verified_at,
            )

        if user.email_verified_at is None:
            user.email_verified_at = accepted_at
            self.db.add(user)
            await self.db.flush()
        return SameEmailInvitationVerificationResult(
            verified=True,
            email_verified_at=user.email_verified_at,
        )
