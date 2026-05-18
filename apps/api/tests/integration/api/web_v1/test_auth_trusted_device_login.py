"""US4 integration tests for trusted-device login bypass."""

# ruff: noqa: F401,F811,I001

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from echoroo.models.trusted_device import TrustedDevice
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


def _set_bypass_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "TRUSTED_DEVICE_BYPASS_ENABLED", enabled)
    monkeypatch.setattr(auth_module.settings, "TRUSTED_DEVICE_BYPASS_ENABLED", enabled)


async def _issue_trusted_cookie(
    session_factory: object,
    *,
    user_id: UUID,
) -> tuple[str, UUID]:
    from echoroo.models.user import User
    from echoroo.services.trusted_device_service import TrustedDeviceService

    async with session_factory() as session, session.begin():  # type: ignore[operator]
        user = await session.get(User, user_id)
        assert user is not None
        issued = await TrustedDeviceService(session).issue_device(
            user=user,
            label="Known browser",
            ip="127.0.0.1",
            user_agent="pytest-agent",
        )
        return issued.raw_secret, issued.device.id


async def _update_device(
    session_factory: object,
    device_id: UUID,
    **values: object,
) -> None:
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        device = await session.get(TrustedDevice, device_id)
        assert device is not None
        for key, value in values.items():
            setattr(device, key, value)


async def _login(client: AsyncClient) -> Any:
    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return response.json()


def _set_trusted_cookie(client: AsyncClient, raw_secret: str) -> None:
    from echoroo.core.settings import get_settings

    client.cookies.set(
        get_settings().TRUSTED_DEVICE_COOKIE_NAME,
        raw_secret,
        path="/",
    )


async def test_login_with_valid_trusted_device_cookie_returns_complete_session(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.core.settings import get_settings

    _set_bypass_flag(monkeypatch, True)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    raw_secret, _device_id = await _issue_trusted_cookie(session_factory, user_id=user.id)
    _set_trusted_cookie(client, raw_secret)

    body = await _login(client)

    assert body["login_state"] == "complete"
    assert body["access_token"]
    assert body["expires_in"] == get_settings().web_access_token_ttl_seconds
    assert body["trusted_device_used"] is True
    assert "interim_token" not in body


@pytest.mark.parametrize("cookie_state", ["missing", "revoked", "expired", "flag_off"])
async def test_login_falls_back_to_2fa_when_trusted_device_cannot_be_used(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
    cookie_state: str,
) -> None:
    _set_bypass_flag(monkeypatch, cookie_state != "flag_off")
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    raw_secret, device_id = await _issue_trusted_cookie(session_factory, user_id=user.id)

    if cookie_state != "missing":
        _set_trusted_cookie(client, raw_secret)
    if cookie_state == "revoked":
        await _update_device(session_factory, device_id, revoked_at=datetime.now(UTC))
    if cookie_state == "expired":
        await _update_device(
            session_factory,
            device_id,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

    body = await _login(client)

    assert body["login_state"] == "2fa_required"
    assert body["interim_token"]
    assert "access_token" not in body
