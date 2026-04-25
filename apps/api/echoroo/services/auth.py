"""Authentication service with business logic."""

import logging
import time
from uuid import UUID

from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token, create_refresh_token, decode_token
from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.models.user import User
from echoroo.repositories.user import UserRepository
from echoroo.schemas.auth import (
    LoginRequest,
    PasswordResetConfirm,
    TokenResponse,
    UserRegisterRequest,
)

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthService:
    """Authentication service for user registration, login, and token management."""

    # Redis key prefix for revoked user tokens
    _REVOCATION_KEY_PREFIX = "revoked_user:"

    def __init__(self, db: AsyncSession) -> None:
        """Initialize auth service.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.user_repo = UserRepository(db)

    async def _get_redis(self) -> Redis | None:
        """Get Redis connection, returning None on failure.

        Returns:
            Redis client or None if connection fails
        """
        try:
            return await get_redis_connection()
        except Exception:
            logger.warning("Redis connection unavailable; token revocation checks skipped")
            return None

    async def revoke_user_tokens(self, user_id: UUID) -> None:
        """Revoke all tokens for a user by storing a revocation marker in Redis.

        The revocation key TTL matches the refresh token expiry so that the key
        is automatically cleaned up once all tokens have naturally expired.

        Args:
            user_id: User's UUID whose tokens should be revoked
        """
        redis = await self._get_redis()
        if redis is None:
            logger.warning("Could not revoke tokens for user %s: Redis unavailable", user_id)
            return

        key = f"{self._REVOCATION_KEY_PREFIX}{user_id}"
        ttl_seconds = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
        try:
            await redis.set(key, "1", ex=ttl_seconds)
            logger.info("Revoked all tokens for user %s (TTL=%ds)", user_id, ttl_seconds)
        except Exception:
            logger.warning("Failed to write revocation key for user %s", user_id, exc_info=True)

    async def is_token_revoked(self, user_id: UUID) -> bool:
        """Check whether a user's tokens have been revoked.

        Args:
            user_id: User's UUID to check

        Returns:
            True if the user's tokens are revoked, False otherwise (including on Redis failure)
        """
        redis = await self._get_redis()
        if redis is None:
            # Fail open: do not block auth when Redis is unavailable
            return False

        key = f"{self._REVOCATION_KEY_PREFIX}{user_id}"
        try:
            value = await redis.get(key)
            return value is not None
        except Exception:
            logger.warning(
                "Failed to check revocation for user %s; allowing request", user_id, exc_info=True
            )
            return False

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
        del request, client_ip
        raise NotImplementedError("Phase 4 T150a: replace this")

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
        del request, client_ip, user_agent
        raise NotImplementedError("Phase 4 T150a: replace this")

    async def logout(self, user_id: UUID) -> None:
        """Logout user by revoking all active tokens via Redis.

        Stores a revocation marker in Redis keyed on the user ID.  All subsequent
        requests that present a JWT issued before this marker was written will be
        rejected by ``get_current_user``.  The key expires automatically after the
        refresh token TTL so no manual cleanup is required.

        Args:
            user_id: User's UUID
        """
        await self.revoke_user_tokens(user_id)

    async def refresh_token(self, refresh_token: str) -> tuple[TokenResponse, str]:
        """Refresh access token using refresh token.

        Implements refresh token family tracking to detect replay attacks.  When a
        refresh token is used it is marked as consumed in Redis.  If the same jti is
        presented a second time all tokens for the user are immediately revoked and
        an error is returned.

        Args:
            refresh_token: Valid refresh token

        Returns:
            Tuple of (new TokenResponse, new refresh_token)

        Raises:
            HTTPException: If token is invalid, expired, already consumed, or revoked
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
        if not user or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
            )

        # Reject refresh attempts for revoked sessions
        if await self.is_token_revoked(user_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )

        old_jti: str | None = payload.get("jti")
        old_family: str | None = payload.get("family")

        # Replay attack detection via consumed-token tracking with grace period.
        # We store the consumption timestamp so we can distinguish between:
        #   - Race conditions (two concurrent requests using the same token within ~10s)
        #   - Genuine replay attacks (token reused after the grace period)
        _RACE_CONDITION_GRACE_SECONDS = 10
        redis = await self._get_redis()
        if redis and old_jti:
            consumed_key = f"consumed_rt:{old_jti}"
            consumed_at_raw = await redis.get(consumed_key)
            if consumed_at_raw:
                try:
                    consumed_ts = float(consumed_at_raw)
                    elapsed = time.time() - consumed_ts
                except (ValueError, TypeError):
                    # Fallback: treat legacy "1" markers as a genuine replay attack
                    elapsed = _RACE_CONDITION_GRACE_SECONDS + 1

                if elapsed < _RACE_CONDITION_GRACE_SECONDS:
                    # Concurrent refresh request using the same token (race condition).
                    # The first request already issued new tokens; simply reject this one
                    # without revoking the user's entire session.
                    logger.info(
                        "Concurrent refresh detected for jti=%s (%.1fs ago), rejecting duplicate",
                        old_jti,
                        elapsed,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token already refreshed",
                    )
                else:
                    # Token reused well after it was consumed - this is a genuine replay attack.
                    logger.warning(
                        "Replay attack detected: refresh token jti=%s reused for user %s "
                        "(%.1fs after consumption); revoking all tokens",
                        old_jti,
                        user_id,
                        elapsed,
                    )
                    await self.revoke_user_tokens(user_id)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token reuse detected; all sessions have been revoked",
                    )

            # Mark this refresh token as consumed with the current timestamp.
            # Using the timestamp (instead of "1") allows the grace period check above.
            ttl_seconds = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
            try:
                await redis.set(consumed_key, str(time.time()), ex=ttl_seconds)
            except Exception:
                logger.warning(
                    "Failed to mark refresh token jti=%s as consumed", old_jti, exc_info=True
                )

        # Generate new tokens (token rotation), preserving the token family
        token_data = {"sub": str(user.id)}
        new_access_token = create_access_token(token_data)
        new_refresh_token = create_refresh_token(token_data, family_id=old_family)

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
        del token
        raise NotImplementedError("Phase 4 T150a: replace this")

    async def request_password_reset(self, email: str) -> None:
        """Request password reset (always returns success for security).

        Args:
            email: User's email address

        Note:
            Always returns success even if email doesn't exist (security best practice)
        """
        del email
        raise NotImplementedError("Phase 4 T150d: replace this")

    async def confirm_password_reset(self, request: PasswordResetConfirm) -> None:
        """Reset password using token.

        Args:
            request: Password reset confirmation data

        Raises:
            HTTPException: If token is invalid or expired
        """
        del request
        raise NotImplementedError("Phase 4 T150d: replace this")

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

        if user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )

        # Check whether the user has been logged out (all tokens revoked)
        if await self.is_token_revoked(user_id):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user
