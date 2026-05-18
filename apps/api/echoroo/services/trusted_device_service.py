"""Trusted-device registration and management service."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from echoroo.core.settings import get_settings
from echoroo.models.superuser import Superuser
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.user import User
from echoroo.repositories.trusted_device import TrustedDeviceRepository
from echoroo.services.account_security_tokens import (
    generate_account_security_token,
    hash_account_security_token,
)

_ACTIVE_DEVICE_CAP = 5
_RAW_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
TrustedDeviceRejectReason = Literal[
    "missing",
    "malformed",
    "not_found",
    "user_mismatch",
    "revoked",
    "expired",
    "security_stamp_mismatch",
    "recent_password_failure",
    "privileged_user",
]


@dataclass(frozen=True)
class IssuedTrustedDevice:
    """A persisted trusted-device row plus its one-time raw cookie secret."""

    device: TrustedDevice
    raw_secret: str


@dataclass(frozen=True)
class TrustedDeviceEvaluation:
    """Result of evaluating a trusted-device cookie for login bypass."""

    accepted: bool
    device: TrustedDevice | None = None
    reject_reason: TrustedDeviceRejectReason | None = None


class TrustedDeviceService:
    """Issue, list, and revoke trusted devices for first-party auth."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TrustedDeviceRepository(session)

    async def issue_device(
        self,
        *,
        user: User,
        label: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedTrustedDevice:
        now = datetime.now(UTC)
        raw_secret = generate_account_security_token()
        device = TrustedDevice(
            user_id=user.id,
            device_secret_hash=hash_account_security_token(raw_secret),
            security_stamp=user.security_stamp,
            label=_normalize_label(label),
            created_at=now,
            expires_at=now
            + timedelta(seconds=get_settings().TRUSTED_DEVICE_COOKIE_TTL_SECONDS),
            created_ip_hash=_optional_hash(ip),
            created_user_agent_hash=_optional_hash(user_agent),
            last_ip_hash=None,
            last_user_agent_hash=None,
            last_used_at=None,
            revoked_at=None,
        )
        await self.repository.add(device)
        await self._enforce_active_cap(user_id=user.id, now=now)
        return IssuedTrustedDevice(device=device, raw_secret=raw_secret)

    async def list_active_devices(self, *, user: User) -> list[TrustedDevice]:
        return await self.repository.list_active_for_user(user_id=user.id)

    async def revoke_device(self, *, user: User, device_id: UUID) -> bool:
        return await self.repository.revoke_device(user_id=user.id, device_id=device_id)

    async def revoke_all_for_user(
        self,
        *,
        user: User,
        reason: str | None = None,
    ) -> int:
        del reason  # Reason is audit context; trusted_devices persists no raw event data.
        return await self.repository.revoke_all_for_user(user_id=user.id)

    async def evaluate_login_bypass(
        self,
        *,
        user: User,
        raw_secret: str | None,
        recent_password_failure: bool,
        ip: str | None = None,
        user_agent: str | None = None,
        now: datetime | None = None,
    ) -> TrustedDeviceEvaluation:
        effective_now = now or datetime.now(UTC)
        if raw_secret is None or raw_secret == "":
            return TrustedDeviceEvaluation(accepted=False, reject_reason="missing")
        if not _RAW_SECRET_RE.fullmatch(raw_secret):
            return TrustedDeviceEvaluation(accepted=False, reject_reason="malformed")
        if recent_password_failure:
            return TrustedDeviceEvaluation(
                accepted=False,
                reject_reason="recent_password_failure",
            )
        if await self._is_privileged_user(user):
            return TrustedDeviceEvaluation(
                accepted=False,
                reject_reason="privileged_user",
            )

        device = await self.repository.get_by_secret_hash(
            device_secret_hash=hash_account_security_token(raw_secret)
        )
        if device is None:
            return TrustedDeviceEvaluation(accepted=False, reject_reason="not_found")
        if device.user_id != user.id:
            return TrustedDeviceEvaluation(
                accepted=False,
                device=device,
                reject_reason="user_mismatch",
            )
        if device.revoked_at is not None:
            return TrustedDeviceEvaluation(
                accepted=False,
                device=device,
                reject_reason="revoked",
            )
        if device.expires_at <= effective_now:
            return TrustedDeviceEvaluation(
                accepted=False,
                device=device,
                reject_reason="expired",
            )
        if device.security_stamp != user.security_stamp:
            return TrustedDeviceEvaluation(
                accepted=False,
                device=device,
                reject_reason="security_stamp_mismatch",
            )

        device.last_used_at = effective_now
        device.last_ip_hash = _optional_hash(ip)
        device.last_user_agent_hash = _optional_hash(user_agent)
        self.session.add(device)
        await self.session.flush()
        return TrustedDeviceEvaluation(accepted=True, device=device)

    async def _is_privileged_user(self, user: User) -> bool:
        if bool(getattr(user, "is_superuser", False)):
            return True
        result = await self.session.execute(
            sa.select(Superuser.id)
            .where(Superuser.user_id == user.id)
            .where(Superuser.revoked_at.is_(None))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _enforce_active_cap(self, *, user_id: UUID, now: datetime) -> None:
        active = await self.repository.list_active_for_user(user_id=user_id, now=now)
        overflow = len(active) - _ACTIVE_DEVICE_CAP
        if overflow <= 0:
            return
        for device in active[:overflow]:
            device.revoked_at = now
            self.session.add(device)
        await self.session.flush()


@event.listens_for(Session, "before_flush")
def _revoke_devices_on_security_stamp_rotation(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    """Revoke trusted devices when a loaded user's security stamp changes."""
    now = datetime.now(UTC)
    for obj in list(session.dirty):
        if not isinstance(obj, User) or obj.id is None:
            continue
        state = sa.inspect(obj)
        if not state.persistent:
            continue
        if not state.attrs.security_stamp.history.has_changes():
            continue
        session.execute(
            sa.update(TrustedDevice)
            .where(
                TrustedDevice.user_id == obj.id,
                TrustedDevice.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )


def _normalize_label(label: str | None) -> str | None:
    if label is None:
        return None
    normalized = label.strip()
    if not normalized:
        return None
    return normalized[:100]


def _optional_hash(value: str | None) -> str | None:
    if not value:
        return None
    return hash_account_security_token(value)
