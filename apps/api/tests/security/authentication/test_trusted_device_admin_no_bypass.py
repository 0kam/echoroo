"""US5 guardrails: trusted devices must not bypass privileged 2FA."""

# ruff: noqa: F401,F811,I001

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from echoroo.models.superuser import Superuser
from tests.integration.api.web_v1.test_auth import _create_user
from tests.integration.api.web_v1.test_auth_totp import (
    _enroll_user,
    _patch_totp_dependencies,
    client_fixture,
    fake_redis,
    pg_container,
    session_factory_fixture,
    upgraded_db,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_privileged_rows(session_factory: object) -> None:
    yield
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        await session.execute(text("DELETE FROM trusted_devices"))
        await session.execute(text("DELETE FROM superusers"))


def _set_bypass_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool = True) -> None:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "TRUSTED_DEVICE_BYPASS_ENABLED", enabled)
    monkeypatch.setattr(auth_module.settings, "TRUSTED_DEVICE_BYPASS_ENABLED", enabled)


def _set_trusted_cookie(client: AsyncClient, raw_secret: str) -> None:
    from echoroo.core.settings import get_settings

    client.cookies.set(
        get_settings().TRUSTED_DEVICE_COOKIE_NAME,
        raw_secret,
        path="/",
    )


async def _promote_superuser(session_factory: object, user_id: UUID) -> None:
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        session.add(
            Superuser(
                user_id=user_id,
                added_by_id=None,
                added_at=datetime.now(UTC) - timedelta(days=1),
                webauthn_credentials=[],
                allowed_ip_cidrs=[],
                revoked_at=None,
            )
        )


async def _issue_trusted_cookie(
    session_factory: object,
    *,
    user_id: UUID,
) -> str:
    from echoroo.models.user import User
    from echoroo.services.trusted_device_service import TrustedDeviceService

    async with session_factory() as session, session.begin():  # type: ignore[operator]
        user = await session.get(User, user_id)
        assert user is not None
        issued = await TrustedDeviceService(session).issue_device(
            user=user,
            label="Admin browser",
            ip="127.0.0.1",
            user_agent="pytest-agent",
        )
        return issued.raw_secret


async def test_service_rejects_trusted_device_bypass_for_superuser_context(
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.models.user import User
    from echoroo.services.trusted_device_service import TrustedDeviceService

    _set_bypass_flag(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    await _promote_superuser(session_factory, user.id)
    raw_secret = await _issue_trusted_cookie(session_factory, user_id=user.id)

    async with session_factory() as session, session.begin():  # type: ignore[operator]
        loaded = await session.get(User, user.id)
        assert loaded is not None
        loaded.is_superuser = True  # type: ignore[attr-defined]
        evaluation = await TrustedDeviceService(session).evaluate_login_bypass(
            user=loaded,
            raw_secret=raw_secret,
            recent_password_failure=False,
            ip="127.0.0.1",
            user_agent="pytest-agent",
        )

    assert evaluation.accepted is False
    assert evaluation.reject_reason == "privileged_user"


async def test_login_with_superuser_trusted_device_still_requires_2fa(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_bypass_flag(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    await _promote_superuser(session_factory, user.id)
    _set_trusted_cookie(
        client,
        await _issue_trusted_cookie(session_factory, user_id=user.id),
    )

    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["login_state"] == "2fa_required"
    assert body["interim_token"]
    assert "access_token" not in body
    assert body.get("trusted_device_used") is not True
