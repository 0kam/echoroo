"""US5 redaction tests for spec 010 auth security events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.audit import sanitize_value
from echoroo.core.security import hash_password
from echoroo.models.user import User
from echoroo.services.email_verification_service import EmailVerificationService

pytestmark = pytest.mark.asyncio


_RAW_EMAIL = "redaction-target@example.com"
_RAW_IP = "198.51.100.44"
_RAW_USER_AGENT = "Mozilla/5.0 EchorooRedactionTest/010"
_RAW_EMAIL_TOKEN = "emailVerificationTokenSecretValue010abcXYZ_"
_RAW_TRUSTED_DEVICE_SECRET = "trustedDeviceCookieSecretValue010abcXYZ_123"


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _assert_no_raw_values(payload: Any, *raw_values: str) -> None:
    serialized = _stable_json(payload)
    leaked = [value for value in raw_values if value in serialized]
    assert leaked == [], f"auth event payload leaked raw values: {leaked!r}"


async def _create_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Auth Redaction Test",
        security_stamp="security-stamp-for-auth-redaction-tests",
        two_factor_enabled=True,
        last_login_at=None,
        last_first_party_activity_at=datetime.now(UTC),
        email_verified_at=None,
    )
    session.add(user)
    await session.flush()
    return user


async def test_auth_event_sanitizer_redacts_spec_010_token_cookie_and_client_fields() -> None:
    payload = {
        "email": _RAW_EMAIL,
        "verification_token": _RAW_EMAIL_TOKEN,
        "trusted_device_cookie_secret": _RAW_TRUSTED_DEVICE_SECRET,
        "ip": _RAW_IP,
        "user_agent": _RAW_USER_AGENT,
        "nested": {
            "verification_url": (
                "https://app.example.test/verify-email?"
                f"token={_RAW_EMAIL_TOKEN}&email={_RAW_EMAIL}"
            ),
            "trusted_device": {
                "secret": _RAW_TRUSTED_DEVICE_SECRET,
                "last_ip": _RAW_IP,
                "last_user_agent": _RAW_USER_AGENT,
            },
        },
    }

    sanitized = sanitize_value(payload, hash_fn=lambda value: f"hash:{len(value)}")

    _assert_no_raw_values(
        sanitized,
        _RAW_EMAIL,
        _RAW_EMAIL_TOKEN,
        _RAW_TRUSTED_DEVICE_SECRET,
        _RAW_IP,
        _RAW_USER_AGENT,
    )
    assert "redacted" in _stable_json(sanitized)


async def test_email_verification_outbox_payload_does_not_include_raw_token_or_pii(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "outbox-redaction@example.com")
    service = EmailVerificationService(db_session)

    issued = await service.issue_verification_token(
        user=user,
        email="Outbox-Redaction@Example.com",
        ip=_RAW_IP,
        user_agent=_RAW_USER_AGENT,
    )

    row = (
        await db_session.execute(
            text(
                "SELECT payload FROM outbox_events "
                "WHERE event_type = 'auth.email_verification.requested' "
                "ORDER BY created_at DESC LIMIT 1"
            )
        )
    ).mappings().one()
    payload = row["payload"]

    _assert_no_raw_values(
        payload,
        issued.token,
        "outbox-redaction@example.com",
        "Outbox-Redaction@Example.com",
        _RAW_IP,
        _RAW_USER_AGENT,
    )
    assert "email_hash" in payload or "recipient_hash" in payload
    assert "token_hash" in payload or "token_hash_prefix" in payload
