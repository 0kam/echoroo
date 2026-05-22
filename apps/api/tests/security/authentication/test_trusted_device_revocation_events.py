"""US5 security tests for trusted-device bulk revocation hooks.

spec/011 Step 10 removed the ``test_password_reset_confirm_*`` case and
the ``email_verified_at`` assertions in the email-change case because
both the self-service password-reset surface and the
``users.email_verified_at`` column were deleted alongside the
email-verification subsystem (FR-011-002 / FR-011-005). The remaining
cases continue to verify the security-event hooks documented for spec
010 US5.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.user import User
from echoroo.schemas.user import PasswordChangeRequest
from echoroo.services.trusted_device_service import TrustedDeviceService

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    async def delete(self, *names: str) -> int:
        return len(names)


async def _create_user(
    session: AsyncSession,
    email: str,
    *,
    security_stamp: str = "s" * 64,
) -> User:
    now = datetime.now(UTC)
    user = User(
        email=email,
        password_hash=hash_password("OldPassword123!"),
        display_name="Trusted Device Revocation",
        security_stamp=security_stamp,
        two_factor_enabled=True,
        last_login_at=None,
        last_first_party_activity_at=now,
    )
    session.add(user)
    await session.flush()
    return user


async def _issue_active_devices(
    session: AsyncSession,
    user: User,
    *,
    count: int = 2,
) -> list[TrustedDevice]:
    service = TrustedDeviceService(session)
    devices: list[TrustedDevice] = []
    for index in range(count):
        issued = await service.issue_device(
            user=user,
            label=f"device-{index}",
            ip=f"198.51.100.{10 + index}",
            user_agent=f"pytest-revocation/{index}",
        )
        devices.append(issued.device)
    await session.flush()
    assert await _active_device_count(session, user) == count
    return devices


async def _active_device_count(session: AsyncSession, user: User) -> int:
    rows = await session.scalars(
        select(TrustedDevice).where(
            TrustedDevice.user_id == user.id,
            TrustedDevice.revoked_at.is_(None),
        )
    )
    return len(list(rows))


async def _assert_all_devices_revoked(
    session: AsyncSession,
    user: User,
    *,
    event: str,
) -> None:
    active_count = await _active_device_count(session, user)
    assert active_count == 0, f"{event} must revoke all active trusted devices"


async def test_password_change_revokes_all_trusted_devices(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.services.auth import AuthService
    from echoroo.services.user import UserService

    async def _revoke_user_tokens(self: AuthService, user_id: object) -> None:
        return None

    monkeypatch.setattr(AuthService, "revoke_user_tokens", _revoke_user_tokens)
    user = await _create_user(db_session, "password-change-revokes@example.com")
    await _issue_active_devices(db_session, user)

    await UserService(db_session).change_password(
        user.id,
        PasswordChangeRequest(
            current_password="OldPassword123!",
            new_password="ChangedPassword123!",
        ),
    )

    await _assert_all_devices_revoked(
        db_session,
        user,
        event="password change",
    )


async def test_two_factor_reset_revokes_all_trusted_devices(
    db_session: AsyncSession,
) -> None:
    from echoroo.services.two_factor_service import TwoFactorService

    user = await _create_user(db_session, "2fa-reset-revokes@example.com")
    await _issue_active_devices(db_session, user)

    await TwoFactorService(db_session, redis=_FakeRedis()).reset_user_two_factor(
        user,
        actor_id=user.id,
        reason="user_requested_recovery",
        commit=False,
    )
    await db_session.flush()

    await _assert_all_devices_revoked(db_session, user, event="2FA reset")


async def test_account_deletion_revokes_all_trusted_devices(
    db_session: AsyncSession,
) -> None:
    from echoroo.services.user_deletion_service import soft_delete_user

    user = await _create_user(db_session, "delete-revokes@example.com")
    await _issue_active_devices(db_session, user)

    await soft_delete_user(
        db_session,
        user_id=user.id,
        request_id="req-delete-revokes",
        ip="198.51.100.201",
        user_agent="pytest/delete",
    )
    await db_session.flush()

    await _assert_all_devices_revoked(db_session, user, event="account deletion")


async def test_email_change_security_event_revokes_trusted_devices(
    db_session: AsyncSession,
) -> None:
    from echoroo.services.user import UserService

    user = await _create_user(db_session, "email-change-old@example.com")
    await _issue_active_devices(db_session, user)
    service = UserService(db_session)
    change_email = getattr(service, "change_email", None)

    assert change_email is not None, (
        "UserService.change_email must centralize email-change security behavior"
    )
    await change_email(
        user.id,
        "email-change-new@example.com",
        ip="198.51.100.202",
        user_agent="pytest/email-change",
    )
    await db_session.refresh(user)

    assert user.email == "email-change-new@example.com"
    # spec/011 Step 10 (FR-011-002): ``email_verified_at`` was dropped
    # alongside the email-verification subsystem; the change_email
    # contract is now "the new email is persisted + every trusted
    # device is revoked", with no verification-timestamp side-effect.
    await _assert_all_devices_revoked(db_session, user, event="email change")


async def test_security_stamp_rotation_revokes_existing_trusted_devices(
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, "stamp-rotation-revokes@example.com")
    await _issue_active_devices(db_session, user)

    user.security_stamp = "r" * 64
    db_session.add(user)
    await db_session.flush()

    await _assert_all_devices_revoked(
        db_session,
        user,
        event="security stamp rotation",
    )
