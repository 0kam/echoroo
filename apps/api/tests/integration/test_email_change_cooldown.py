"""Integration tests for the 24-hour email-change cool-off gate (spec/011 §FR-011-305).

The cool-off window opened by a successful self-service email change also
blocks:

* ``UserService.change_email`` — cannot change email again during the window.
* ``UserService.change_password`` — legacy self-service password change is
  gated too (FIX 1, T621 regression guard).
* ``self_password_change.change_password`` — the BFF/v1 change-password
  service raises ``EmailChangeCooldownActiveError`` → HTTP 409.

Coverage from task description (review finding #2):

1. Seeded cooldown → ``change_email`` raises 409 ``email_change_cooldown_active``
   AND ``user.email`` is unchanged (no half-update).
2. Successful ``change_email`` (no prior cooldown) sets
   ``email_change_cooldown_until ≈ now+24h`` (tz-aware).
3. Naive-tz cooldown timestamp → gate still rejects (tz-normalization path).
4. ``UserService.change_password`` with active cooldown → 409
   ``email_change_cooldown_active`` EVEN WHEN ``current_password`` correct.
5. ``self_password_change.change_password`` with active cooldown → 409 via BFF.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from echoroo.api.web_v1 import auth as web_auth_module
from echoroo.api.web_v1.auth import router as web_auth_router
from echoroo.core.database import get_db
from echoroo.core.security import hash_password
from echoroo.middleware.auth import get_current_user
from echoroo.middleware.auth_router import Principal
from echoroo.models.user import User
from echoroo.schemas.user import PasswordChangeRequest
from echoroo.services import self_password_change
from echoroo.services.user import EMAIL_CHANGE_COOLDOWN, UserService
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.asyncio

_PASSWORD = "CooloffTestPassw0rd!2026"
_NEW_EMAIL = "cooloff-new@example.com"
_NEW_PASSWORD = "CooloffNewPassw0rd!2026"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(
    db: AsyncSession,
    *,
    suffix: str = "",
    email_change_cooldown_until: datetime | None = None,
) -> User:
    """Create a fresh User for the test, optionally with an active cooldown."""
    user = User(
        email=f"cooloff-base{suffix}@example.com",
        password_hash=hash_password(_PASSWORD),
        security_stamp=secrets.token_hex(32),
        email_change_cooldown_until=email_change_cooldown_until,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Fixtures — minimal FastAPI app with change-password BFF router
# ---------------------------------------------------------------------------


class _PrincipalMiddleware(BaseHTTPMiddleware):
    """Stamps ``request.state.principal`` from the X-Test-Principal header."""

    def __init__(self, app: Any, *, user_ids: dict[str, UUID]) -> None:
        super().__init__(app)
        self._user_ids = user_ids

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: Any,
    ) -> StarletteResponse:
        marker = request.headers.get("x-test-principal")
        uid = self._user_ids.get(marker) if marker else None
        if uid is None:
            request.state.principal = None
        else:
            request.state.principal = Principal.for_session(
                user_id=uid,
                security_stamp="s" * 64,
            )
        return await call_next(request)


@pytest_asyncio.fixture
async def audit_session_maker(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Rebind AsyncSessionLocal in both service modules onto the test engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(
        self_password_change, "AsyncSessionLocal", maker, raising=True
    )
    monkeypatch.setattr(web_auth_module, "AsyncSessionLocal", maker, raising=True)
    yield maker
    await engine.dispose()


@pytest_asyncio.fixture
async def cooloff_app(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[tuple[FastAPI, User], None]:
    """Build a minimal app with the BFF change-password router.

    The fixture creates ONE fresh user with NO cooldown. Callers seed
    ``email_change_cooldown_until`` via direct ORM mutation if they need an
    active cooldown.
    """
    user = await _make_user(db_session, suffix="-app")
    user_ids: dict[str, UUID] = {"user": user.id}

    app = FastAPI()
    app.include_router(web_auth_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    async def _override_current_user(
        request: StarletteRequest,
    ) -> User:
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_current_user
    app.add_middleware(_PrincipalMiddleware, user_ids=user_ids)
    yield app, user


# ---------------------------------------------------------------------------
# Case 1 — active cooldown → change_email rejects with 409, email unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_email_blocked_during_cooldown(
    db_session: AsyncSession,
) -> None:
    """change_email raises HTTP 409 and does NOT mutate user.email."""
    original_email = "cooloff-c1@example.com"
    user = User(
        email=original_email,
        password_hash=hash_password(_PASSWORD),
        security_stamp=secrets.token_hex(32),
        email_change_cooldown_until=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    svc = UserService(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.change_email(user.id, "c1-new@example.com")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "email_change_cooldown_active"

    # Verify no half-update: email is still the original value.
    await db_session.refresh(user)
    assert user.email == original_email


# ---------------------------------------------------------------------------
# Case 2 — successful change_email sets cooldown_until ≈ now+24h (tz-aware)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_change_email_sets_cooldown(
    db_session: AsyncSession,
) -> None:
    """A successful email change writes a tz-aware cooldown_until ≈ now+24h."""
    user = await _make_user(db_session, suffix="-c2")
    assert user.email_change_cooldown_until is None

    before = datetime.now(UTC)
    svc = UserService(db_session)
    await svc.change_email(user.id, _NEW_EMAIL)

    await db_session.refresh(user)
    cooldown = user.email_change_cooldown_until
    assert cooldown is not None, "cooldown_until should have been set"
    # Must be timezone-aware.
    assert cooldown.tzinfo is not None, "cooldown_until must be tz-aware"
    # Must be approximately now + 24 h (within a 30-second tolerance).
    expected = before + EMAIL_CHANGE_COOLDOWN
    delta = abs((cooldown - expected).total_seconds())
    assert delta < 30, f"cooldown_until={cooldown} too far from expected {expected}"


# ---------------------------------------------------------------------------
# Case 3 — naive-tz cooldown timestamp → gate normalizes and still rejects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_email_naive_cooldown_timestamp_still_rejects(
    db_session: AsyncSession,
) -> None:
    """A naive cooldown_until is treated as UTC and still blocks the change."""
    # Store a NAIVE timestamp that is 1 hour in the future (as UTC without tzinfo).
    naive_future = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
    original_email = "cooloff-c3@example.com"
    user = User(
        email=original_email,
        password_hash=hash_password(_PASSWORD),
        security_stamp=secrets.token_hex(32),
        email_change_cooldown_until=naive_future,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    svc = UserService(db_session)
    with pytest.raises(HTTPException) as exc_info:
        await svc.change_email(user.id, "c3-new@example.com")

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "email_change_cooldown_active"
    await db_session.refresh(user)
    assert user.email == original_email


# ---------------------------------------------------------------------------
# Case 4 — UserService.change_password with active cooldown → 409 even if pw correct
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_change_password_blocked_during_cooldown(
    db_session: AsyncSession,
) -> None:
    """UserService.change_password rejects with 409 while cooldown active.

    FIX 1 regression guard: the cool-off gate fires BEFORE the credential
    check, so even a correct current_password is blocked.
    """
    user = User(
        email="cooloff-c4@example.com",
        password_hash=hash_password(_PASSWORD),
        security_stamp=secrets.token_hex(32),
        email_change_cooldown_until=datetime.now(UTC) + timedelta(hours=2),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    svc = UserService(db_session)
    req = PasswordChangeRequest(
        current_password=_PASSWORD,  # correct password
        new_password=_NEW_PASSWORD,
    )
    with pytest.raises(HTTPException) as exc_info:
        await svc.change_password(user.id, req)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "email_change_cooldown_active"

    # Password must be unchanged (no half-write).
    await db_session.refresh(user)
    from echoroo.core.security import verify_password
    assert verify_password(_PASSWORD, user.password_hash), (
        "password must NOT have been updated during an active cooldown"
    )


# ---------------------------------------------------------------------------
# Case 5 — self_password_change via BFF endpoint → 409 during cooldown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bff_change_password_blocked_during_cooldown(
    cooloff_app: tuple[FastAPI, User],
    db_session: AsyncSession,
) -> None:
    """POST /web-api/v1/auth/change-password returns 409 during active cooldown."""
    app, user = cooloff_app

    # Seed an active cooldown directly on the ORM object.
    user.email_change_cooldown_until = datetime.now(UTC) + timedelta(hours=3)
    db_session.add(user)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": _PASSWORD,
                "new_password": _NEW_PASSWORD,
            },
            headers={"X-Test-Principal": "user"},
        )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["detail"]["error_code"] == "email_change_cooldown_active"
