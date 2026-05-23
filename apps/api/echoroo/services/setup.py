"""Setup service for initial system configuration."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import pyotp
import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User
from echoroo.repositories.system import SystemSettingRepository
from echoroo.schemas.setup import (
    SetupCompleteResponse,
    SetupInitializeRequest,
    SetupStatusResponse,
    UserResponse,
)
from echoroo.services.superuser_service import (
    SuperuserActionOutcome,
    SuperuserServiceError,
    add_superuser,
    trigger_post_commit_audit,
)
from echoroo.services.two_factor_service import (
    ISSUER_NAME,
    TOTP_SECRET_LENGTH,
    _current_dek_version,
    _encrypt_totp_secret,
    _security_stamp,
)

_SETUP_ALREADY_DONE_DETAIL: Final[str] = (
    "Setup already completed or users already exist"
)

# Stable advisory-lock key for the first-run setup critical section.
_SETUP_INITIALIZE_LOCK_KEY: Final[int] = (
    int.from_bytes(hashlib.sha256(b"setup_initialize").digest()[:8], "big")
    & 0x7FFFFFFFFFFFFFFF
)
_AUDIT_CHAIN_UNAVAILABLE_DETAIL: Final[str] = (
    "Audit chain unavailable; setup not finalized"
)


def _setup_forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=_SETUP_ALREADY_DONE_DETAIL,
    )


def _audit_chain_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=_AUDIT_CHAIN_UNAVAILABLE_DETAIL,
    )


def _generate_bootstrap_token() -> str:
    from echoroo.scripts.init_superuser import _generate_bootstrap_token as helper

    return helper()


def _bootstrap_token_ttl() -> timedelta:
    from echoroo.scripts.init_superuser import BOOTSTRAP_TOKEN_TTL

    return BOOTSTRAP_TOKEN_TTL


async def _persist_bootstrap_token(
    session: AsyncSession,
    *,
    superuser_id: UUID,
    token: str,
    expires_at: datetime,
) -> None:
    from echoroo.scripts.init_superuser import _persist_bootstrap_token as helper

    await helper(
        session,
        superuser_id=superuser_id,
        token=token,
        expires_at=expires_at,
    )


async def _write_bootstrap_audit(
    *,
    actor_user_id: UUID,
    request_id: str,
    ip: str,
    user_agent: str,
    detail: dict[str, Any],
) -> None:
    from echoroo.core.database import AsyncSessionLocal
    from echoroo.scripts.init_superuser import AUDIT_ACTION_BOOTSTRAP
    from echoroo.services.audit_service import AuditLogService

    async with AsyncSessionLocal() as audit_session:
        try:
            await AuditLogService(audit_session).write_platform_event(
                actor_user_id=actor_user_id,
                action=AUDIT_ACTION_BOOTSTRAP,
                request_id=request_id or f"bootstrap-{uuid4()}",
                ip=ip or "127.0.0.1",
                user_agent=user_agent or "echoroo.api.setup",
                detail=detail,
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            raise


class SetupService:
    """Service for managing initial system setup."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize setup service.

        Args:
            session: Async database session
        """
        self.session = session
        self.system_repo = SystemSettingRepository(session)

    async def get_setup_status(self) -> SetupStatusResponse:
        """Get current setup status.

        Checks if setup is required (no users exist) and if setup has been completed.

        Returns:
            SetupStatusResponse with current status
        """
        # Check if setup has been marked as completed
        setup_completed = await self.system_repo.is_setup_completed()

        # Check if any users exist
        result = await self.session.execute(select(User).limit(1))
        has_users = result.scalar_one_or_none() is not None

        # Setup is required if no users exist and setup not completed
        setup_required = not has_users and not setup_completed

        return SetupStatusResponse(
            setup_required=setup_required,
            setup_completed=setup_completed,
        )

    async def initialize_setup(
        self,
        request: SetupInitializeRequest,
        *,
        request_id: str = "",
        ip: str = "",
        user_agent: str = "",
    ) -> SetupCompleteResponse:
        """Initialize system setup by creating the first admin user.

        Creates a bootstrap superuser account, marks setup as completed,
        and returns the one-time TOTP/WebAuthn bootstrap artifacts.

        Args:
            request: Setup initialization request with admin user details
            request_id: Request id for platform audit rows
            ip: Client IP address for platform audit rows
            user_agent: Client user agent for platform audit rows

        Returns:
            SetupCompleteResponse with the created user and bootstrap artifacts

        Raises:
            HTTPException: 403 if setup is already completed or users exist
        """
        setup_request: SetupInitializeRequest | None = request
        del request

        secret: str | None = None
        provisioning_uri: str | None = None
        bootstrap_token: str | None = None
        outcome: SuperuserActionOutcome | None = None
        should_rollback = False

        try:
            # Fast-fail without taking the global lock; the authoritative guard is
            # the same check repeated after pg_advisory_xact_lock serializes setup.
            await self._ensure_setup_allowed()
            assert setup_request is not None
            display_name = self._resolve_display_name(
                setup_request.display_name,
                str(setup_request.email),
            )

            should_rollback = True
            await self._acquire_initialize_lock()
            # Re-check under the advisory lock so concurrent initializes cannot
            # both observe an empty database and create competing genesis users.
            await self._ensure_setup_allowed()

            secret = pyotp.random_base32(length=TOTP_SECRET_LENGTH)
            provisioning_uri = pyotp.TOTP(secret).provisioning_uri(
                name=str(setup_request.email),
                issuer_name=ISSUER_NAME,
            )
            encrypted_secret = _encrypt_totp_secret(secret)
            encrypted_secret_dek_version = _current_dek_version()

            bootstrap_token = _generate_bootstrap_token()
            bootstrap_token_expires = datetime.now(UTC) + _bootstrap_token_ttl()

            # spec/011 §FR-011-002 / FR-011-009 — the bootstrap superuser
            # row no longer sets ``email_verified_at`` because the
            # column is dropped in migration 0022. The setup wizard
            # path is the canonical "no email infrastructure" entry
            # point: requiring a verification timestamp on the very
            # first user contradicts spec/011's zero-email goal.
            user_row = User(
                id=uuid4(),
                email=str(setup_request.email),
                password_hash=hash_password(setup_request.password),
                display_name=display_name,
                two_factor_enabled=True,
                two_factor_secret_encrypted=encrypted_secret,
                two_factor_secret_dek_version=encrypted_secret_dek_version,
                two_factor_backup_codes_hashed=None,
                security_stamp=_security_stamp(),
            )
            self.session.add(user_row)
            await self.session.flush()
            await self.session.refresh(user_row)

            try:
                outcome = await add_superuser(
                    self.session,
                    target_user_id=user_row.id,
                    requester_superuser_id=None,
                    actor_user_id=None,
                    request_id=request_id or f"bootstrap-{uuid4()}",
                    ip=ip or "unknown",
                    user_agent=user_agent or "",
                )
            except SuperuserServiceError as exc:
                raise _setup_forbidden() from exc

            if outcome.status != "direct" or outcome.superuser_id is None:
                raise _setup_forbidden()

            await _persist_bootstrap_token(
                self.session,
                superuser_id=outcome.superuser_id,
                token=bootstrap_token,
                expires_at=bootstrap_token_expires,
            )
            await self.system_repo.mark_setup_completed(outcome.superuser_id)

            user_response = UserResponse.model_validate(user_row)
            user_id = user_response.id
            user_email = user_response.email
            user_display_name = user_response.display_name

            try:
                await _write_bootstrap_audit(
                    actor_user_id=user_id,
                    request_id=outcome.request_id,
                    ip=outcome.ip,
                    user_agent=outcome.user_agent,
                    detail={
                        "user_id": str(user_id),
                        "superuser_id": str(outcome.superuser_id),
                        "email": user_email,
                        "display_name": user_display_name,
                        "bootstrap_token_expires_at": (
                            bootstrap_token_expires.isoformat()
                        ),
                    },
                )
            except Exception as exc:
                raise _audit_chain_unavailable() from exc

            await self.session.commit()
            should_rollback = False
            await trigger_post_commit_audit(outcome)

            return SetupCompleteResponse(
                user=user_response,
                totp_secret_base32=secret,
                totp_provisioning_uri=provisioning_uri,
                bootstrap_token=bootstrap_token,
                bootstrap_token_expires_at=bootstrap_token_expires,
                webauthn_registration_url=(
                    f"/admin/webauthn/register?token={bootstrap_token}"
                ),
            )
        except Exception:
            if should_rollback:
                await self.session.rollback()
            raise
        finally:
            setup_request = None
            secret = None
            provisioning_uri = None
            bootstrap_token = None
            del setup_request
            del secret
            del provisioning_uri
            del bootstrap_token

    async def _acquire_initialize_lock(self) -> None:
        await self.session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _SETUP_INITIALIZE_LOCK_KEY},
        )

    async def _ensure_setup_allowed(self) -> None:
        setup_completed = await self.system_repo.is_setup_completed()
        result = await self.session.execute(select(User.id).limit(1))
        has_users = result.scalar_one_or_none() is not None
        if setup_completed or has_users:
            raise _setup_forbidden()

    @staticmethod
    def _resolve_display_name(display_name: str | None, email: str) -> str:
        if display_name is not None and display_name.strip():
            return display_name.strip()
        return email.split("@", 1)[0]
