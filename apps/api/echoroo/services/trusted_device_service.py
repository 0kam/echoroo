"""Trusted-device registration and management service."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal
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

logger = logging.getLogger(__name__)

_ACTIVE_DEVICE_CAP = 5
_RAW_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")

#: spec/011 §NFR-011-005 / FR-011-402 / T020 — canonical platform-scope
#: audit-action string for a bulk trusted-device revocation
#: (:meth:`TrustedDeviceService.revoke_all_for_user`). Emitted when a
#: sensitive account change wipes every trusted device for a user
#: (admin password reset / self-reset / email change / admin 2FA
#: disable per FR-011-402 / R10). Declaring the constant here (the
#: service that owns the revoke-all primitive) is the foundational
#: T020 step; the email->audit emit that consumes it lands with the
#: US7 ``services/email.py`` rewrite (T610-T617). The string is
#: banner-eligible (see
#: :data:`echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS`).
AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL: Final[str] = (
    "auth.trusted_device.revoke_all"
)

#: spec/011 §FR-011-402 / T630 — allowlist of reason codes accepted by
#: :meth:`TrustedDeviceService.revoke_all_for_user`. Every call-site MUST
#: pass one of these; an unknown reason raises ``ValueError`` so a typo
#: cannot silently emit an un-attributed revoke-all audit row.
#:
#: ``password_change`` is included so the shipped self-service /legacy
#: change-password flows (``services.self_password_change`` +
#: ``services.user.UserService.change_password``) keep working after
#: their reason strings were remapped from the historical
#: ``"password_changed"`` to the canonical ``"password_change"``.
REVOKE_ALL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "password_reset",
        "password_reset_self",
        "password_change",
        "email_change",
        "2fa_disable",
        "user_self_revoke",
        "user_deleted",
    }
)
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
        reason: str,
        actor_user_id: UUID | None = None,
    ) -> int:
        """Revoke every active trusted device for ``user`` and audit it.

        spec/011 §FR-011-402 / T630. The revoke itself runs on the
        caller's session (so it commits atomically with the surrounding
        state change), then a SINGLE ``auth.trusted_device.revoke_all``
        audit row is written in a FRESH session and committed
        independently — the audit writer issues ``SET TRANSACTION
        ISOLATION LEVEL SERIALIZABLE`` which the caller's already-used
        connection cannot satisfy (mirrors
        :func:`echoroo.services.admin_password_reset._write_audit_row`).

        The audit ``detail`` carries ``target_user_id`` so the row
        surfaces as an in-app banner to the affected user even when the
        actor is an operator (admin reset / admin 2FA disable). The emit
        is IDEMPOTENT in the sense that exactly one row is written per
        call — including when ``revoked_count == 0`` (no active devices)
        — so the banner / activity history records every revoke-all
        event regardless of how many rows the repository flipped.

        Args:
            user: The user whose trusted devices are being revoked
                (the banner target).
            reason: One of :data:`REVOKE_ALL_REASONS`. An unknown reason
                raises ``ValueError`` so a typo cannot emit an
                un-attributed audit row.
            actor_user_id: The actor performing the revoke. Defaults to
                ``user.id`` (self-revoke); operator-driven call-sites
                (admin password reset, admin 2FA disable) pass the
                operator's id.

        Returns:
            The number of trusted-device rows the repository flipped to
            revoked (0 when none were active).

        Raises:
            ValueError: ``reason`` is not in :data:`REVOKE_ALL_REASONS`.
        """
        if reason not in REVOKE_ALL_REASONS:
            raise ValueError(
                f"unknown revoke_all_for_user reason {reason!r}; "
                f"expected one of {sorted(REVOKE_ALL_REASONS)}"
            )
        effective_actor = actor_user_id if actor_user_id is not None else user.id
        revoked_count = await self.repository.revoke_all_for_user(user_id=user.id)
        await self._emit_revoke_all_audit(
            target_user_id=user.id,
            actor_user_id=effective_actor,
            reason=reason,
            revoked_count=revoked_count,
        )
        return revoked_count

    async def _emit_revoke_all_audit(
        self,
        *,
        target_user_id: UUID,
        actor_user_id: UUID,
        reason: str,
        revoked_count: int,
    ) -> None:
        """Write the single revoke-all audit row in a fresh session.

        Soft-alert on failure (FR-088): the trusted-device revocation has
        already happened on the caller's session, so a missing audit row
        must not bubble up as a hard error. We log a warning and continue.
        The fresh ``AsyncSessionLocal`` is required because the audit
        writer's SERIALIZABLE upgrade is rejected on a connection that has
        already run SQL (the caller's session ran the revoke UPDATE).
        """
        from echoroo.core.database import AsyncSessionLocal  # noqa: PLC0415
        from echoroo.services.audit_service import (  # noqa: PLC0415
            AuditLogService,
        )

        detail = {
            "user_id": str(target_user_id),
            "target_user_id": str(target_user_id),
            "revoked_count": revoked_count,
            "reason": reason,
        }
        try:
            async with AsyncSessionLocal() as audit_session:
                try:
                    await AuditLogService(audit_session).write_platform_event(
                        actor_user_id=actor_user_id,
                        action=AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
                        request_id="",
                        ip="",
                        user_agent="",
                        detail=detail,
                    )
                    await audit_session.commit()
                except Exception:
                    await audit_session.rollback()
                    raise
        except Exception as exc:  # noqa: BLE001 — soft alert
            logger.warning(
                "%s audit write failed (FR-088 soft alert): target=%s "
                "reason=%s error=%r",
                AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL,
                target_user_id,
                reason,
                exc,
            )

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
