"""System settings repository for data access.

Phase 13 P1 (T803a): updated to use native JSONB values. The legacy
``value_type`` / ``description`` arguments were removed; callers should
pass native Python objects (str, int, float, bool, dict, list) directly
and the database will round-trip them via JSONB.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.system import SystemSetting


class SystemSettingRepository:
    """Repository for SystemSetting data access operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: Async database session
        """
        self.db = db

    async def get_setting(self, key: str) -> SystemSetting | None:
        """Get a system setting by key.

        Args:
            key: Setting key to retrieve

        Returns:
            SystemSetting if found, None otherwise
        """
        result = await self.db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        return result.scalar_one_or_none()

    async def get_value(self, key: str, default: Any = None) -> Any:
        """Get the JSONB value for a setting key.

        Args:
            key: Setting key to retrieve
            default: Value to return if the key is not present

        Returns:
            The native Python object stored in the JSONB column, or
            ``default`` if the row does not exist.
        """
        setting = await self.get_setting(key)
        if setting is None:
            return default
        return setting.value

    async def set_setting(
        self,
        key: str,
        value: Any,
        updated_by_id: UUID,
    ) -> SystemSetting:
        """Create or update a system setting.

        Phase 13 P1 R2 致命 #1: ``updated_by_id`` is now NOT NULL and must
        reference a row in ``superusers.id`` (the FK target changed in the
        baseline schema; passing ``users.id`` violates the foreign-key
        constraint). Callers MUST resolve the active superuser id first.

        Args:
            key: Setting key
            value: Native Python value (str/int/float/bool/dict/list).
                Stored as JSONB.
            updated_by_id: Active superuser id (``superusers.id``)
                performing the update.

        Returns:
            Created or updated SystemSetting
        """
        setting = await self.get_setting(key)

        if setting:
            setting.value = value
            setting.updated_by_id = updated_by_id
        else:
            setting = SystemSetting(
                key=key,
                value=value,
                updated_by_id=updated_by_id,
            )
            self.db.add(setting)

        await self.db.flush()
        return setting

    async def is_setup_completed(self) -> bool:
        """Check if initial setup has been completed.

        Returns:
            True if setup_completed setting is true, False otherwise
        """
        value = await self.get_value("setup_completed", default=False)
        if isinstance(value, bool):
            return value
        # Tolerate legacy string-encoded values just in case.
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    async def mark_setup_completed(
        self, updated_by_id: UUID
    ) -> None:
        """Mark the initial setup as completed.

        Phase 13 P1 R2 致命 #1: ``updated_by_id`` is required (NOT NULL FK
        to ``superusers.id``). The setup wizard must have already promoted
        the bootstrap user to superuser before calling this — that
        ``superusers.id`` is the value to pass here.
        """

        await self.set_setting(
            key="setup_completed",
            value=True,
            updated_by_id=updated_by_id,
        )

    async def get_embedding_model(self) -> str:
        """Get the configured embedding model name.

        Reads the 'embedding_model' system setting, defaulting to 'perch'
        if the setting has not been explicitly configured by an admin.
        """
        value = await self.get_value("embedding_model")
        if isinstance(value, str) and value:
            return value
        return "perch"

    async def get_birdnet_settings(self) -> dict[str, object]:
        """Get BirdNET detection settings with defaults."""

        species_filter = await self.get_value("birdnet_species_filter")
        min_conf_raw = await self.get_value("birdnet_min_conf")

        species: str = species_filter if isinstance(species_filter, str) else "none"
        try:
            min_conf = (
                float(min_conf_raw)
                if min_conf_raw is not None
                else 0.25
            )
        except (TypeError, ValueError):
            min_conf = 0.25

        return {
            "species_filter": species,
            "min_conf": min_conf,
        }
