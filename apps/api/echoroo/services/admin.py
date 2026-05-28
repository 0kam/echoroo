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
    AdminUserListItem,
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
        is_active: bool | None = None,  # noqa: ARG002 — deprecated, spec/006 dropped the column
    ) -> AdminUserListResponse:
        """List all users with optional pagination + search.

        spec/011 PR 7: un-stubbed. spec/006 dropped ``users.is_active`` so
        the ``is_active`` parameter is accepted for API compatibility but
        silently ignored. Uses :meth:`UserRepository.list_users` with
        offset/limit translation.
        """
        del is_active  # accepted for compat, no longer filterable
        offset = (page - 1) * limit
        rows, total = await self.user_repo.list_users(
            offset=offset, limit=limit, search=search,
        )
        items = [
            AdminUserListItem(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                created_at=user.created_at,
                last_login_at=user.last_login_at,
                is_superuser=is_su,
            )
            for user, is_su in rows
        ]
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
        """Update a user profile.

        spec/011 PR 7: un-stubbed. Only ``display_name`` is applied;
        legacy ``is_active`` / ``is_superuser`` / ``is_verified`` fields
        are accepted in the request schema for client compatibility but
        silently ignored (spec/006 dropped those columns from ``users``).
        Raises 404 when the target user is missing or soft-deleted.
        """
        user = await self.user_repo.get_by_id(user_id)
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        if request.display_name is not None:
            user.display_name = request.display_name
        await self.user_repo.update(user)
        await self.db.commit()
        return user

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
