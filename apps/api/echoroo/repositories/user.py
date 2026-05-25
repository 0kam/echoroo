"""User repository for database operations."""

from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.sql import ColumnElement

from echoroo.models.superuser import Superuser
from echoroo.models.user import User
from echoroo.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Repository for User entity operations."""

    model = User

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by ID.

        Args:
            user_id: User's UUID

        Returns:
            User instance or None if not found
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def list_users(
        self,
        *,
        offset: int,
        limit: int,
        search: str | None = None,
    ) -> tuple[list[tuple[User, bool]], int]:
        """List active (non-soft-deleted) users with the superuser flag resolved.

        Args:
            offset: Number of rows to skip (``(page - 1) * page_size``).
            limit: Maximum number of rows to return.
            search: Optional case-insensitive substring filter applied to
                ``email`` OR ``display_name``.

        Returns:
            Tuple of ``(rows, total_count)``:

            * ``rows`` — list of ``(User, is_superuser)`` tuples ordered
              by ``created_at`` descending. ``is_superuser`` is ``True``
              iff the user has a matching row in ``superusers`` with
              ``revoked_at IS NULL`` (FR-111 SOT for operator status).
              Resolved via a single LEFT JOIN so there is no N+1.
            * ``total_count`` — number of rows matching the filter,
              independent of pagination.

        spec/011 follow-up (2026-05-26): previously returned only
        ``list[User]``; the schema layer now needs the ``is_superuser``
        flag for the admin UI badge, so the join is moved into the
        repository and the response shape upgraded to a tuple. Existing
        callers update accordingly.
        """
        filters: list[ColumnElement[bool]] = [User.deleted_at.is_(None)]
        if search:
            pattern = f"%{search}%"
            filters.append(
                or_(
                    User.email.ilike(pattern),
                    User.display_name.ilike(pattern),
                )
            )

        total_stmt = select(func.count()).select_from(User).where(*filters)
        total = int((await self.db.execute(total_stmt)).scalar_one())

        # LEFT JOIN superusers with the ``revoked_at IS NULL`` predicate
        # baked into the join clause so revoked rows are dropped during
        # the join (rather than carried into the result set as falsy).
        # ``case(...)`` collapses the NULL/UUID outer-join column into a
        # boolean returned alongside the User row.
        is_superuser_expr = case(
            (Superuser.id.is_not(None), True),
            else_=False,
        ).label("is_superuser")

        rows_stmt = (
            select(User, is_superuser_expr)
            .outerjoin(
                Superuser,
                (Superuser.user_id == User.id) & Superuser.revoked_at.is_(None),
            )
            .where(*filters)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(rows_stmt)
        rows: list[tuple[User, bool]] = [
            (user, bool(is_superuser)) for user, is_superuser in result.all()
        ]
        return rows, total

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
        raise NotImplementedError("Phase 4 T150a: replace this")

    async def get_by_reset_token(self, token: str) -> User | None:
        """Get user by password reset token.

        Args:
            token: Password reset token

        Returns:
            User instance or None if not found
        """
        raise NotImplementedError("Phase 4 T150d: replace this")

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
        raise NotImplementedError("Phase 4 T178: login attempt tracking moved to audit log")

    async def get_recent_failed_attempts_by_ip(self, ip_address: str, minutes: int = 15) -> int:
        """Count recent failed login attempts from an IP address.

        Args:
            ip_address: IP address to check
            minutes: Time window in minutes (default: 15)

        Returns:
            Number of failed attempts in the time window
        """
        raise NotImplementedError("Phase 4 T178: login attempt tracking moved to audit log")

    async def record_login_attempt(
        self,
        email: str,
        ip_address: str,
        success: bool,
        user_agent: str | None = None,
        user_id: UUID | None = None,
    ) -> None:
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
        raise NotImplementedError("Phase 4 T178: login attempt tracking moved to audit log")
