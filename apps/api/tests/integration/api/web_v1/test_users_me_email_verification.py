"""US2 integration tests for current-user email verification state."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.auth import issue_access_token
from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    email_verified_at: datetime | None,
) -> User:
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Current User Email Verification",
        security_stamp=f"email-state-{uuid4()}",
        two_factor_enabled=False,
        last_login_at=None,
        last_first_party_activity_at=datetime.now(UTC),
        email_verified_at=email_verified_at,
    )
    session.add(user)
    await session.flush()
    return user


async def _web_session_headers(
    client: AsyncClient,
    session: AsyncSession,
    user: User,
) -> dict[str, str]:
    settings = get_settings()
    family_id = uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, now())"
        ),
        {"family_id": family_id, "user_id": user.id},
    )
    await session.commit()
    access_token = issue_access_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    client.cookies.set(
        settings.web_session_cookie_name,
        str(family_id),
        path="/web-api/v1/",
    )
    return {"Authorization": f"Bearer {access_token}"}


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_current_user_returns_null_email_verified_at_for_unverified_user(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(
        db_session,
        email="users-me-unverified@example.com",
        email_verified_at=None,
    )
    headers = await _web_session_headers(client, db_session, user)

    response = await client.get("/web-api/v1/users/me", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["email"] == user.email
    assert body["email_verified_at"] is None


async def test_current_user_returns_iso_email_verified_at_for_verified_user(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    verified_at = datetime(2026, 5, 18, 3, 4, 5, tzinfo=UTC)
    user = await _create_user(
        db_session,
        email="users-me-verified@example.com",
        email_verified_at=verified_at,
    )
    headers = await _web_session_headers(client, db_session, user)

    response = await client.get("/web-api/v1/users/me", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["email_verified_at"] is not None
    assert _parse_iso_datetime(body["email_verified_at"]) == verified_at
