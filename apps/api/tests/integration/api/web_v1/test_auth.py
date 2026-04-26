"""Integration coverage for the first-party auth router (T150a)."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dev extra may be absent locally
    PostgresContainer = None  # type: ignore[assignment,misc]

API_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = API_ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
    except Exception as exc:  # noqa: BLE001 - container runtime availability varies
        pytest.skip(f"PostgreSQL testcontainer unavailable: {exc}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def upgraded_db(pg_container: object) -> str:
    sync_url = pg_container.get_connection_url()  # type: ignore[attr-defined]
    sync_url = sync_url.replace("postgresql+psycopg2://", "postgresql://")
    env = {
        "DATABASE_URL": sync_url.replace("postgresql://", "postgresql+asyncpg://"),
        "ALEMBIC_SYNC_URL": sync_url,
        "JWT_SECRET_KEY": "test-jwt-secret-value-with-32-characters",
        "web_session_secret": "test-web-session-secret-with-32-chars",
    }
    result = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(API_ROOT),
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return sync_url.replace("postgresql://", "postgresql+asyncpg://")


@pytest.fixture
async def session_factory(upgraded_db: str) -> AsyncIterator[object]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(upgraded_db, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            for table in ("refresh_tokens", "token_families", "users"):
                await session.execute(__import__("sqlalchemy").text(f"DELETE FROM {table}"))
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: object,
) -> AsyncIterator[AsyncClient]:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.database import get_db
    from echoroo.main import create_app
    from echoroo.services.auth_service import AlwaysFreshHibp, InMemoryLoginAttemptRecorder

    async def override_get_db() -> AsyncGenerator[Any, None]:
        async with session_factory() as session:  # type: ignore[operator]
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    audit_events: list[dict[str, Any]] = []

    async def record_audit(**kwargs: Any) -> None:
        audit_events.append(kwargs)

    monkeypatch.setattr(auth_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(auth_module, "_write_platform_audit", record_audit)
    monkeypatch.setattr(auth_module, "compute_pii_hash", lambda value: f"hash:{value}")
    monkeypatch.setattr(auth_module, "_login_attempts", InMemoryLoginAttemptRecorder())
    monkeypatch.setattr(auth_module, "_hibp_checker", AlwaysFreshHibp())
    auth_module._register_windows.clear()  # noqa: SLF001 - test isolation

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.state.audit_events = audit_events
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


async def _create_user(
    session_factory: object,
    *,
    email: str = "user@example.com",
    password: str = "correct horse battery staple",
    two_factor_enabled: bool = False,
    security_stamp: str = "s" * 64,
) -> Any:
    from echoroo.core.security import hash_password
    from echoroo.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        display_name="Test User",
        security_stamp=security_stamp,
        two_factor_enabled=two_factor_enabled,
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


@pytest.mark.asyncio
async def test_register_creates_user_and_returns_2fa_setup_required(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/web-api/v1/auth/register",
        json={
            "email": "NewUser@example.com",
            "password": "correct horse battery staple",
            "display_name": "New User",
            "timezone": "Asia/Tokyo",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "newuser@example.com"
    assert body["two_factor_setup_required"] is True


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client: AsyncClient) -> None:
    response = await client.post(
        "/web-api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )
    assert response.status_code == 422
    assert "at least 8 characters" in response.text


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    payload = {"email": "Dup@example.com", "password": "correct horse battery staple"}
    first = await client.post("/web-api/v1/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post(
        "/web-api/v1/auth/register",
        json={**payload, "email": "dup@EXAMPLE.com"},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_login_with_correct_password_returns_2fa_required_when_2fa_enabled(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, two_factor_enabled=True)
    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    assert response.json()["login_state"] == "2fa_required"
    assert "interim_token" in response.json()


@pytest.mark.asyncio
async def test_login_with_correct_password_returns_2fa_setup_required_when_2fa_disabled(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, two_factor_enabled=False)
    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    assert response.json()["login_state"] == "2fa_setup_required"


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401_constant_time(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory)
    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_login_attempts_apply_backoff_after_threshold(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory)
    for _ in range(5):
        response = await client.post(
            "/web-api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong password"},
        )
        assert response.status_code == 401
    locked = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong password"},
    )
    assert locked.status_code == 429
    assert locked.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_refresh_rotates_family_and_reissues_tokens(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200
    assert response.json()["expires_in"] == 900
    assert "access_token" in response.json()
    assert get_settings().web_refresh_cookie_name in response.cookies
    assert get_settings().web_csrf_cookie_name in response.cookies


@pytest.mark.asyncio
async def test_session_establish_sets_logged_in_marker_cookie_on_root_path(
    client: AsyncClient,
    session_factory: object,
) -> None:
    """T160-T163 P0: marker cookie must be Path=/ so SvelteKit page guards see it.

    The session/refresh/csrf cookies are scoped to /web-api/v1/* and cannot
    be read by SvelteKit page-level routes (e.g. /dashboard). The
    ``echoroo_logged_in`` marker carries no sensitive content (literal "1")
    and is set on Path=/ so ``hooks.server.ts`` can detect logged-in state.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200
    set_cookie_headers = response.headers.get_list("set-cookie")
    marker_headers = [
        h for h in set_cookie_headers
        if h.startswith(f"{settings.web_logged_in_cookie_name}=")
    ]
    assert len(marker_headers) == 1, (
        f"expected one marker cookie header, got: {set_cookie_headers!r}"
    )
    marker_header = marker_headers[0]
    assert f"{settings.web_logged_in_cookie_name}=1" in marker_header
    assert "Path=/" in marker_header
    assert "Path=/web-api" not in marker_header
    assert "HttpOnly" in marker_header
    # The session/refresh cookies remain scoped to /web-api/v1/*.
    session_headers = [
        h for h in set_cookie_headers
        if h.startswith(f"{settings.web_session_cookie_name}=")
    ]
    assert session_headers, "session cookie must still be set"
    assert "Path=/web-api/v1/" in session_headers[0]


@pytest.mark.asyncio
async def test_logout_clears_logged_in_marker_cookie(
    client: AsyncClient,
    session_factory: object,
) -> None:
    """T160-T163 P0: logout must clear the Path=/ marker cookie."""
    from echoroo.core.settings import get_settings

    settings = get_settings()
    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    refreshed = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert refreshed.status_code == 200
    csrf = refreshed.headers["X-CSRF-Token"]
    response = await client.post(
        "/web-api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 204
    set_cookie_headers = response.headers.get_list("set-cookie")
    marker_clears = [
        h for h in set_cookie_headers
        if h.startswith(f"{settings.web_logged_in_cookie_name}=")
    ]
    assert marker_clears, (
        f"expected marker cookie to be cleared on logout, got: {set_cookie_headers!r}"
    )
    # Cookie deletion is signalled by an empty value + expired/Max-Age=0.
    cleared = marker_clears[0]
    assert "Path=/" in cleared
    assert (
        'Max-Age=0' in cleared
        or 'max-age=0' in cleared
        or "expires=Thu, 01 Jan 1970" in cleared.lower()
        or "Expires=Thu, 01 Jan 1970" in cleared
    )


@pytest.mark.asyncio
async def test_refresh_with_reused_token_revokes_family_and_returns_401(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1.auth import _decode_web_refresh_token
    from echoroo.core.auth import SqlTokenStore
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    claims = _decode_web_refresh_token(refresh_token)
    first = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert first.status_code == 200
    replay = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert replay.status_code == 401
    assert await SqlTokenStore(session_factory).is_family_revoked(claims.family_id)


@pytest.mark.asyncio
async def test_refresh_with_stale_security_stamp_returns_401(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1.auth import _decode_web_refresh_token
    from echoroo.core.auth import SqlTokenStore
    from echoroo.core.settings import get_settings
    from echoroo.models.user import User

    user = await _create_user(session_factory, security_stamp="a" * 64)
    refresh_token = await _seed_refresh_token(session_factory, user)
    claims = _decode_web_refresh_token(refresh_token)
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        db_user = await session.get(User, user.id)
        assert db_user is not None
        db_user.security_stamp = "b" * 64
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 401
    assert await SqlTokenStore(session_factory).is_family_revoked(claims.family_id)


def _assert_session_cookies_cleared(set_cookie_headers: list[str]) -> None:
    """Helper: assert the response Set-Cookie list deletes session cookies.

    ``Response.delete_cookie`` produces ``Set-Cookie: <name>="";`` with
    ``Max-Age=0`` and an ``Expires`` in the past. We accept either form.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()
    expected_names = (
        settings.web_logged_in_cookie_name,
        settings.web_session_cookie_name,
        settings.web_csrf_cookie_name,
        settings.web_refresh_cookie_name,
    )
    for name in expected_names:
        matching = [h for h in set_cookie_headers if h.startswith(f"{name}=")]
        assert matching, (
            f"expected {name} to be cleared, "
            f"got Set-Cookie headers: {set_cookie_headers!r}"
        )
        cleared = matching[0].lower()
        assert (
            "max-age=0" in cleared
            or "expires=thu, 01 jan 1970" in cleared
            or 'expires=thu, 01-jan-1970' in cleared
        ), f"expected {name} clear-cookie pattern, got: {matching[0]!r}"


@pytest.mark.asyncio
async def test_refresh_reuse_clears_marker_and_session_cookies(
    client: AsyncClient,
    session_factory: object,
) -> None:
    """T160-T163 round-2 P1: token-reuse 401 must clear all session cookies."""
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    first = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert first.status_code == 200
    replay = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert replay.status_code == 401
    _assert_session_cookies_cleared(replay.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_refresh_stale_security_stamp_clears_marker_and_session_cookies(
    client: AsyncClient,
    session_factory: object,
) -> None:
    """T160-T163 round-2 P1: stale security_stamp 401 must clear all cookies."""
    from echoroo.core.settings import get_settings
    from echoroo.models.user import User

    user = await _create_user(session_factory, security_stamp="a" * 64)
    refresh_token = await _seed_refresh_token(session_factory, user)
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        db_user = await session.get(User, user.id)
        assert db_user is not None
        db_user.security_stamp = "b" * 64
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 401
    _assert_session_cookies_cleared(response.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_refresh_against_already_revoked_family_clears_cookies(
    client: AsyncClient,
    session_factory: object,
) -> None:
    """T160-T163 round-2 P1: refresh on revoked family 401 must clear cookies."""
    from echoroo.api.web_v1.auth import _decode_web_refresh_token
    from echoroo.core.auth import SqlTokenStore
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    claims = _decode_web_refresh_token(refresh_token)
    # Pre-revoke the family directly (simulates a prior security event).
    await SqlTokenStore(session_factory).revoke_family(claims.family_id)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 401
    _assert_session_cookies_cleared(response.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_logout_revokes_family_and_clears_cookies(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1.auth import _decode_web_refresh_token
    from echoroo.core.auth import SqlTokenStore
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    claims = _decode_web_refresh_token(refresh_token)
    refreshed = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert refreshed.status_code == 200
    csrf = refreshed.headers["X-CSRF-Token"]
    response = await client.post(
        "/web-api/v1/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 204
    assert await SqlTokenStore(session_factory).is_family_revoked(claims.family_id)
    set_cookie = response.headers.get("set-cookie", "")
    assert get_settings().web_session_cookie_name in set_cookie
    assert get_settings().web_csrf_cookie_name in set_cookie


@pytest.mark.asyncio
async def test_logout_without_csrf_returns_403_and_keeps_family_active(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1.auth import _decode_web_refresh_token
    from echoroo.core.auth import SqlTokenStore
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token = await _seed_refresh_token(session_factory, user)
    claims = _decode_web_refresh_token(refresh_token)
    refreshed = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert refreshed.status_code == 200

    response = await client.post("/web-api/v1/auth/logout")

    assert response.status_code == 403
    assert response.json()["error_code"] == "csrf_failed"
    assert not await SqlTokenStore(session_factory).is_family_revoked(claims.family_id)


@pytest.mark.asyncio
async def test_interim_token_claims_bind_scope_subject_and_ttl(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.core.settings import get_settings

    settings = get_settings()
    setup_user = await _create_user(
        session_factory,
        email="setup@example.com",
        two_factor_enabled=False,
    )
    challenge_user = await _create_user(
        session_factory,
        email="challenge@example.com",
        two_factor_enabled=True,
    )

    setup_response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": "setup@example.com", "password": "correct horse battery staple"},
    )
    challenge_response = await client.post(
        "/web-api/v1/auth/login",
        json={
            "email": "challenge@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert setup_response.status_code == 200
    assert challenge_response.status_code == 200

    def decode_claims(token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            settings.web_session_secret,
            algorithms=[settings.JWT_ALGORITHM],
        )

    setup_claims = decode_claims(setup_response.json()["interim_token"])
    challenge_claims = decode_claims(challenge_response.json()["interim_token"])

    assert setup_claims["type"] == "interim"
    assert setup_claims["scope"] == "2fa_setup"
    assert setup_claims["sub"] == str(setup_user.id)
    assert abs(
        (setup_claims["exp"] - setup_claims["iat"])
        - settings.web_interim_token_ttl_seconds
    ) <= 1
    assert challenge_claims["type"] == "interim"
    assert challenge_claims["scope"] == "2fa_challenge"
    assert challenge_claims["sub"] == str(challenge_user.id)
    assert abs(
        (challenge_claims["exp"] - challenge_claims["iat"])
        - settings.web_interim_token_ttl_seconds
    ) <= 1


@pytest.mark.asyncio
async def test_interim_token_cross_user_replay_is_rejected(
    session_factory: object,
) -> None:
    from fastapi import HTTPException

    from echoroo.api.web_v1.auth import _decode_interim_token, _issue_interim_token

    user_a = await _create_user(session_factory, email="a@example.com")
    user_b = await _create_user(session_factory, email="b@example.com")
    token = _issue_interim_token(user=user_a, scope="2fa_setup")

    decoded = _decode_interim_token(
        token,
        expected_user_id=user_a.id,
        expected_scope="2fa_setup",
    )
    assert decoded["sub"] == str(user_a.id)

    with pytest.raises(HTTPException) as exc_info:
        _decode_interim_token(
            token,
            expected_user_id=user_b.id,
            expected_scope="2fa_setup",
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_register_email_normalization_nfkc_lowercase(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/web-api/v1/auth/register",
        json={
            "email": "ＴＥＳＴ@ＥＸＡＭＰＬＥ.COM",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 201
    assert response.json()["email"] == "test@example.com"
