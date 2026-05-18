"""US4 security tests for trusted-device bypass rejection paths."""

# ruff: noqa: F401,F811,I001

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

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
            label="Known browser",
            ip="127.0.0.1",
            user_agent="pytest-agent",
        )
        return issued.raw_secret


async def _rotate_user_security_stamp(session_factory: object, user_id: UUID) -> None:
    from echoroo.models.user import User

    async with session_factory() as session, session.begin():  # type: ignore[operator]
        user = await session.get(User, user_id)
        assert user is not None
        user.security_stamp = "r" * 64


async def _login(client: AsyncClient) -> Any:
    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return response.json()


async def test_malformed_trusted_device_cookie_does_not_bypass_2fa(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_bypass_flag(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    _set_trusted_cookie(client, "not-a-valid-trusted-device-secret")

    body = await _login(client)

    assert body["login_state"] == "2fa_required"
    assert body["interim_token"]
    assert "access_token" not in body


async def test_trusted_device_cookie_for_different_user_does_not_bypass_2fa(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_bypass_flag(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    other = await _create_user(
        session_factory,
        email="other@example.com",
        two_factor_enabled=False,
        security_stamp="o" * 64,
    )
    await _enroll_user(session_factory, other.id, fake_redis)
    _set_trusted_cookie(
        client,
        await _issue_trusted_cookie(session_factory, user_id=other.id),
    )

    body = await _login(client)

    assert body["login_state"] == "2fa_required"
    assert body["interim_token"]
    assert "access_token" not in body


async def test_trusted_device_cookie_with_stale_security_stamp_does_not_bypass_2fa(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_bypass_flag(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    _set_trusted_cookie(
        client,
        await _issue_trusted_cookie(session_factory, user_id=user.id),
    )
    await _rotate_user_security_stamp(session_factory, user.id)

    body = await _login(client)

    assert body["login_state"] == "2fa_required"
    assert body["interim_token"]
    assert "access_token" not in body


async def test_recent_failed_password_attempt_prevents_trusted_device_bypass(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_bypass_flag(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)
    _set_trusted_cookie(
        client,
        await _issue_trusted_cookie(session_factory, user_id=user.id),
    )

    failed = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong password"},
    )
    assert failed.status_code == 401

    body = await _login(client)

    assert body["login_state"] == "2fa_required"
    assert body["interim_token"]
    assert "access_token" not in body
