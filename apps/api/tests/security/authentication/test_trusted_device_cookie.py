"""US3 security tests for trusted-device cookie issuance."""

# ruff: noqa: F401,F811,I001

from __future__ import annotations

from typing import Any

import pyotp
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select

from echoroo.models.trusted_device import TrustedDevice
from tests.integration.api.web_v1.test_auth import _create_user
from tests.integration.api.web_v1.test_auth_totp import (
    _enroll_user,
    _issue_interim_token_for_user,
    _patch_totp_dependencies,
    _setup_interim,
    client_fixture,
    fake_redis,
    pg_container,
    session_factory_fixture,
    upgraded_db,
)

pytestmark = pytest.mark.asyncio


def _trusted_cookie_header(response: Response) -> str:
    from echoroo.core.settings import get_settings

    cookie_name = get_settings().TRUSTED_DEVICE_COOKIE_NAME
    matches = [
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{cookie_name}=")
    ]
    assert matches, f"{cookie_name} cookie was not set"
    return matches[0]


async def _trusted_devices(session_factory: object) -> list[TrustedDevice]:
    async with session_factory() as session:  # type: ignore[operator]
        rows = await session.scalars(
            select(TrustedDevice).where(TrustedDevice.revoked_at.is_(None))
        )
        return list(rows)


def _enable_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "TRUSTED_DEVICE_REGISTRATION_ENABLED", True)
    monkeypatch.setattr(auth_module.settings, "TRUSTED_DEVICE_REGISTRATION_ENABLED", True)


async def test_2fa_challenge_sets_secure_trusted_device_cookie_and_hash_only_db(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.core.settings import get_settings

    _enable_registration(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    secret, _backup_codes = await _enroll_user(session_factory, user.id, fake_redis)

    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory,
                user.id,
                "2fa_challenge",
            ),
            "method": "totp",
            "code": pyotp.TOTP(secret).now(),
            "trust_device": True,
            "device_label": "Work laptop",
        },
    )

    assert response.status_code == 200
    assert response.json()["trusted_device_created"] is True
    cookie = _trusted_cookie_header(response)
    cookie_value = response.cookies[get_settings().TRUSTED_DEVICE_COOKIE_NAME]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert f"Max-Age={get_settings().TRUSTED_DEVICE_COOKIE_TTL_SECONDS}" in cookie
    assert len(cookie_value) == 43

    devices = await _trusted_devices(session_factory)
    assert len(devices) == 1
    assert devices[0].label == "Work laptop"
    assert devices[0].device_secret_hash != cookie_value
    assert cookie_value not in devices[0].device_secret_hash


async def test_totp_setup_confirm_sets_trusted_device_cookie_when_requested(
    client: AsyncClient,
    session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_registration(monkeypatch)
    await _create_user(session_factory, two_factor_enabled=False)
    setup = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": await _setup_interim(client)},
    )
    assert setup.status_code == 200
    setup_body = setup.json()

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp/confirm",
        json={
            "interim_token": setup_body["next_interim_token"],
            "secret": setup_body["secret"],
            "totp_code": pyotp.TOTP(setup_body["secret"]).now(),
            "trust_device": True,
            "device_label": "Setup browser",
        },
    )

    assert response.status_code == 200
    assert response.json()["trusted_device_created"] is True
    cookie = _trusted_cookie_header(response)
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


async def test_trusted_device_cookie_not_set_when_registration_flag_disabled(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
) -> None:
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory, two_factor_enabled=False)
    secret, _backup_codes = await _enroll_user(session_factory, user.id, fake_redis)

    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory,
                user.id,
                "2fa_challenge",
            ),
            "method": "totp",
            "code": pyotp.TOTP(secret).now(),
            "trust_device": True,
        },
    )

    assert response.status_code == 200
    assert get_settings().TRUSTED_DEVICE_COOKIE_NAME not in response.cookies
    assert response.json()["trusted_device_created"] is False
    assert await _trusted_devices(session_factory) == []
