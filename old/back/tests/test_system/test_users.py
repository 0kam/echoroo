import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, models
from echoroo.api.users import ensure_system_user
from echoroo.system.users import UserDatabase


@pytest.mark.asyncio
async def test_has_user_ignores_system_account(session: AsyncSession):
    user_db = UserDatabase(session, models.User)

    # No users created yet.
    assert await user_db.has_user() is False

    # Insert the system user (inactive) and ensure it does not count.
    await ensure_system_user(session)
    assert await user_db.has_user() is False

    # Regular active user should be counted.
    await api.users.create(
        session,
        username="first_user",
        password="password",
        email="first@example.com",
        is_active=True,
    )
    await session.commit()

    assert await user_db.has_user() is True
