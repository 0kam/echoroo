"""Fixtures for integration tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.user import User


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user for integration tests.

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="integrationtest@example.com",
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Integration Test User",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers(db_session: AsyncSession, test_user: User) -> dict[str, str]:
    """Create authentication headers for test user.

    Args:
        db_session: Database session
        test_user: Test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {access_token}"}
