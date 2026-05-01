"""Phase 13 P1 R2 致命 #1 + #2 — system_settings FK + admin caller path.

Two regressions are pinned here:

1. ``system_settings.updated_by_id`` is ``NOT NULL`` and FKs ``superusers.id``
   (not ``users.id``). Persisting a row with ``users.id`` violates the FK and
   must raise ``IntegrityError``. Persisting with the active ``superusers.id``
   succeeds.

2. The admin auth dependency (:func:`echoroo.middleware.auth._stamp_superuser_status`)
   stamps both ``user.is_superuser`` and ``user._superuser_id`` so the admin
   handler at ``PATCH /api/v1/admin/settings`` can persist the FK without a
   second SQL probe. We verify the stamped id is the *superusers* id, not the
   *users* id, and that it survives a round-trip through the repository.

These tests are deliberately scoped at the repository / database layer to
avoid coupling to the broader (still-stubbed) admin HTTP surface in
``apps/api/echoroo/api/v1/admin.py`` whose ``update_user`` path remains
501 Not Implemented (Phase 4 deferred work).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.middleware.auth import _stamp_superuser_status
from echoroo.models.user import User
from echoroo.repositories.system import SystemSettingRepository


async def _create_user(session: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"User {email}",
        security_stamp="0" * 64,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _promote_superuser(session: AsyncSession, user_id: object) -> object:
    """Insert a ``superusers`` row and return ``superusers.id`` (NOT user_id)."""
    return (
        await session.execute(
            sa.text(
                "INSERT INTO superusers (user_id, added_at) VALUES "
                "(:uid, now()) RETURNING id"
            ),
            {"uid": user_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_set_setting_with_superuser_fk_succeeds(
    db_session: AsyncSession,
) -> None:
    """Happy path: persist a setting with a real ``superusers.id``."""
    user = await _create_user(db_session, "ss_fk_ok@example.com")
    su_id = await _promote_superuser(db_session, user.id)
    await db_session.commit()

    repo = SystemSettingRepository(db_session)
    setting = await repo.set_setting(
        key="trusted_default_duration_seconds",
        value=7_776_000,
        updated_by_id=su_id,
    )
    await db_session.commit()

    assert setting.key == "trusted_default_duration_seconds"
    assert setting.value == 7_776_000
    assert setting.updated_by_id == su_id


@pytest.mark.asyncio
async def test_set_setting_with_user_id_violates_fk(
    db_session: AsyncSession,
) -> None:
    """Negative path: ``users.id`` is NOT a valid value for ``updated_by_id``.

    Pins the Phase 13 P1 R2 致命 #2 contract: the admin handler must NOT
    pass ``current_user.id`` directly. The DB rejects it with a FK
    integrity violation.
    """
    user = await _create_user(db_session, "ss_fk_bad@example.com")
    # Promote to superuser so the user *exists* — but we pass user.id (not
    # superusers.id) below to confirm the FK rejects.
    await _promote_superuser(db_session, user.id)
    await db_session.commit()

    repo = SystemSettingRepository(db_session)
    with pytest.raises(IntegrityError):
        await repo.set_setting(
            key="dormant_threshold_seconds",
            value=31_622_400,
            updated_by_id=user.id,  # WRONG — this is users.id, not superusers.id
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_stamp_superuser_status_resolves_superusers_id(
    db_session: AsyncSession,
) -> None:
    """``_stamp_superuser_status`` writes ``users.id`` *and* ``superusers.id``.

    The admin endpoint reads ``current_user._superuser_id`` to populate the
    ``system_settings.updated_by_id`` FK; this test pins the contract that
    the stamp resolves the *superusers* id, not the *users* id.
    """
    user = await _create_user(db_session, "stamp_su_id@example.com")
    expected_su_id = await _promote_superuser(db_session, user.id)
    await db_session.commit()

    await _stamp_superuser_status(db_session, user)

    assert user.is_superuser is True  # type: ignore[attr-defined]
    assert user._superuser_id == expected_su_id  # type: ignore[attr-defined]
    assert user._superuser_id != user.id  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_stamp_superuser_status_none_for_plain_user(
    db_session: AsyncSession,
) -> None:
    """Plain users get ``_superuser_id = None`` — admin handlers fail-close."""
    user = await _create_user(db_session, "stamp_plain@example.com")
    await db_session.commit()

    await _stamp_superuser_status(db_session, user)

    assert user.is_superuser is False  # type: ignore[attr-defined]
    assert user._superuser_id is None  # type: ignore[attr-defined]
