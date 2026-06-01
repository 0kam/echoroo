"""Account trusted-device management endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.user import User
from echoroo.schemas.web_v1.trusted_device import (
    TrustedDeviceListResponse,
    TrustedDeviceResponse,
)
from echoroo.services.account_security_tokens import hash_account_security_token
from echoroo.services.trusted_device_service import TrustedDeviceService

router = APIRouter(prefix="/trusted-devices")


def _require_authenticated(current_user: User | None) -> User:
    if current_user is None or getattr(current_user, "deleted_at", None) is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user


def _is_current_device(request: Request, device: TrustedDevice) -> bool:
    raw_secret = request.cookies.get(get_settings().TRUSTED_DEVICE_COOKIE_NAME)
    if not raw_secret:
        return False
    return hash_account_security_token(raw_secret) == device.device_secret_hash


def _render_device(request: Request, device: TrustedDevice) -> TrustedDeviceResponse:
    return TrustedDeviceResponse(
        id=device.id,
        label=device.label,
        current_device=_is_current_device(request, device),
        created_at=device.created_at,
        last_used_at=device.last_used_at,
        expires_at=device.expires_at,
    )


@router.get(
    "",
    response_model=TrustedDeviceListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_account_trusted_devices(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TrustedDeviceListResponse:
    user = _require_authenticated(current_user)
    devices = await TrustedDeviceService(db).list_active_devices(user=user)
    return TrustedDeviceListResponse(
        devices=[_render_device(request, device) for device in devices]
    )


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_account_trusted_device(
    device_id: UUID,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> Response:
    user = _require_authenticated(current_user)
    await TrustedDeviceService(db).revoke_device(user=user, device_id=device_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/revoke-all",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_all_account_trusted_devices(
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> Response:
    user = _require_authenticated(current_user)
    # spec/011 T630 (OQ11): the self-service revoke-all now passes an
    # explicit reason from the allowlist so the audit row is attributed
    # (a missing/``None`` reason now raises ``ValueError``).
    await TrustedDeviceService(db).revoke_all_for_user(
        user=user,
        reason="user_self_revoke",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
