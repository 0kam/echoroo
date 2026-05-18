"""US3 trusted-device service contract tests.

These tests intentionally describe the service API before T056 implements
``echoroo.services.trusted_device_service``.
"""

from __future__ import annotations

import importlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio

_RAW_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def _service_module():
    return importlib.import_module("echoroo.services.trusted_device_service")


async def _create_user(session: AsyncSession, email: str = "trusted@example.com") -> User:
    user = User(
        email=email,
        password_hash=hash_password("CorrectHorseBatteryStaple123!"),
        display_name="Trusted Device User",
        security_stamp="s" * 64,
        two_factor_enabled=True,
        email_verified_at=datetime.now(UTC),
    )
    session.add(user)
    await session.flush()
    return user


async def _active_devices(session: AsyncSession, user: User) -> list[TrustedDevice]:
    rows = await session.scalars(
        select(TrustedDevice)
        .where(TrustedDevice.user_id == user.id, TrustedDevice.revoked_at.is_(None))
        .order_by(TrustedDevice.created_at)
    )
    return list(rows)


async def test_issue_device_returns_raw_secret_but_persists_hash_only(
    db_session: AsyncSession,
) -> None:
    """Issuance returns a one-time cookie secret while DB stores only its hash."""
    mod = _service_module()
    user = await _create_user(db_session)
    service = mod.TrustedDeviceService(db_session)

    issued = await service.issue_device(
        user=user,
        label="Work laptop",
        ip="203.0.113.10",
        user_agent="pytest-agent",
    )
    await db_session.flush()

    assert _RAW_SECRET_RE.fullmatch(issued.raw_secret)
    assert issued.device.user_id == user.id
    assert issued.device.label == "Work laptop"
    assert issued.device.security_stamp == user.security_stamp
    assert issued.device.expires_at > datetime.now(UTC) + timedelta(days=29)
    assert issued.device.device_secret_hash != issued.raw_secret
    assert len(issued.device.device_secret_hash) == 64

    stored = await db_session.get(TrustedDevice, issued.device.id)
    assert stored is not None
    assert stored.device_secret_hash == issued.device.device_secret_hash
    assert issued.raw_secret not in stored.device_secret_hash


async def test_issue_device_enforces_five_active_devices_and_revokes_oldest(
    db_session: AsyncSession,
) -> None:
    """Creating the sixth active device revokes the oldest active device."""
    mod = _service_module()
    user = await _create_user(db_session, "trusted-cap@example.com")
    service = mod.TrustedDeviceService(db_session)

    issued = []
    for index in range(6):
        issued.append(
            await service.issue_device(
                user=user,
                label=f"device-{index}",
                ip=f"203.0.113.{index}",
                user_agent="pytest-agent",
            )
        )
        await db_session.flush()

    active = await _active_devices(db_session, user)
    revoked_oldest = await db_session.get(TrustedDevice, issued[0].device.id)

    assert len(active) == 5
    assert revoked_oldest is not None
    assert revoked_oldest.revoked_at is not None
    assert {device.label for device in active} == {
        "device-1",
        "device-2",
        "device-3",
        "device-4",
        "device-5",
    }


async def test_list_active_devices_excludes_expired_and_revoked_devices(
    db_session: AsyncSession,
) -> None:
    """The account view should show only active, unexpired trusted devices."""
    mod = _service_module()
    user = await _create_user(db_session, "trusted-list@example.com")
    service = mod.TrustedDeviceService(db_session)
    active = await service.issue_device(user=user, label="active")
    revoked = await service.issue_device(user=user, label="revoked")
    expired = await service.issue_device(user=user, label="expired")
    revoked.device.revoked_at = datetime.now(UTC)
    expired.device.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.flush()

    devices = await service.list_active_devices(user=user)

    assert [device.id for device in devices] == [active.device.id]


async def test_revoke_device_and_revoke_all_mark_only_user_devices_revoked(
    db_session: AsyncSession,
) -> None:
    """Users can revoke one device or all of their own active devices."""
    mod = _service_module()
    user = await _create_user(db_session, "trusted-revoke@example.com")
    other = await _create_user(db_session, "trusted-other@example.com")
    service = mod.TrustedDeviceService(db_session)
    first = await service.issue_device(user=user, label="first")
    second = await service.issue_device(user=user, label="second")
    other_device = await service.issue_device(user=other, label="other")

    assert await service.revoke_device(user=user, device_id=first.device.id) is True
    await db_session.refresh(first.device)
    assert first.device.revoked_at is not None

    assert await service.revoke_device(user=user, device_id=other_device.device.id) is False

    revoked_count = await service.revoke_all_for_user(user=user)
    await db_session.refresh(second.device)
    await db_session.refresh(other_device.device)

    assert revoked_count == 1
    assert second.device.revoked_at is not None
    assert other_device.device.revoked_at is None
