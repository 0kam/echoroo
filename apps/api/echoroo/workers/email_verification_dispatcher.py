"""Outbox dispatcher for verification email requests."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.text import has_control_chars
from echoroo.models.email_verification_token import EmailVerificationToken
from echoroo.services.account_security_tokens import hash_account_security_token
from echoroo.services.email import send_verification_email
from echoroo.services.email_verification_service import (
    EMAIL_VERIFICATION_EVENT_TYPE,
    EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION,
    EmailVerificationError,
    unseal_email_verification_outbox_token,
)
from echoroo.workers.outbox_processor import register_outbox_handler

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class EmailVerificationPayloadError(ValueError):
    """Raised when a verification email outbox payload is malformed."""


def _clean_email(value: object) -> str:
    email = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not email or has_control_chars(email):
        raise EmailVerificationPayloadError("verification email payload has invalid email")
    return email


def _clean_token(value: object) -> str:
    token = str(value or "")
    if not _TOKEN_RE.fullmatch(token):
        raise EmailVerificationPayloadError("verification email payload has invalid token")
    return token


async def _resolve_delivery_payload(
    session: AsyncSession,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """Resolve the current PII-free payload shape to recipient and token."""
    token_id_raw = str(payload.get("token_id") or "")
    token_envelope = str(payload.get("token_envelope") or "")
    if (
        not token_id_raw
        or not token_envelope
        or payload.get("token_envelope_version") != EMAIL_VERIFICATION_OUTBOX_TOKEN_VERSION
    ):
        raise EmailVerificationPayloadError("verification email payload is missing token envelope")
    try:
        token_id = UUID(token_id_raw)
    except ValueError as exc:
        raise EmailVerificationPayloadError("verification email payload has invalid token id") from exc

    row = await session.get(EmailVerificationToken, token_id)
    if row is None:
        raise EmailVerificationPayloadError("verification token row not found")
    try:
        token = unseal_email_verification_outbox_token(token_envelope)
    except EmailVerificationError as exc:
        raise EmailVerificationPayloadError("verification token envelope is invalid") from exc
    if row.token_hash != hash_account_security_token(token):
        raise EmailVerificationPayloadError("verification token envelope does not match row")
    return _clean_email(row.email_normalized), token


@register_outbox_handler(EMAIL_VERIFICATION_EVENT_TYPE)
async def dispatch_email_verification(
    session: AsyncSession,
    payload: dict[str, Any],
) -> None:
    """Validate the outbox payload and delegate to the email service."""
    if "email" in payload or "token" in payload:
        recipient = _clean_email(payload.get("email"))
        token = _clean_token(payload.get("token"))
    else:
        recipient, token = await _resolve_delivery_payload(session, payload)
    await send_verification_email(
        to=recipient,
        token=token,
    )


__all__ = [
    "EmailVerificationPayloadError",
    "dispatch_email_verification",
]
