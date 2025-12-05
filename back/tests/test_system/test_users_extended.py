"""Extended tests for the users module."""

import pytest
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, models, schemas
from echoroo.api.users import ensure_system_user
from echoroo.system.users import UserDatabase, UserManager, is_first_user


class TestUserDatabase:
    """Test the UserDatabase class."""

    @pytest.mark.asyncio
    async def test_has_user_returns_false_for_empty_db(self, session: AsyncSession):
        """Test that has_user returns False for empty database."""
        user_db = UserDatabase(session, models.User)
        assert await user_db.has_user() is False

    @pytest.mark.asyncio
    async def test_has_user_ignores_system_account(self, session: AsyncSession):
        """Test that system user is ignored by has_user."""
        user_db = UserDatabase(session, models.User)
        assert await user_db.has_user() is False

        # Create system user
        await ensure_system_user(session)
        assert await user_db.has_user() is False

    @pytest.mark.asyncio
    async def test_has_user_ignores_inactive_accounts(self, session: AsyncSession):
        """Test that inactive users are ignored by has_user."""
        user_db = UserDatabase(session, models.User)

        # Create an inactive user
        await api.users.create(
            session,
            username="inactive",
            password="password",
            email="inactive@example.com",
            is_active=False,
        )
        await session.commit()

        assert await user_db.has_user() is False

    @pytest.mark.asyncio
    async def test_has_user_returns_true_with_active_user(self, session: AsyncSession):
        """Test that has_user returns True with active user."""
        user_db = UserDatabase(session, models.User)

        await api.users.create(
            session,
            username="active",
            password="password",
            email="active@example.com",
            is_active=True,
        )
        await session.commit()

        assert await user_db.has_user() is True

    @pytest.mark.asyncio
    async def test_get_by_username_returns_user(self, session: AsyncSession):
        """Test that get_by_username returns the correct user."""
        user_db = UserDatabase(session, models.User)

        created_user = await api.users.create(
            session,
            username="testuser",
            password="password",
            email="test@example.com",
            is_active=True,
        )
        await session.commit()

        user = await user_db.get_by_username("testuser")
        assert user is not None
        assert user.username == "testuser"
        assert user.id == created_user.id

    @pytest.mark.asyncio
    async def test_get_by_username_returns_none_for_nonexistent(
        self, session: AsyncSession
    ):
        """Test that get_by_username returns None for nonexistent user."""
        user_db = UserDatabase(session, models.User)
        user = await user_db.get_by_username("nonexistent")
        assert user is None

    @pytest.mark.asyncio
    async def test_get_by_username_case_sensitive(self, session: AsyncSession):
        """Test that get_by_username is case-sensitive."""
        user_db = UserDatabase(session, models.User)

        await api.users.create(
            session,
            username="TestUser",
            password="password",
            email="test@example.com",
            is_active=True,
        )
        await session.commit()

        # Exact match should work
        user = await user_db.get_by_username("TestUser")
        assert user is not None

        # Different case should not work
        user = await user_db.get_by_username("testuser")
        assert user is None


