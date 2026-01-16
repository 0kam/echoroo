"""Authentication service with business logic."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token, create_refresh_token, decode_token
from echoroo.core.security import hash_password, verify_password
from echoroo.core.settings import get_settings
from echoroo.models.user import User
from echoroo.repositories.user import UserRepository
from echoroo.schemas.auth import (
    LoginRequest,
    PasswordResetConfirm,
    TokenResponse,
    UserRegisterRequest,
)
from echoroo.services.captcha import verify_turnstile
from echoroo.services.email import send_password_reset_email, send_verification_email

settings = get_settings()


class AuthService:
    """Authentication service for user registration, login, and token management."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize auth service.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    async def register(self, request: UserRegisterRequest, client_ip: str) -> User:
        """Register a new user.

        Args:
            request: User registration data
            client_ip: Client IP address for CAPTCHA verification

        Returns:
            Created user instance

        Raises:
            HTTPException: If email already exists, CAPTCHA invalid, or validation fails
        """
        # Check if email already exists
        existing_user = await self.user_repo.get_by_email(request.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Verify CAPTCHA if provided
        if request.captcha_token:
            captcha_valid = await verify_turnstile(request.captcha_token, client_ip)
            if not captcha_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid CAPTCHA",
                )

        # Generate email verification token
        verification_token = secrets.token_urlsafe(32)
        verification_expires = datetime.now(UTC) + timedelta(hours=24)

        # Create user
        user = User(
            email=request.email,
            hashed_password=hash_password(request.password),
            display_name=request.display_name,
            is_verified=False,
            email_verification_token=verification_token,
            email_verification_expires_at=verification_expires,
        )

        user = await self.user_repo.create(user)
        await self.db.commit()

        # Send verification email (non-blocking)
        await send_verification_email(user.email, verification_token)

        return user

    async def login(
        self, request: LoginRequest, client_ip: str, user_agent: str | None = None
    ) -> tuple[TokenResponse, str]:
        """Authenticate user and generate tokens.

        Args:
            request: Login credentials
            client_ip: Client IP address
            user_agent: User agent string

        Returns:
            Tuple of (TokenResponse, refresh_token)

        Raises:
            HTTPException: If credentials invalid, account locked, or rate limited
        """
        # Check failed attempts for rate limiting
        failed_attempts = await self.user_repo.get_recent_failed_attempts(request.email)
        failed_attempts_ip = await self.user_repo.get_recent_failed_attempts_by_ip(client_ip)

        # Account lockout after too many failed attempts (check first before CAPTCHA)
        if failed_attempts >= 5:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Account temporarily locked due to too many failed attempts",
            )

        # Require CAPTCHA after threshold
        if failed_attempts >= 3 or failed_attempts_ip >= 3:
            if not request.captcha_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="CAPTCHA required after multiple failed attempts",
                )
            captcha_valid = await verify_turnstile(request.captcha_token, client_ip)
            if not captcha_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid CAPTCHA",
                )

        # Get user
        user = await self.user_repo.get_by_email(request.email)
        if not user or not verify_password(request.password, user.hashed_password):
            # Record failed attempt
            await self.user_repo.record_login_attempt(
                email=request.email,
                ip_address=client_ip,
                success=False,
                user_agent=user_agent,
            )
            await self.db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )

        # Check if account is active
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )

        # Check if email is verified (optional - can be enforced via settings)
        # if not user.is_verified:
        #     raise HTTPException(
        #         status_code=status.HTTP_403_FORBIDDEN,
        #         detail="Email not verified",
        #     )

        # Record successful login
        await self.user_repo.record_login_attempt(
            email=request.email,
            ip_address=client_ip,
            success=True,
            user_agent=user_agent,
            user_id=user.id,
        )

        # Update last login timestamp
        user.last_login_at = datetime.now(UTC)
        await self.user_repo.update(user)
        await self.db.commit()

        # Generate tokens
        token_data = {"sub": str(user.id), "email": user.email}
        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        token_response = TokenResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

        return token_response, refresh_token

    async def logout(self, user_id: UUID) -> None:
        """Logout user (placeholder for token revocation).

        Args:
            user_id: User's UUID

        Note:
            In production, this would revoke refresh token families in Redis
        """
        # TODO: Implement token family revocation in Redis
        pass

    async def refresh_token(self, refresh_token: str) -> tuple[TokenResponse, str]:
        """Refresh access token using refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            Tuple of (new TokenResponse, new refresh_token)

        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            payload = decode_token(refresh_token)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            ) from e

        # Verify token type
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        # Get user
        user_id = UUID(payload.get("sub", ""))
        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )

        # Generate new tokens (token rotation)
        token_data = {"sub": str(user.id), "email": user.email}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data)

        token_response = TokenResponse(
            access_token=new_access_token,
            token_type="bearer",
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

        return token_response, new_refresh_token

    async def verify_email(self, token: str) -> User:
        """Verify user email with token.

        Args:
            token: Email verification token

        Returns:
            Verified user instance

        Raises:
            HTTPException: If token is invalid or expired
        """
        user = await self.user_repo.get_by_verification_token(token)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification token",
            )

        # Check token expiration
        if not user.email_verification_expires_at or datetime.now(
            UTC
        ) > user.email_verification_expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification token expired",
            )

        # Mark as verified
        user.is_verified = True
        user.email_verification_token = None
        user.email_verification_expires_at = None

        await self.user_repo.update(user)
        await self.db.commit()

        return user

    async def request_password_reset(self, email: str) -> None:
        """Request password reset (always returns success for security).

        Args:
            email: User's email address

        Note:
            Always returns success even if email doesn't exist (security best practice)
        """
        user = await self.user_repo.get_by_email(email)

        if user and user.is_active:
            # Generate reset token
            reset_token = secrets.token_urlsafe(32)
            reset_expires = datetime.now(UTC) + timedelta(hours=1)

            user.password_reset_token = reset_token
            user.password_reset_expires_at = reset_expires

            await self.user_repo.update(user)
            await self.db.commit()

            # Send reset email
            await send_password_reset_email(user.email, reset_token)

        # Always return success (don't leak email existence)

    async def confirm_password_reset(self, request: PasswordResetConfirm) -> None:
        """Reset password using token.

        Args:
            request: Password reset confirmation data

        Raises:
            HTTPException: If token is invalid or expired
        """
        user = await self.user_repo.get_by_reset_token(request.token)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset token",
            )

        # Check token expiration
        if not user.password_reset_expires_at or datetime.now(
            UTC
        ) > user.password_reset_expires_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset token expired",
            )

        # Update password
        user.hashed_password = hash_password(request.password)
        user.password_reset_token = None
        user.password_reset_expires_at = None

        await self.user_repo.update(user)
        await self.db.commit()

    async def get_current_user(self, token: str) -> User:
        """Get current user from access token.

        Args:
            token: JWT access token

        Returns:
            User instance

        Raises:
            HTTPException: If token is invalid or user not found
        """
        try:
            payload = decode_token(token)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

        # Verify token type
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get user
        user_id = UUID(payload.get("sub", ""))
        user = await self.user_repo.get_by_id(user_id)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )

        return user
