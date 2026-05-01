"""SameSite=Strict cookie security tests (T971, FR-097).

Verifies that every session-related cookie issued by the auth refresh
endpoint carries SameSite=Strict, HttpOnly (where required), and uses
the correct Path attributes.

All four cookies must be SameSite=Strict:
  * echoroo_refresh    — HttpOnly, Path=/web-api/v1/auth/refresh
  * echoroo_session    — HttpOnly, Path=/web-api/v1/
  * echoroo_csrf       — httponly=False (public half for double-submit), Path=/
  * echoroo_logged_in  — HttpOnly, Path=/

Design note (shim OFF):
  The cookie transport itself is the subject under test. Using the global
  ``client`` fixture from tests/conftest.py would inject the Phase 16 Batch 6c
  JWT shim which patches AuthRouterMiddleware._authenticate_api_key for /api/v1/*.
  The shim is irrelevant to /web-api/v1 session cookies, but we build our own
  app instance anyway to ensure isolation and clarity of intent.

  We avoid testcontainers here to allow this suite to run in the standard CI
  environment. Instead we use the project-level TEST_DATABASE_URL (same as
  conftest.py) backed by the existing test PostgreSQL instance.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Fixtures — app + session factory backed by TEST_DATABASE_URL
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory_t971() -> AsyncIterator[object]:
    """AsyncSession factory using the shared test DB (no testcontainers).

    Only cleans refresh / token_family tables (no projects/users) to avoid
    FK conflicts with other test data. Tests seed their own users and expect
    the global conftest cleanup_test_data (via db_session fixture) to handle
    the broader table sweep. However, since T971 does NOT use the db_session
    fixture directly, we seed users here and clean them up by unique email
    prefix after the test rather than by blanket DELETE.
    """
    import sqlalchemy as sa

    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            for table in ("refresh_tokens", "token_families"):
                await session.execute(sa.text(
                    f"DO $$ BEGIN IF EXISTS "
                    f"(SELECT 1 FROM pg_class WHERE relname='{table}') "
                    f"THEN DELETE FROM {table}; END IF; END $$"
                ))
        yield factory
    finally:
        # Cleanup test users seeded by this fixture (identified by t971 email prefix).
        async with factory() as session, session.begin():
            for table in ("refresh_tokens", "token_families"):
                await session.execute(sa.text(
                    f"DO $$ BEGIN IF EXISTS "
                    f"(SELECT 1 FROM pg_class WHERE relname='{table}') "
                    f"THEN DELETE FROM {table}; END IF; END $$"
                ))
            await session.execute(sa.text(
                "DELETE FROM users WHERE email LIKE 't971%@example.com'"
            ))
        await engine.dispose()


@pytest.fixture
async def client_t971(
    monkeypatch: pytest.MonkeyPatch,
    session_factory_t971: object,
) -> AsyncIterator[AsyncClient]:
    """Build app WITHOUT the Batch 6c JWT shim — cookie transport is the subject."""
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.database import get_db
    from echoroo.main import create_app
    from echoroo.services.auth_service import AlwaysFreshHibp, InMemoryLoginAttemptRecorder

    async def override_get_db() -> AsyncGenerator[Any, None]:
        async with session_factory_t971() as session:  # type: ignore[operator]
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _noop_audit(**_kwargs: Any) -> None:
        pass

    monkeypatch.setattr(auth_module, "AsyncSessionLocal", session_factory_t971)
    monkeypatch.setattr(auth_module, "_write_platform_audit", _noop_audit)
    monkeypatch.setattr(auth_module, "compute_pii_hash", lambda value: f"hash:{value}")
    monkeypatch.setattr(auth_module, "_login_attempts", InMemoryLoginAttemptRecorder())
    monkeypatch.setattr(auth_module, "_hibp_checker", AlwaysFreshHibp())
    auth_module._register_windows.clear()  # noqa: SLF001

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _create_user(
    session_factory: object,
    *,
    email: str = "t971_user@example.com",
) -> Any:
    from echoroo.core.security import hash_password
    from echoroo.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password("correct horse battery staple"),
        display_name="T971 Test User",
        security_stamp="a" * 64,
        two_factor_enabled=False,
    )
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        session.add(user)
    return user


async def _seed_refresh_token(session_factory: object, user: Any) -> str:
    from echoroo.api.web_v1.auth import _issue_web_refresh_token
    from echoroo.core.auth import SqlTokenStore

    token, record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    await SqlTokenStore(session_factory).record_issued(record)
    return token


def _parse_set_cookie_headers(headers: Any, cookie_name: str) -> list[str]:
    """Return all Set-Cookie header strings that begin with ``<cookie_name>=``."""
    return [
        h
        for h in headers.get_list("set-cookie")
        if h.startswith(f"{cookie_name}=")
    ]


# ---------------------------------------------------------------------------
# T971-1: echoroo_refresh SameSite=Strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_cookie_is_samesite_strict(
    client_t971: AsyncClient,
    session_factory_t971: object,
) -> None:
    """echoroo_refresh must carry SameSite=Strict (FR-097)."""
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory_t971)
    refresh_token = await _seed_refresh_token(session_factory_t971, user)
    response = await client_t971.post(
        "/web-api/v1/auth/refresh",
        cookies={settings.web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200
    headers = _parse_set_cookie_headers(response.headers, settings.web_refresh_cookie_name)
    assert headers, (
        f"echoroo_refresh cookie not set: {response.headers.get_list('set-cookie')!r}"
    )
    header = headers[0].lower()
    assert "samesite=strict" in header, (
        f"echoroo_refresh must carry SameSite=Strict (FR-097), got: {headers[0]!r}"
    )
    assert "httponly" in header, "echoroo_refresh must be HttpOnly"


# ---------------------------------------------------------------------------
# T971-2: echoroo_session SameSite=Strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_cookie_is_samesite_strict(
    client_t971: AsyncClient,
    session_factory_t971: object,
) -> None:
    """echoroo_session must carry SameSite=Strict (FR-097)."""
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory_t971, email="t971_session@example.com")
    refresh_token = await _seed_refresh_token(session_factory_t971, user)
    response = await client_t971.post(
        "/web-api/v1/auth/refresh",
        cookies={settings.web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200
    headers = _parse_set_cookie_headers(response.headers, settings.web_session_cookie_name)
    assert headers, (
        f"echoroo_session cookie not set: {response.headers.get_list('set-cookie')!r}"
    )
    header = headers[0].lower()
    assert "samesite=strict" in header, (
        f"echoroo_session must carry SameSite=Strict (FR-097), got: {headers[0]!r}"
    )
    assert "httponly" in header, "echoroo_session must be HttpOnly"


# ---------------------------------------------------------------------------
# T971-3: echoroo_csrf SameSite=Strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csrf_cookie_is_samesite_strict(
    client_t971: AsyncClient,
    session_factory_t971: object,
) -> None:
    """echoroo_csrf must carry SameSite=Strict (FR-097).

    The CSRF cookie is the public half of the double-submit pattern
    (httponly=False). SameSite=Strict prevents cross-origin forging.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory_t971, email="t971_csrf@example.com")
    refresh_token = await _seed_refresh_token(session_factory_t971, user)
    response = await client_t971.post(
        "/web-api/v1/auth/refresh",
        cookies={settings.web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200
    headers = _parse_set_cookie_headers(response.headers, settings.web_csrf_cookie_name)
    assert headers, (
        f"echoroo_csrf cookie not set: {response.headers.get_list('set-cookie')!r}"
    )
    header = headers[0].lower()
    assert "samesite=strict" in header, (
        f"echoroo_csrf must carry SameSite=Strict (FR-097), got: {headers[0]!r}"
    )
    assert "path=/" in header, "echoroo_csrf must be on Path=/"


# ---------------------------------------------------------------------------
# T971-4: echoroo_logged_in SameSite=Strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logged_in_marker_cookie_is_samesite_strict(
    client_t971: AsyncClient,
    session_factory_t971: object,
) -> None:
    """echoroo_logged_in must carry SameSite=Strict (FR-097)."""
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory_t971, email="t971_marker@example.com")
    refresh_token = await _seed_refresh_token(session_factory_t971, user)
    response = await client_t971.post(
        "/web-api/v1/auth/refresh",
        cookies={settings.web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200
    headers = _parse_set_cookie_headers(response.headers, settings.web_logged_in_cookie_name)
    assert headers, (
        f"echoroo_logged_in cookie not set: {response.headers.get_list('set-cookie')!r}"
    )
    header = headers[0].lower()
    assert "samesite=strict" in header, (
        f"echoroo_logged_in must carry SameSite=Strict (FR-097), got: {headers[0]!r}"
    )
    assert "httponly" in header, "echoroo_logged_in must be HttpOnly"
    assert "path=/" in header, "echoroo_logged_in must be on Path=/"


# ---------------------------------------------------------------------------
# T971-5: all four cookies present and SameSite=Strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_four_cookies_present_and_samesite_strict(
    client_t971: AsyncClient,
    session_factory_t971: object,
) -> None:
    """All four session cookies must be issued and all must be SameSite=Strict.

    This is the regression-guard test: missing or downgraded SameSite on
    any one of the four cookies will fail this assertion.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory_t971, email="t971_all4@example.com")
    refresh_token = await _seed_refresh_token(session_factory_t971, user)
    response = await client_t971.post(
        "/web-api/v1/auth/refresh",
        cookies={settings.web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200

    expected_cookies = {
        settings.web_refresh_cookie_name,
        settings.web_session_cookie_name,
        settings.web_csrf_cookie_name,
        settings.web_logged_in_cookie_name,
    }
    set_cookie_headers = response.headers.get_list("set-cookie")

    for cookie_name in expected_cookies:
        matching = [h for h in set_cookie_headers if h.startswith(f"{cookie_name}=")]
        assert matching, (
            f"Cookie {cookie_name!r} not found in Set-Cookie headers: "
            f"{set_cookie_headers!r}"
        )
        assert "samesite=strict" in matching[0].lower(), (
            f"Cookie {cookie_name!r} must carry SameSite=Strict (FR-097), "
            f"got: {matching[0]!r}"
        )


# ---------------------------------------------------------------------------
# T971-6: cleared cookies on logout also SameSite=Strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cookies_cleared_on_logout_also_samesite_strict(
    client_t971: AsyncClient,
    session_factory_t971: object,
) -> None:
    """Cleared (delete) cookies on logout must also carry SameSite=Strict.

    Cookie deletion requires matching attributes — if the Set-Cookie
    deletion header omits SameSite=Strict the browser may create a sibling
    cookie rather than evicting the original.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory_t971, email="t971_logout@example.com")
    refresh_token = await _seed_refresh_token(session_factory_t971, user)
    refreshed = await client_t971.post(
        "/web-api/v1/auth/refresh",
        cookies={settings.web_refresh_cookie_name: refresh_token},
    )
    assert refreshed.status_code == 200
    csrf = refreshed.headers["X-CSRF-Token"]

    logout = await client_t971.post(
        "/web-api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert logout.status_code == 204

    set_cookie_headers = logout.headers.get_list("set-cookie")
    for cookie_name in (
        settings.web_refresh_cookie_name,
        settings.web_session_cookie_name,
        settings.web_csrf_cookie_name,
        settings.web_logged_in_cookie_name,
    ):
        matching = [h for h in set_cookie_headers if h.startswith(f"{cookie_name}=")]
        assert matching, (
            f"Logout did not clear cookie {cookie_name!r}: {set_cookie_headers!r}"
        )
        assert "samesite=strict" in matching[0].lower(), (
            f"Cleared cookie {cookie_name!r} must carry SameSite=Strict, "
            f"got: {matching[0]!r}"
        )


# ---------------------------------------------------------------------------
# T971-7: Secure attribute is set in staging/production ENVIRONMENT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_session_cookies_are_secure(
    monkeypatch: pytest.MonkeyPatch,
    session_factory_t971: object,
) -> None:
    """All four session cookies carry the Secure attribute when ENVIRONMENT != development.

    In development the ``Secure`` flag is intentionally omitted (plain HTTP
    localhost). In staging / production it MUST be present so cookies are
    never transmitted over plain HTTP.  This test force-sets
    ``auth_module.settings.ENVIRONMENT`` to ``"staging"`` for the duration
    of the request, triggering the ``secure_cookie = True`` branch inside
    ``_set_session_cookies``, then asserts that every issued cookie carries
    ``Secure`` in its header.
    """
    import collections.abc

    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.database import get_db
    from echoroo.core.settings import get_settings
    from echoroo.main import create_app
    from echoroo.services.auth_service import AlwaysFreshHibp, InMemoryLoginAttemptRecorder

    settings = get_settings()

    # Force Secure=True branch for this test.
    monkeypatch.setattr(auth_module.settings, "ENVIRONMENT", "staging")

    async def override_get_db() -> collections.abc.AsyncGenerator[AsyncSession, None]:
        async with session_factory_t971() as session:  # type: ignore[operator]
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _noop_audit(**_kwargs: object) -> None:
        pass

    monkeypatch.setattr(auth_module, "AsyncSessionLocal", session_factory_t971)
    monkeypatch.setattr(auth_module, "_write_platform_audit", _noop_audit)
    monkeypatch.setattr(auth_module, "compute_pii_hash", lambda value: f"hash:{value}")
    monkeypatch.setattr(auth_module, "_login_attempts", InMemoryLoginAttemptRecorder())
    monkeypatch.setattr(auth_module, "_hibp_checker", AlwaysFreshHibp())
    auth_module._register_windows.clear()  # noqa: SLF001

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://testserver",
        ) as client:
            user = await _create_user(
                session_factory_t971, email="t971_secure@example.com"
            )
            refresh_token = await _seed_refresh_token(session_factory_t971, user)
            response = await client.post(
                "/web-api/v1/auth/refresh",
                cookies={settings.web_refresh_cookie_name: refresh_token},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, (
        f"Refresh must succeed for Secure-attribute test, got {response.status_code}: "
        f"{response.text!r}"
    )

    set_cookie_headers = response.headers.get_list("set-cookie")
    for cookie_name in (
        settings.web_refresh_cookie_name,
        settings.web_session_cookie_name,
        settings.web_csrf_cookie_name,
        settings.web_logged_in_cookie_name,
    ):
        matching = [h for h in set_cookie_headers if h.startswith(f"{cookie_name}=")]
        assert matching, (
            f"Cookie {cookie_name!r} not found in Set-Cookie headers: "
            f"{set_cookie_headers!r}"
        )
        header_lower = matching[0].lower()
        assert "secure" in header_lower, (
            f"Cookie {cookie_name!r} must carry Secure attribute in staging/production "
            f"(FR-097), got: {matching[0]!r}"
        )
        assert "samesite=strict" in header_lower, (
            f"Cookie {cookie_name!r} must carry SameSite=Strict, got: {matching[0]!r}"
        )
