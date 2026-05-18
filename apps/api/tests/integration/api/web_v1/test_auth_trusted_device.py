"""US3 integration tests for trusting a device after 2FA success."""

# ruff: noqa: F401,F811,I001

from __future__ import annotations

from typing import Any

import pyotp
import pytest
from httpx import AsyncClient
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


def _enable_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "TRUSTED_DEVICE_REGISTRATION_ENABLED", True)
    monkeypatch.setattr(auth_module.settings, "TRUSTED_DEVICE_REGISTRATION_ENABLED", True)


async def _active_trusted_devices(session_factory: object) -> list[TrustedDevice]:
    async with session_factory() as session:  # type: ignore[operator]
        rows = await session.scalars(
            select(TrustedDevice).where(TrustedDevice.revoked_at.is_(None))
        )
        return list(rows)


async def test_2fa_challenge_accepts_trust_device_and_device_label(
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
            "device_label": "Personal browser",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["trusted_device_created"] is True
    assert get_settings().TRUSTED_DEVICE_COOKIE_NAME in response.cookies
    devices = await _active_trusted_devices(session_factory)
    assert len(devices) == 1
    assert devices[0].label == "Personal browser"


async def test_totp_setup_confirm_accepts_trust_device_and_device_label(
    client: AsyncClient,
    session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.core.settings import get_settings

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
            "device_label": "First login browser",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["backup_codes"]
    assert body["trusted_device_created"] is True
    assert get_settings().TRUSTED_DEVICE_COOKIE_NAME in response.cookies
    devices = await _active_trusted_devices(session_factory)
    assert len(devices) == 1
    assert devices[0].label == "First login browser"


async def test_trust_device_false_creates_no_trusted_device(
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
            "trust_device": False,
            "device_label": "Ignored label",
        },
    )

    assert response.status_code == 200
    assert response.json()["trusted_device_created"] is False
    assert get_settings().TRUSTED_DEVICE_COOKIE_NAME not in response.cookies
    assert await _active_trusted_devices(session_factory) == []


async def test_registration_flag_off_creates_no_trusted_device(
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
            "device_label": "Ignored label",
        },
    )

    assert response.status_code == 200
    assert response.json()["trusted_device_created"] is False
    assert get_settings().TRUSTED_DEVICE_COOKIE_NAME not in response.cookies
    assert await _active_trusted_devices(session_factory) == []


async def test_invalid_2fa_does_not_create_trusted_device(
    client: AsyncClient,
    session_factory: object,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_registration(monkeypatch)
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)

    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory,
                user.id,
                "2fa_challenge",
            ),
            "method": "totp",
            "code": "000000",
            "trust_device": True,
            "device_label": "Should not persist",
        },
    )

    assert response.status_code == 401
    assert await _active_trusted_devices(session_factory) == []
