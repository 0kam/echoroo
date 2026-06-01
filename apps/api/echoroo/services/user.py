"""User profile service with business logic."""

import logging
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password, verify_password
from echoroo.models.user import User
from echoroo.repositories.user import UserRepository
from echoroo.schemas.user import PasswordChangeRequest, UserUpdateRequest
from echoroo.services.email import send_email_change_notification
from echoroo.services.trusted_device_service import TrustedDeviceService

#: spec/011 §FR-011-305 — duration of the cool-off window opened after a
#: successful self-service email change. During this window the user
#: cannot change their email again (or change their password via the
#: self-service path); the operator recovery path bypasses it (OQ10).
EMAIL_CHANGE_COOLDOWN: Final[timedelta] = timedelta(hours=24)

#: spec/011 §NFR-011-005 / FR-011-305 / T020 — canonical platform-scope
#: audit-action string for a user email change. Emitted (per the table
#: in data-model.md) by the email-change flow which also triggers
#: session invalidation + trusted-device revoke + cool-off. Declaring
#: the constant here (the service that owns ``change_email``) is the
#: foundational T020 step; the email->audit emit that consumes it lands
#: with the US7 ``services/email.py`` rewrite (T610-T617). The detail
#: carries old/new email *hashes* only — never the plaintext address
#: (NFR-011-005 / A-13). The string is banner-eligible (see
#: :data:`echoroo.services.user_banner.BANNER_ELIGIBLE_ACTIONS`).
AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED: Final[str] = (
    "platform.user.email_changed"
)


def _normalize_email_for_change(email: str) -> str:
    """Normalize an email address for storage.

    spec/011 Step 10 (T123) inlined the legacy
    ``EmailVerificationService.normalize_email_for_verification`` helper
    so removing the email-verification subsystem does not regress the
    case/Unicode handling of the ``UserService.change_email`` flow
    (Phase 9 US7 will eventually replace this with the cross-spec
    ``services.invitation_service.canonicalize_email`` helper once
    change-email is wired end-to-end).
    """
    normalized = unicodedata.normalize("NFKC", email).strip()
    try:
        validated = validate_email(
            normalized,
            allow_smtputf8=True,
            check_deliverability=False,
        )
    except EmailNotValidError:
        return normalized.lower()
    return validated.normalized.lower()

logger = logging.getLogger(__name__)


