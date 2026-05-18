"""US2 security tests for email verification resend anti-enumeration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio

_RESEND_PATH = "/web-api/v1/auth/verify-email/resend"


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    email_verified_at: datetime | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Email Verification Resend",
        security_stamp=f"email-resend-{uuid4()}",
        two_factor_enabled=False,
        last_login_at=None,
        last_first_party_activity_at=datetime.now(UTC),
        email_verified_at=email_verified_at,
    )
    session.add(user)
    await session.flush()
    return user


async def _active_token_count(session: AsyncSession, user_id: object) -> int:
    result = await session.execute(
        sa.text(
            "SELECT count(*) FROM email_verification_tokens "
            "WHERE user_id = :user_id "
            "AND purpose = 'verify_email' "
            "AND consumed_at IS NULL "
            "AND superseded_at IS NULL"
        ),
        {"user_id": user_id},
    )
    return int(result.scalar_one())


async def _superseded_token_count(session: AsyncSession, user_id: object) -> int:
    result = await session.execute(
        sa.text(
            "SELECT count(*) FROM email_verification_tokens "
            "WHERE user_id = :user_id "
            "AND purpose = 'verify_email' "
            "AND superseded_at IS NOT NULL"
        ),
        {"user_id": user_id},
    )
    return int(result.scalar_one())


@pytest.mark.parametrize(
    "email",
    [
        "resend-known-unverified@example.com",
        "resend-missing-account@example.com",
        "RESEND-KNOWN-UNVERIFIED@example.com",
    ],
)
async def test_resend_returns_generic_accepted_without_account_enumeration(
    client: AsyncClient,
    db_session: AsyncSession,
    email: str,
) -> None:
    await _create_user(
        db_session,
        email="resend-known-unverified@example.com",
        email_verified_at=None,
    )
    await db_session.commit()

    response = await client.post(
        _RESEND_PATH,
        json={"email": email},
        headers={"X-Forwarded-For": "198.51.100.24"},
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}


async def test_resend_supersedes_previous_active_token_and_caps_active_tokens(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(
        db_session,
        email="resend-supersede@example.com",
        email_verified_at=None,
    )
    await db_session.commit()

    first = await client.post(_RESEND_PATH, json={"email": user.email})
    second = await client.post(_RESEND_PATH, json={"email": user.email})

    assert first.status_code == 202
    assert second.status_code == 202
    assert await _active_token_count(db_session, user.id) == 1
    assert await _superseded_token_count(db_session, user.id) == 1


async def test_resend_rate_limits_repeated_requests_without_enumerating_account(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(
        db_session,
        email="resend-rate-limit@example.com",
        email_verified_at=None,
    )
    await db_session.commit()

    responses = [
        await client.post(
            _RESEND_PATH,
            json={"email": user.email},
            headers={"X-Forwarded-For": "203.0.113.77"},
        )
        for _ in range(8)
    ]

    assert responses[0].status_code == 202
    limited = [response for response in responses if response.status_code == 429]
    assert limited
    assert limited[0].json()["code"] == "ERR_EMAIL_VERIFICATION_RESEND_RATE_LIMITED"
    assert "Retry-After" in limited[0].headers
