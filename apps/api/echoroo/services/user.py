"""User profile service with business logic."""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password, verify_password
from echoroo.models.user import User
from echoroo.repositories.user import UserRepository
from echoroo.schemas.user import PasswordChangeRequest, UserUpdateRequest


class UserService:
    """User service for profile management."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize user service.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db
        self.user_repo = UserRepository(db)

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
        if request.organization is not None:
            user.organization = request.organization

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
        if not verify_password(request.current_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid current password",
            )

        # Check if new password is same as current
        if verify_password(request.new_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be different from current password",
            )

        # Update password
        user.hashed_password = hash_password(request.new_password)
        await self.user_repo.update(user)
        await self.db.commit()
