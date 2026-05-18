"""US3 integration tests for account trusted-device management routes."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pyotp
import pytest
from httpx import ASGITransport, AsyncClient, Response

from echoroo.models.trusted_device import TrustedDevice
from tests.integration.api.web_v1._helpers import assert_csrf_required
from tests.integration.api.web_v1.test_auth import _create_user
from tests.integration.api.web_v1.test_auth_totp import (  # noqa: F401
    _patch_totp_dependencies,
    _setup_interim,
    fake_redis,
    pg_container,
    session_factory_fixture,
    upgraded_db,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(name="client")
async def account_client_fixture(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: object,
) -> AsyncIterator[AsyncClient]:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.database import get_db
    from echoroo.main import create_app
    from echoroo.services.auth_service import AlwaysFreshHibp, InMemoryLoginAttemptRecorder

    async def override_get_db() -> AsyncGenerator[Any, None]:
        async with session_factory() as session:  # type: ignore[operator]
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def no_audit(**_kwargs: Any) -> None:
        return None

    async def no_login_notification(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(auth_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(auth_module, "_write_platform_audit", no_audit)
    monkeypatch.setattr(auth_module, "_record_login_notification", no_login_notification)
    monkeypatch.setattr(auth_module, "compute_pii_hash", lambda value: f"hash:{value}")
    monkeypatch.setattr(auth_module, "_login_attempts", InMemoryLoginAttemptRecorder())
    monkeypatch.setattr(auth_module, "_hibp_checker", AlwaysFreshHibp())
    auth_module._register_windows.clear()  # noqa: SLF001 - test isolation

    from echoroo.middleware.two_factor_enforcement import (
        TwoFactorEnforcementMiddleware,
    )

    async def passthrough_two_factor(
        self: TwoFactorEnforcementMiddleware,
        request: Any,
        call_next: Any,
    ) -> Any:
        return await call_next(request)

    monkeypatch.setattr(
        TwoFactorEnforcementMiddleware,
        "dispatch",
        passthrough_two_factor,
    )

    app = create_app(session_factory=session_factory)
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def _login_with_session(
    client: AsyncClient,
    session_factory: object,
) -> tuple[Any, dict[str, str]]:
    user = await _create_user(session_factory, two_factor_enabled=False)
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
        },
    )
    assert response.status_code == 200
    return user, {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


async def _seed_trusted_device(
    session_factory: object,
    *,
    user_id: UUID,
    label: str,
    hash_suffix: str,
    revoked: bool = False,
) -> TrustedDevice:
    device = TrustedDevice(
        user_id=user_id,
        device_secret_hash=f"{hash_suffix:0>64}"[-64:],
        security_stamp="s" * 64,
        label=label,
        created_at=datetime.now(UTC) - timedelta(minutes=10),
        last_used_at=None,
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=datetime.now(UTC) if revoked else None,
        created_ip_hash="a" * 64,
        created_user_agent_hash="b" * 64,
        last_ip_hash=None,
        last_user_agent_hash=None,
    )
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        session.add(device)
    return device


async def _get_device(session_factory: object, device_id: UUID) -> TrustedDevice:
    async with session_factory() as session:  # type: ignore[operator]
        device = await session.get(TrustedDevice, device_id)
        assert device is not None
        return device


async def _post_without_csrf(
    client: AsyncClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str],
) -> Response:
    return await assert_csrf_required(client, method, path, headers=headers)


async def test_get_account_trusted_devices_lists_active_devices_for_current_user(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user, headers = await _login_with_session(client, session_factory)
    active = await _seed_trusted_device(
        session_factory,
        user_id=user.id,
        label="Work laptop",
        hash_suffix="1",
    )
    await _seed_trusted_device(
        session_factory,
        user_id=user.id,
        label="Revoked browser",
        hash_suffix="2",
        revoked=True,
    )

    response = await client.get("/web-api/v1/account/trusted-devices", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [device["id"] for device in body["devices"]] == [str(active.id)]
    assert body["devices"][0]["label"] == "Work laptop"
    assert body["devices"][0]["current_device"] is False
    assert body["devices"][0]["created_at"]
    assert body["devices"][0]["expires_at"]


async def test_delete_account_trusted_device_revokes_one_device_and_requires_csrf(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user, headers = await _login_with_session(client, session_factory)
    device = await _seed_trusted_device(
        session_factory,
        user_id=user.id,
        label="Work laptop",
        hash_suffix="3",
    )

    await _post_without_csrf(
        client,
        "DELETE",
        f"/web-api/v1/account/trusted-devices/{device.id}",
        headers=headers,
    )
    response = await client.delete(
        f"/web-api/v1/account/trusted-devices/{device.id}",
        headers=headers,
    )

    assert response.status_code == 204
    revoked = await _get_device(session_factory, device.id)
    assert revoked.revoked_at is not None


async def test_delete_account_trusted_device_cannot_revoke_another_users_device(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user, headers = await _login_with_session(client, session_factory)
    other = await _create_user(
        session_factory,
        email="trusted-other-account@example.com",
        two_factor_enabled=True,
    )
    device = await _seed_trusted_device(
        session_factory,
        user_id=other.id,
        label="Other browser",
        hash_suffix="4",
    )

    response = await client.delete(
        f"/web-api/v1/account/trusted-devices/{device.id}",
        headers=headers,
    )

    assert response.status_code == 204
    untouched = await _get_device(session_factory, device.id)
    assert untouched.revoked_at is None
    assert user.id != other.id


async def test_post_revoke_all_account_trusted_devices_revokes_current_user_only(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user, headers = await _login_with_session(client, session_factory)
    first = await _seed_trusted_device(
        session_factory,
        user_id=user.id,
        label="First",
        hash_suffix="5",
    )
    second = await _seed_trusted_device(
        session_factory,
        user_id=user.id,
        label="Second",
        hash_suffix="6",
    )

    await _post_without_csrf(
        client,
        "POST",
        "/web-api/v1/account/trusted-devices/revoke-all",
        headers=headers,
    )
    response = await client.post(
        "/web-api/v1/account/trusted-devices/revoke-all",
        headers=headers,
    )

    assert response.status_code == 204
    assert (await _get_device(session_factory, first.id)).revoked_at is not None
    assert (await _get_device(session_factory, second.id)).revoked_at is not None


async def test_account_trusted_device_routes_require_session(
    client: AsyncClient,
) -> None:
    responses = [
        await client.get("/web-api/v1/account/trusted-devices"),
        await client.delete(
            "/web-api/v1/account/trusted-devices/00000000-0000-0000-0000-000000000000"
        ),
        await client.post("/web-api/v1/account/trusted-devices/revoke-all"),
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
