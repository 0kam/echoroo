"""User profile service with business logic."""

import logging
import unicodedata
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
            reason="password_changed",
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
    ) -> User:
        """Change account email and reset email-trust dependent security state."""
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
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
        # ``change_email`` no longer needs to clear a verification
        # timestamp; the change-email banner + cool-off invariants are
        # owned by the FR-011-305 cool-off enforcement (added in
        # migration 0021).
        await TrustedDeviceService(self.db).revoke_all_for_user(
            user=user,
            reason="email_changed",
        )
        # Parameters retained for signature parity with the production
        # FR-011-305 wire-up (Phase 9 US7); they currently land in the
        # ``send_email_change_notification`` banner stub below.
        del ip
        del user_agent
        await self.user_repo.update(user)
        await self.db.commit()

        logger.info(
            "Email changed for user %s; trusted devices revoked",
            user_id,
        )
        if previous_email:
            await send_email_change_notification(previous_email)
        return user
