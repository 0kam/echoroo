"""Admin service for user and system management."""

from typing import Any, NoReturn
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
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


def _derive_value_type(value: Any) -> str:
    """Derive a UI-facing value-type label from a JSONB value.

    Used to keep the ``SystemSettingResponse.value_type`` field stable for
    legacy clients after Phase 13 dropped the ``setting_type`` enum column.
    """

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return "json"

_PHASE4_STUB_DETAIL = (
    "This endpoint is being rewritten in Phase 4 T150a-d / T155. "
    "Use the new auth flow when available."
)


def _raise_phase4_stub() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=_PHASE4_STUB_DETAIL,
    )


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
        del page, limit, search, is_active
        _raise_phase4_stub()

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
        del user_id, request, admin_id
        _raise_phase4_stub()

    async def get_system_settings(self) -> dict[str, SystemSettingResponse]:
        """Get all system settings.

        Returns:
            Dictionary mapping setting key to setting details. Values are
            returned as native Python objects (Phase 13 P1: JSONB-backed).
        """
        query = select(SystemSetting)
        result = await self.db.execute(query)
        settings = result.scalars().all()

        return {
            setting.key: SystemSettingResponse(
                key=setting.key,
                value=setting.value,
                value_type=_derive_value_type(setting.value),
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

        Phase 13 P1 (T803a): values are stored as native JSONB; the
        ``admin_id`` parameter must reference a row in ``superusers.id``
        (FK target changed in the schema). Caller layer (``api/v1/admin``)
        is responsible for resolving the current user to a superuser id.
        """

        if request.registration_mode is not None:
            await self._update_setting(
                "registration_mode", request.registration_mode, admin_id
            )
        if request.allow_registration is not None:
            await self._update_setting(
                "allow_registration", request.allow_registration, admin_id
            )
        if request.session_timeout_minutes is not None:
            await self._update_setting(
                "session_timeout_minutes",
                request.session_timeout_minutes,
                admin_id,
            )
        if request.birdnet_species_filter is not None:
            await self._update_setting(
                "birdnet_species_filter",
                request.birdnet_species_filter,
                admin_id,
            )
        if request.birdnet_min_conf is not None:
            await self._update_setting(
                "birdnet_min_conf", request.birdnet_min_conf, admin_id
            )

        await self.db.commit()

    async def _update_setting(
        self,
        key: str,
        value: Any,
        admin_id: UUID,
    ) -> None:
        """Update a single system setting (JSONB-backed)."""

        setting = await self.setting_repo.get_setting(key)
        if setting:
            setting.value = value
            setting.updated_by_id = admin_id
        else:
            setting = SystemSetting(
                key=key,
                value=value,
                updated_by_id=admin_id,
            )
            self.db.add(setting)

        await self.db.flush()
