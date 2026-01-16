"""User repository for database operations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.user import LoginAttempt, User


class UserRepository:
    """Repository for User entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID.

        Args:
            user_id: User's UUID

        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Get user by email address.

        Args:
            email: User's email address

        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(
            select(User).where(func.lower(User.email) == func.lower(email))
        )
        return result.scalar_one_or_none()

    async def get_by_verification_token(self, token: str) -> User | None:
        """Get user by email verification token.

        Args:
            token: Email verification token

        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(
            select(User).where(User.email_verification_token == token)
        )
        return result.scalar_one_or_none()

    async def get_by_reset_token(self, token: str) -> User | None:
        """Get user by password reset token.

        Args:
            token: Password reset token

        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(select(User).where(User.password_reset_token == token))
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        """Create a new user.

        Args:
            user: User instance to create

        Returns:
            Created user instance
        """
        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def update(self, user: User) -> User:
        """Update an existing user.

        Args:
            user: User instance to update

        Returns:
            Updated user instance
        """
        await self.db.flush()
        await self.db.refresh(user)
        return user

    async def get_recent_failed_attempts(self, email: str, minutes: int = 15) -> int:
        """Count recent failed login attempts for an email.

        Args:
            email: Email address to check
            minutes: Time window in minutes (default: 15)

        Returns:
            Number of failed attempts in the time window
        """
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)
        result = await self.db.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.email == email,
                LoginAttempt.success == False,  # noqa: E712
                LoginAttempt.attempted_at >= cutoff_time,
            )
        )
        count: int = result.scalar_one()
        return count

    async def get_recent_failed_attempts_by_ip(self, ip_address: str, minutes: int = 15) -> int:
        """Count recent failed login attempts from an IP address.

        Args:
            ip_address: IP address to check
            minutes: Time window in minutes (default: 15)

        Returns:
            Number of failed attempts in the time window
        """
        cutoff_time = datetime.now(UTC) - timedelta(minutes=minutes)
        result = await self.db.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.ip_address == ip_address,
                LoginAttempt.success == False,  # noqa: E712
                LoginAttempt.attempted_at >= cutoff_time,
            )
        )
        count: int = result.scalar_one()
        return count

    async def record_login_attempt(
        self,
        email: str,
        ip_address: str,
        success: bool,
        user_agent: str | None = None,
        user_id: UUID | None = None,
    ) -> LoginAttempt:
        """Record a login attempt.

        Args:
            email: Email address used in attempt
            ip_address: Client IP address
            success: Whether login was successful
            user_agent: User agent string
            user_id: User ID (if successful)

        Returns:
            Created LoginAttempt instance
        """
        attempt = LoginAttempt(
            email=email,
            ip_address=ip_address,
            success=success,
            attempted_at=datetime.now(UTC),
            user_agent=user_agent,
            user_id=user_id,
        )
        self.db.add(attempt)
        await self.db.flush()
        return attempt
