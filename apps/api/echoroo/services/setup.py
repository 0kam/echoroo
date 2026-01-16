"""Setup service for initial system configuration."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.security import hash_password
from echoroo.models.user import User
from echoroo.repositories.system import SystemSettingRepository
from echoroo.schemas.setup import SetupInitializeRequest, SetupStatusResponse


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

    async def initialize_setup(self, request: SetupInitializeRequest) -> User:
        """Initialize system setup by creating the first admin user.

        Creates a superuser account and marks setup as completed.

        Args:
            request: Setup initialization request with admin user details

        Returns:
            Created User object

        Raises:
            HTTPException: 403 if setup is already completed or users exist
        """
        # Check if setup is already completed
        setup_completed = await self.system_repo.is_setup_completed()
        if setup_completed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Initial setup has already been completed",
            )

        # Check if any users already exist
        result = await self.session.execute(select(User).limit(1))
        existing_user = result.scalar_one_or_none()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Users already exist. Setup cannot be performed.",
            )

        # Create the first admin user
        user = User(
            email=request.email,
            hashed_password=hash_password(request.password),
            display_name=request.display_name,
            is_active=True,
            is_superuser=True,  # First user is always superuser
            is_verified=True,  # Auto-verify first user
        )

        self.session.add(user)

        # Mark setup as completed
        await self.system_repo.mark_setup_completed()

        # Commit transaction
        await self.session.commit()
        await self.session.refresh(user)

        return user
