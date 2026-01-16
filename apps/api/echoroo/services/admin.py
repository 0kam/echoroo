"""Admin service for user and system management."""

import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.system import SystemSetting
from echoroo.models.user import User
from echoroo.repositories.system import SystemSettingRepository
from echoroo.repositories.user import UserRepository
from echoroo.schemas.admin import (
    AdminUserListResponse,
    AdminUserUpdateRequest,
    SystemSettingResponse,
    SystemSettingsUpdateRequest,
)
from echoroo.schemas.auth import UserResponse


class AdminService:
    """Service for administrative operations on users and system settings."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize admin service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.user_repo = UserRepository(db)
        self.setting_repo = SystemSettingRepository(db)

    async def list_users(
        self,
        page: int = 1,
        limit: int = 20,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> AdminUserListResponse:
        """List all users with optional filtering and pagination.

        Args:
            page: Page number (1-indexed)
            limit: Number of items per page
            search: Search term for email or display name
            is_active: Filter by active status

        Returns:
            Paginated user list with total count
        """
        # Build query
        query = select(User)

        # Apply filters
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    func.lower(User.email).like(func.lower(search_pattern)),
                    func.lower(User.display_name).like(func.lower(search_pattern)),
                )
            )

        if is_active is not None:
            query = query.where(User.is_active == is_active)

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * limit
        query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)

        # Execute query
        result = await self.db.execute(query)
        users = result.scalars().all()

        # Convert to response schemas
        items = [UserResponse.model_validate(user) for user in users]

        return AdminUserListResponse(
            items=items,
            total=total,
            page=page,
            limit=limit,
        )

    async def update_user(
        self,
        user_id: UUID,
        request: AdminUserUpdateRequest,
        admin_id: UUID,  # noqa: ARG002 - reserved for future audit logging
    ) -> User:
        """Update user status and permissions.

        Args:
            user_id: UUID of user to update
            request: Update request with fields to change
            admin_id: UUID of admin performing the update (reserved for audit logging)

        Returns:
            Updated user instance

        Raises:
            HTTPException: If user not found or trying to disable last superuser
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Check if trying to disable or demote the last superuser
        if (request.is_active is False and user.is_superuser) or (
            request.is_superuser is False and user.is_superuser
        ):
            # Count active superusers
            query = select(func.count()).select_from(User).where(User.is_superuser == True)  # noqa: E712
            if request.is_active is False:
                # If deactivating, count other active superusers
                query = query.where(User.is_active == True, User.id != user_id)  # noqa: E712
            elif request.is_superuser is False:
                # If demoting, count other superusers
                query = query.where(User.id != user_id)

            result = await self.db.execute(query)
            superuser_count = result.scalar_one()

            if superuser_count == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot disable or remove superuser role from the last superuser",
                )

        # Apply updates
        if request.is_active is not None:
            user.is_active = request.is_active

        if request.is_superuser is not None:
            user.is_superuser = request.is_superuser

        if request.is_verified is not None:
            user.is_verified = request.is_verified

        # Save changes
        await self.db.commit()
        await self.db.refresh(user)

        return user

    async def get_system_settings(self) -> dict[str, SystemSettingResponse]:
        """Get all system settings.

        Returns:
            Dictionary mapping setting key to setting details
        """
        query = select(SystemSetting)
        result = await self.db.execute(query)
        settings = result.scalars().all()

        return {
            setting.key: SystemSettingResponse(
                key=setting.key,
                value=self._parse_setting_value(setting.value, setting.value_type),
                value_type=setting.value_type,
                description=setting.description,
                updated_at=setting.updated_at,
            )
            for setting in settings
        }

    async def update_system_settings(
        self,
        request: SystemSettingsUpdateRequest,
        admin_id: UUID,
    ) -> None:
        """Update system settings.

        Args:
            request: Settings update request
            admin_id: UUID of admin performing the update
        """
        # Update each provided setting
        if request.registration_mode is not None:
            await self._update_setting(
                "registration_mode",
                request.registration_mode,
                "string",
                admin_id,
            )

        if request.allow_registration is not None:
            await self._update_setting(
                "allow_registration",
                "true" if request.allow_registration else "false",
                "boolean",
                admin_id,
            )

        if request.session_timeout_minutes is not None:
            await self._update_setting(
                "session_timeout_minutes",
                str(request.session_timeout_minutes),
                "number",
                admin_id,
            )

        await self.db.commit()

    async def _update_setting(
        self,
        key: str,
        value: str,
        value_type: str,
        admin_id: UUID,
    ) -> None:
        """Update a single system setting.

        Args:
            key: Setting key
            value: Setting value (as string)
            value_type: Type of the value
            admin_id: UUID of admin performing the update
        """
        setting = await self.setting_repo.get_setting(key)

        if setting:
            setting.value = value
            setting.value_type = value_type
            setting.updated_by_id = admin_id
        else:
            setting = SystemSetting(
                key=key,
                value=value,
                value_type=value_type,
                updated_by_id=admin_id,
            )
            self.db.add(setting)

        await self.db.flush()

    def _parse_setting_value(
        self, value: str, value_type: str
    ) -> str | int | bool | dict[str, object]:
        """Parse setting value based on its type.

        Args:
            value: String representation of the value
            value_type: Type of the value

        Returns:
            Parsed value in appropriate type
        """
        if value_type == "boolean":
            return value.lower() == "true"
        elif value_type == "number":
            # Try to parse as int, fallback to float if needed
            # But return as int since we don't use floats in settings
            try:
                return int(value)
            except ValueError:
                # This shouldn't happen with our current settings
                return int(float(value))
        elif value_type == "json":
            parsed: dict[str, object] = json.loads(value)
            return parsed
        else:  # string
            return value