class TestUserManager:
    """Test the UserManager class."""

    @pytest.mark.asyncio
    async def test_get_by_username_raises_on_not_found(self, session: AsyncSession):
        """Test that get_by_username raises UserNotExists for nonexistent user."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)

        with pytest.raises(exceptions.UserNotExists):
            await manager.get_by_username("nonexistent")

    @pytest.mark.asyncio
    async def test_get_by_username_returns_user(self, session: AsyncSession):
        """Test that get_by_username returns the correct user."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)

        created_user = await api.users.create(
            session,
            username="testuser",
            password="password",
            email="test@example.com",
            is_active=True,
        )
        await session.commit()

        user = await manager.get_by_username("testuser")
        assert user is not None
        assert user.username == "testuser"
        assert user.id == created_user.id

    @pytest.mark.asyncio
    async def test_authenticate_with_valid_credentials(self, session: AsyncSession):
        """Test authentication with valid credentials."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)

        created_user = await api.users.create(
            session,
            username="testuser",
            password="testpassword",
            email="test@example.com",
            is_active=True,
        )
        await session.commit()

        credentials = OAuth2PasswordRequestForm(
            username="testuser", password="testpassword", grant_type="password"
        )
        user = await manager.authenticate(credentials)
        assert user is not None
        assert user.username == "testuser"
        assert user.id == created_user.id

    @pytest.mark.asyncio
    async def test_authenticate_with_invalid_password(self, session: AsyncSession):
        """Test authentication with invalid password."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)

        await api.users.create(
            session,
            username="testuser",
            password="correctpassword",
            email="test@example.com",
            is_active=True,
        )
        await session.commit()

        credentials = OAuth2PasswordRequestForm(
            username="testuser", password="wrongpassword", grant_type="password"
        )
        user = await manager.authenticate(credentials)
        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_with_nonexistent_user(self, session: AsyncSession):
        """Test authentication with nonexistent user."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)

        credentials = OAuth2PasswordRequestForm(
            username="nonexistent", password="password", grant_type="password"
        )
        user = await manager.authenticate(credentials)
        assert user is None

    @pytest.mark.asyncio
    async def test_authenticate_with_inactive_user(self, session: AsyncSession):
        """Test authentication with inactive user (note: system allows it to proceed)."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)

        await api.users.create(
            session,
            username="inactive",
            password="password",
            email="inactive@example.com",
            is_active=False,
        )
        await session.commit()

        credentials = OAuth2PasswordRequestForm(
            username="inactive", password="password", grant_type="password"
        )
        # Note: The system allows authentication of inactive users
        # The is_active flag is not checked during password verification
        user = await manager.authenticate(credentials)
        assert user is not None
        assert user.username == "inactive"

    @pytest.mark.asyncio
    async def test_manager_has_password_helper(self, session: AsyncSession):
        """Test that manager has password helper."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(user_db)
        assert hasattr(manager, "password_helper")
        assert manager.password_helper is not None

    @pytest.mark.asyncio
    async def test_manager_initialization(self, session: AsyncSession):
        """Test manager initialization with custom secrets."""
        user_db = UserDatabase(session, models.User)
        manager = UserManager(
            user_db,
            reset_password_token_secret="custom_secret",
            verification_token_secret="custom_verification",
        )
        assert manager.reset_password_token_secret == "custom_secret"
        assert manager.verification_token_secret == "custom_verification"


class TestIsFirstUser:
    """Test the is_first_user function."""

    @pytest.mark.asyncio
    async def test_returns_true_for_empty_db(self, session: AsyncSession):
        """Test that is_first_user returns True for empty database."""
        is_first = await is_first_user(session)
        assert is_first is True

    @pytest.mark.asyncio
    async def test_returns_true_with_only_system_user(self, session: AsyncSession):
        """Test that is_first_user returns True with only system user."""
        await ensure_system_user(session)
        await session.commit()

        is_first = await is_first_user(session)
        assert is_first is True

    @pytest.mark.asyncio
    async def test_returns_false_with_active_user(self, session: AsyncSession):
        """Test that is_first_user returns False with active user."""
        await api.users.create(
            session,
            username="firstuser",
            password="password",
            email="first@example.com",
            is_active=True,
        )
        await session.commit()

        is_first = await is_first_user(session)
        assert is_first is False

    @pytest.mark.asyncio
    async def test_returns_true_with_only_inactive_user(self, session: AsyncSession):
        """Test that is_first_user returns True with only inactive user."""
        await api.users.create(
            session,
            username="inactive",
            password="password",
            email="inactive@example.com",
            is_active=False,
        )
        await session.commit()

        is_first = await is_first_user(session)
        assert is_first is True

    @pytest.mark.asyncio
    async def test_multiple_calls_consistent(self, session: AsyncSession):
        """Test that multiple calls return consistent results."""
        is_first_1 = await is_first_user(session)
        is_first_2 = await is_first_user(session)
        assert is_first_1 == is_first_2

    @pytest.mark.asyncio
    async def test_changes_after_user_creation(self, session: AsyncSession):
        """Test that result changes after creating a user."""
        is_first = await is_first_user(session)
        assert is_first is True

        await api.users.create(
            session,
            username="firstuser",
            password="password",
            email="first@example.com",
            is_active=True,
        )
        await session.commit()

        is_first = await is_first_user(session)
        assert is_first is False
