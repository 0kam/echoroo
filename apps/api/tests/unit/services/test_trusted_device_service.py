"""US3 trusted-device service contract tests.

These tests intentionally describe the service API before T056 implements
``echoroo.services.trusted_device_service``.
"""

from __future__ import annotations

import importlib
import re
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.superuser import Superuser
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

    revoked_count = await service.revoke_all_for_user(user=user, reason="user_self_revoke")
    await db_session.refresh(second.device)
    await db_session.refresh(other_device.device)

    assert revoked_count == 1
    assert second.device.revoked_at is not None
    assert other_device.device.revoked_at is None


async def test_evaluate_login_bypass_rejects_unknown_secret(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "trusted-missing@example.com")

    evaluation = await mod.TrustedDeviceService(db_session).evaluate_login_bypass(
        user=user,
        raw_secret="A" * 43,
        recent_password_failure=False,
    )

    assert evaluation.accepted is False
    assert evaluation.reject_reason == "not_found"


async def test_evaluate_login_bypass_rejects_other_users_device(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "trusted-owner@example.com")
    other = await _create_user(db_session, "trusted-device-owner@example.com")
    service = mod.TrustedDeviceService(db_session)
    issued = await service.issue_device(user=other, label="other")

    evaluation = await service.evaluate_login_bypass(
        user=user,
        raw_secret=issued.raw_secret,
        recent_password_failure=False,
    )

    assert evaluation.accepted is False
    assert evaluation.device == issued.device
    assert evaluation.reject_reason == "user_mismatch"


@pytest.mark.parametrize(
    ("mutate_device", "expected_reason"),
    [
        (lambda device: setattr(device, "revoked_at", datetime.now(UTC)), "revoked"),
        (
            lambda device: setattr(
                device,
                "expires_at",
                datetime.now(UTC) - timedelta(seconds=1),
            ),
            "expired",
        ),
        (
            lambda device: setattr(device, "security_stamp", "old-security-stamp"),
            "security_stamp_mismatch",
        ),
    ],
)
async def test_evaluate_login_bypass_rejects_inactive_or_stale_device(
    db_session: AsyncSession,
    mutate_device: object,
    expected_reason: str,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, f"trusted-{expected_reason}@example.com")
    service = mod.TrustedDeviceService(db_session)
    issued = await service.issue_device(user=user, label=expected_reason)
    mutate_device(issued.device)  # type: ignore[operator]
    await db_session.flush()

    evaluation = await service.evaluate_login_bypass(
        user=user,
        raw_secret=issued.raw_secret,
        recent_password_failure=False,
    )

    assert evaluation.accepted is False
    assert evaluation.device == issued.device
    assert evaluation.reject_reason == expected_reason


async def test_evaluate_login_bypass_accepts_and_updates_last_used_metadata(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "trusted-accepted@example.com")
    service = mod.TrustedDeviceService(db_session)
    issued = await service.issue_device(user=user, label="Accepted")
    now = datetime.now(UTC)

    evaluation = await service.evaluate_login_bypass(
        user=user,
        raw_secret=issued.raw_secret,
        recent_password_failure=False,
        ip="203.0.113.55",
        user_agent="pytest-agent",
        now=now,
    )

    assert evaluation.accepted is True
    assert evaluation.device == issued.device
    assert issued.device.last_used_at == now
    assert issued.device.last_ip_hash is not None
    assert issued.device.last_user_agent_hash is not None


async def test_is_privileged_user_detects_active_superuser_row(
    db_session: AsyncSession,
) -> None:
    mod = _service_module()
    user = await _create_user(db_session, "trusted-superuser@example.com")
    db_session.add(
        Superuser(
            user_id=user.id,
            added_by_id=None,
            added_at=datetime.now(UTC),
            webauthn_credentials=[],
            allowed_ip_cidrs=[],
            revoked_at=None,
        )
    )
    await db_session.flush()

    assert await mod.TrustedDeviceService(db_session)._is_privileged_user(user) is True


async def test_security_stamp_rotation_listener_skips_non_persistent_users() -> None:
    mod = _service_module()
    transient_user = User(
        id=uuid4(),
        email="transient@example.com",
        password_hash="hash",
        display_name="Transient",
        security_stamp="s" * 64,
    )
    fake_session = MagicMock()
    fake_session.dirty = [transient_user]

    mod._revoke_devices_on_security_stamp_rotation(fake_session, None, None)

    fake_session.execute.assert_not_called()


async def test_normalize_label_returns_none_for_missing_or_blank_label() -> None:
    mod = _service_module()

    assert mod._normalize_label(None) is None
    assert mod._normalize_label("   ") is None
