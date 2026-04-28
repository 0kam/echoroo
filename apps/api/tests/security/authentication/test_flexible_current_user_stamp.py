"""Phase 12 R3 follow-up (Major #2) — FlexibleCurrentUser superuser stamp.

The legacy ``/api/v1/...`` recordings router uses its own auth helper
:func:`echoroo.api.v1.recordings.get_current_user_flexible` — distinct
from the canonical :func:`echoroo.middleware.auth.get_current_user` —
because media endpoints (``/audio``, ``/stream``, ``/playback``,
``/spectrogram``, ``/download``) accept the access token via the
``?token=`` query parameter so browser ``<audio src>`` / ``<img src>``
elements can stream without forging an Authorization header.

The R2 fix (致命 C1) stamped ``user.is_superuser`` from the
``superusers`` source-of-truth in :func:`get_current_user` and
:func:`get_current_user_optional` so the central permission gate's Step
0c superuser short-circuit (FR-090) had a uniform attribute to consult.
``FlexibleCurrentUser`` was overlooked: it returned an *unstamped* User
instance whose ``is_superuser`` defaulted to ``False`` even for an
active superuser — meaning the legacy media gates skipped the
short-circuit and fell through to the matrix-driven Restricted /
Trusted gates.

This regression test verifies the R3 fix: any User returned from
:func:`get_current_user_flexible` carries ``is_superuser`` consistent
with the ``superusers`` table.

Two sub-cases:

* Active superuser → ``is_superuser is True``.
* Non-superuser     → ``is_superuser is False``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.v1.recordings import get_current_user_flexible
from echoroo.core.jwt import create_access_token
from echoroo.models.user import User


async def _create_user(session: AsyncSession, *, email: str) -> User:
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


async def _promote_superuser(session: AsyncSession, *, user_id: object) -> None:
    """Insert an active row into the ``superusers`` table."""
    await session.execute(
        sa.text(
            "INSERT INTO superusers (user_id, added_at) VALUES (:uid, now())"
        ),
        {"uid": user_id},
    )


@pytest.mark.asyncio
async def test_flexible_current_user_stamps_active_superuser(
    db_session: AsyncSession,
) -> None:
    """An active ``superusers`` row → ``is_superuser is True``.

    Mirrors the contract verified for the canonical
    :data:`CurrentUser` / :data:`OptionalCurrentUser` dependencies in
    R2 致命 C1.
    """
    user = await _create_user(
        db_session, email="r3_flex_su_active@example.com"
    )
    await _promote_superuser(db_session, user_id=user.id)
    await db_session.commit()

    token = create_access_token({"sub": str(user.id)})
    request = MagicMock()  # the dependency only reads it for trace headers

    resolved = await get_current_user_flexible(
        request=request,
        db=db_session,
        token=token,
        credentials=None,
    )

    assert resolved is not None
    assert resolved.id == user.id
    # The R3 fix wires ``_stamp_superuser_status`` into the dispatcher,
    # so the stamped attribute MUST exist and reflect the SOT.
    assert hasattr(resolved, "is_superuser"), (
        "FlexibleCurrentUser MUST stamp is_superuser after R3 (Major #2)"
    )
    assert resolved.is_superuser is True


@pytest.mark.asyncio
async def test_flexible_current_user_stamps_non_superuser_false(
    db_session: AsyncSession,
) -> None:
    """A user with NO ``superusers`` row → ``is_superuser is False``.

    Critical fail-closed branch: an unstamped attribute would default
    to ``False`` accidentally, so this test pins the explicit-stamp
    behaviour by inserting a competing default and re-verifying after
    the dependency runs.
    """
    user = await _create_user(
        db_session, email="r3_flex_plain_user@example.com"
    )
    await db_session.commit()

    # Pre-stamp a misleading True on the in-memory ORM instance to
    # ensure the dependency RE-stamps from the database rather than
    # accidentally relying on a stale attribute.
    user.is_superuser = True  # type: ignore[attr-defined]

    token = create_access_token({"sub": str(user.id)})
    request = MagicMock()

    resolved = await get_current_user_flexible(
        request=request,
        db=db_session,
        token=token,
        credentials=None,
    )

    assert resolved is not None
    assert resolved.id == user.id
    assert resolved.is_superuser is False, (
        "non-superuser must be stamped False even if a stale True was "
        "set in-memory before the dependency ran (R3 Major #2)"
    )


@pytest.mark.asyncio
async def test_flexible_current_user_returns_none_for_missing_token(
    db_session: AsyncSession,
) -> None:
    """Guest fall-through (no token) returns ``None`` unchanged.

    The R3 fix MUST NOT regress the Guest path — Public-readable
    media endpoints rely on the dependency returning ``None`` when no
    credentials are supplied so the central gate decides Public-Guest
    visibility.
    """
    request = MagicMock()
    resolved = await get_current_user_flexible(
        request=request,
        db=db_session,
        token=None,
        credentials=None,
    )
    assert resolved is None


__all__ = [
    "test_flexible_current_user_stamps_active_superuser",
    "test_flexible_current_user_stamps_non_superuser_false",
    "test_flexible_current_user_returns_none_for_missing_token",
]
