"""System settings repository for data access."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.system import SystemSetting


class SystemSettingRepository:
    """Repository for SystemSetting data access operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            session: Async database session
        """
        self.session = session

    async def get_setting(self, key: str) -> SystemSetting | None:
        """Get a system setting by key.

        Args:
            key: Setting key to retrieve

        Returns:
            SystemSetting if found, None otherwise
        """
        result = await self.session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        return result.scalar_one_or_none()

    async def set_setting(
        self, key: str, value: str, value_type: str, description: str | None = None
    ) -> SystemSetting:
        """Create or update a system setting.

        Args:
            key: Setting key
            value: Setting value (as string)
            value_type: Type of the value ('string', 'number', 'boolean', 'json')
            description: Optional description

        Returns:
            Created or updated SystemSetting
        """
        setting = await self.get_setting(key)

        if setting:
            # Update existing
            setting.value = value
            setting.value_type = value_type
            if description is not None:
                setting.description = description
        else:
            # Create new
            setting = SystemSetting(
                key=key,
                value=value,
                value_type=value_type,
                description=description,
            )
            self.session.add(setting)

        await self.session.flush()
        return setting

    async def is_setup_completed(self) -> bool:
        """Check if initial setup has been completed.

        Returns:
            True if setup_completed setting is true, False otherwise
        """
        setting = await self.get_setting("setup_completed")
        if not setting:
            return False
        # Value is stored as string "true" or "false"
        return setting.value.lower() == "true"

    async def mark_setup_completed(self) -> None:
        """Mark the initial setup as completed.

        Sets the setup_completed setting to true.
        """
        await self.set_setting(
            key="setup_completed",
            value="true",
            value_type="boolean",
            description="Whether initial setup has been completed",
        )