class UserService:
    """User service for profile management."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize user service.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.user_repo = UserRepository(db)

        # Import here to avoid circular imports between user and auth services
        from echoroo.services.auth import AuthService  # noqa: PLC0415

        self._auth_service = AuthService(db)

    async def get_current_user(self, user_id: UUID) -> User:
        """Get current user by ID.

        Args:
            user_id: User's UUID

        Returns:
            User instance

        Raises:
            HTTPException: If user not found
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        return user

    async def update_user(self, user_id: UUID, request: UserUpdateRequest) -> User:
        """Update user profile.

        Args:
            user_id: User's UUID
            request: Profile update data

        Returns:
            Updated user instance

        Raises:
            HTTPException: If user not found
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Update fields if provided
        if request.display_name is not None:
            user.display_name = request.display_name

        await self.user_repo.update(user)
        await self.db.commit()

        return user

    async def change_password(
        self, user_id: UUID, request: PasswordChangeRequest
    ) -> None:
        """Change user password.

        Args:
            user_id: User's UUID
            request: Password change data

        Raises:
            HTTPException: If user not found, current password invalid, or new password weak
        """
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Verify current password
        if not verify_password(request.current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid current password",
            )

        # Check if new password is same as current
        if verify_password(request.new_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password",
            )

        # Update password
        user.password_hash = hash_password(request.new_password)
        await TrustedDeviceService(self.db).revoke_all_for_user(
            user=user,
            reason="password_change",
        )
        await self.user_repo.update(user)
        await self.db.commit()

        # Revoke all existing tokens so that other active sessions are invalidated
        logger.info("Password changed for user %s; revoking all tokens", user_id)
        await self._auth_service.revoke_user_tokens(user_id)

    async def change_email(
        self,
        user_id: UUID,
        new_email: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        request_id: str = "",
        now: datetime | None = None,
    ) -> User:
        """Change account email and reset email-trust dependent security state.

        spec/011 §FR-011-305 / US7 (T620/T621). On a successful change
        this:

        1. Rejects the change with HTTP 409 (``email_change_cooldown_active``)
           when the user is still inside a prior 24-hour cool-off window.
        2. Updates ``users.email``.
        3. Rotates ``users.security_stamp`` and flushes — the
           :func:`echoroo.services.trusted_device_service._revoke_devices_on_security_stamp_rotation`
           ``before_flush`` listener fires on the flush and revokes every
           active trusted device; the stamp rotation also invalidates
           every outstanding session token (FR-055).
        4. Explicitly calls ``revoke_all_for_user(reason="email_change")``
           as defence-in-depth (and to emit the single banner-eligible
           ``auth.trusted_device.revoke_all`` audit row).
        5. Emits the ``platform.user.email_changed`` banner via
           :func:`echoroo.services.email.send_email_change_notification`.
        6. Opens a fresh 24-hour cool-off window
           (``email_change_cooldown_until``).
        """
        tick = now or datetime.now(UTC)
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # ---- Cool-off gate (FR-011-305 / T621) --------------------------
        #
        # The cool-off applies to the user's OWN self-service email /
        # password change requests. The operator recovery path
        # (``admin_password_reset.reset_password``) does NOT read this
        # column and therefore bypasses the cool-off (OQ10).
        cooldown_until = user.email_change_cooldown_until
        if cooldown_until is not None:
            if cooldown_until.tzinfo is None:
                cooldown_until = cooldown_until.replace(tzinfo=UTC)
            if tick < cooldown_until:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error_code": "email_change_cooldown_active",
                        "message": (
                            "Email change is in a 24-hour cool-off; please "
                            f"wait until {cooldown_until.isoformat()}."
                        ),
                    },
                )

        normalized_email = _normalize_email_for_change(new_email)
        existing = await self.user_repo.get_by_email(normalized_email)
        if existing is not None and existing.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )

        previous_email = user.email
        user.email = normalized_email
        # spec/011 §FR-011-002 / Step 10 (T123) — ``email_verified_at``
        # was removed alongside the email-verification subsystem.

        # ---- Session invalidation (FR-055 / FR-011-305) -----------------
        #
        # Rotate the security stamp and FLUSH it BEFORE the explicit
        # ``revoke_all_for_user`` so the ``before_flush`` listener revokes
        # trusted devices first; the explicit call below is then
        # defence-in-depth (mirrors ``admin_password_reset`` ordering).
        user.security_stamp = secrets.token_hex(32)
        self.db.add(user)
        await self.db.flush()

        await TrustedDeviceService(self.db).revoke_all_for_user(
            user=user,
            reason="email_change",
        )

        # ---- Open the 24-hour cool-off window (FR-011-305) --------------
        user.email_change_cooldown_until = tick + EMAIL_CHANGE_COOLDOWN

        await self.user_repo.update(user)
        await self.db.commit()

        logger.info(
            "Email changed for user %s; trusted devices revoked, cool-off "
            "until %s",
            user_id,
            user.email_change_cooldown_until.isoformat(),
        )

        # ---- Emit the email-change banner (FR-011-301 / FR-011-305) -----
        #
        # ``send_email_change_notification`` writes the banner-eligible
        # ``platform.user.email_changed`` audit row in its own fresh
        # session (soft-alert on failure). ``ip`` / ``user_agent`` are
        # not persisted into the banner detail (A-13); they are accepted
        # for signature parity with the request envelope.
        del ip
        del user_agent
        if previous_email:
            await send_email_change_notification(
                previous_email,
                user_id=user.id,
                request_id=request_id,
            )
        return user
