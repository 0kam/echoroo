"""Repository helpers for trusted-device persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update

from echoroo.models.trusted_device import TrustedDevice
from echoroo.repositories.base import BaseRepository


class TrustedDeviceRepository(BaseRepository[TrustedDevice]):
    """Small query wrapper around ``trusted_devices``."""

    model = TrustedDevice

    async def add(self, device: TrustedDevice) -> TrustedDevice:
        self.db.add(device)
        await self.db.flush()
        return device

    async def get_by_secret_hash(
        self,
        *,
        device_secret_hash: str,
    ) -> TrustedDevice | None:
        row = await self.db.scalars(
            select(TrustedDevice)
            .where(TrustedDevice.device_secret_hash == device_secret_hash)
            .order_by(
                TrustedDevice.revoked_at.is_(None).desc(),
                TrustedDevice.created_at.desc(),
                TrustedDevice.id.desc(),
            )
            .limit(1)
        )
        return row.first()

    async def list_active_for_user(
        self,
        *,
        user_id: UUID,
        now: datetime | None = None,
    ) -> list[TrustedDevice]:
        effective_now = now or datetime.now(UTC)
        rows = await self.db.scalars(
            select(TrustedDevice)
            .where(
                TrustedDevice.user_id == user_id,
                TrustedDevice.revoked_at.is_(None),
                TrustedDevice.expires_at > effective_now,
            )
            .order_by(TrustedDevice.created_at, TrustedDevice.id)
        )
        return list(rows)

    async def revoke_device(
        self,
        *,
        user_id: UUID,
        device_id: UUID,
        now: datetime | None = None,
    ) -> bool:
        effective_now = now or datetime.now(UTC)
        result = await self.db.execute(
            update(TrustedDevice)
            .where(
                TrustedDevice.id == device_id,
                TrustedDevice.user_id == user_id,
                TrustedDevice.revoked_at.is_(None),
            )
            .values(revoked_at=effective_now)
        )
        return bool(result.rowcount)

    async def revoke_all_for_user(
        self,
        *,
        user_id: UUID,
        now: datetime | None = None,
    ) -> int:
        effective_now = now or datetime.now(UTC)
        result = await self.db.execute(
            update(TrustedDevice)
            .where(
                TrustedDevice.user_id == user_id,
                TrustedDevice.revoked_at.is_(None),
            )
            .values(revoked_at=effective_now)
        )
        return int(result.rowcount or 0)
