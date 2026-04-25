"""End-to-end coverage of the 2FA enforcement chain (T155 polish).

This test boots the *real* :func:`echoroo.main.create_app` against a
throwaway PostgreSQL container so the AuthRouter -> 2FA-enforcement ->
CSRF middleware stack is exercised exactly as it ships in production.

We seed:

* a ``users`` row matching the desired enforcement scenario,
* a ``token_families`` row owned by that user (the cookie-bound session
  identifier exposed to :class:`JwtSessionVerifier`).

Each test then makes a request with that family id set in the session
cookie and asserts the right block code (or pass-through) lands.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dev extra may be absent locally
    PostgresContainer = None  # type: ignore[assignment,misc]

API_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = API_ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    container = PostgresContainer("postgres:16-alpine")
    try:
        container.start()
    except Exception as exc:  # noqa: BLE001 - container runtime varies
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
        # ``platform_audit_log`` is append-only (FR-093 trigger guard);
        # we deliberately leave it alone so the chain stays intact
        # across test runs.
        async with factory() as session, session.begin():
            for table in ("refresh_tokens", "token_families", "users"):
                await session.execute(
                    __import__("sqlalchemy").text(f"DELETE FROM {table}")
                )
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def client(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: object,
) -> AsyncIterator[AsyncClient]:
    """Boot ``create_app`` with the test session factory injected.

    We patch every module reference to :data:`AsyncSessionLocal` that
    the middleware chain reads at construction or at request time.
    """
    # All modules that import AsyncSessionLocal at module scope must be
    # patched; the middleware constructors capture the symbol at
    # create_app() time, so patching has to land BEFORE we call it.
    import echoroo.main as main_module
    import echoroo.middleware.two_factor_enforcement as enforcement_module
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.database import get_db
    from echoroo.main import create_app

    monkeypatch.setattr(main_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(enforcement_module, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(auth_module, "AsyncSessionLocal", session_factory)

    # Stub out KMS so the audit write inside ``_default_audit_writer``
    # does not try to reach AWS during the test. The audit content is
    # not asserted on — we only need it to not raise.
    import echoroo.services.audit_service as audit_module

    def _stub_pii_hash(value: str) -> str:
        return f"h:{value}"[:64].ljust(64, "0")

    def _stub_chain_hash(_prev: str, _canonical: bytes) -> str:
        return "c" * 64

    monkeypatch.setattr(audit_module, "compute_pii_hash", _stub_pii_hash)
    monkeypatch.setattr(audit_module, "compute_audit_chain_hash", _stub_chain_hash)

    async def override_get_db() -> AsyncGenerator[Any, None]:
        async with session_factory() as session:  # type: ignore[operator]
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
    ) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


async def _seed_user_and_session(
    session_factory: object,
    *,
    two_factor_enabled: bool,
    cooldown_until: datetime | None = None,
) -> tuple[uuid.UUID, str, str]:
    """Insert a ``users`` row + a ``token_families`` row owned by it.

    Returns ``(user_id, session_id, access_token)`` — the session id is
    the family UUID (matches what ``_set_session_cookies`` writes in
    production); the access token is a freshly-signed JWT bound to the
    user's security stamp so the AuthRouter accepts the request.
    """
    from sqlalchemy import text

    from echoroo.core.auth import issue_access_token
    from echoroo.core.security import hash_password

    user_id = uuid.uuid4()
    family_id = uuid.uuid4()
    security_stamp = "s" * 64
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        await session.execute(
            text(
                "INSERT INTO users "
                "(id, email, password_hash, display_name, security_stamp, "
                " two_factor_enabled, two_factor_reset_cooldown_until) "
                "VALUES (:id, :email, :password_hash, :display_name, :security_stamp, "
                "        :two_factor_enabled, :cooldown)"
            ),
            {
                "id": user_id,
                "email": f"test+{user_id}@example.com",
                "password_hash": hash_password("correct horse battery staple"),
                "display_name": "Real Chain Test",
                "security_stamp": security_stamp,
                "two_factor_enabled": two_factor_enabled,
                "cooldown": cooldown_until,
            },
        )
        await session.execute(
            text(
                "INSERT INTO token_families (family_id, user_id, created_at) "
                "VALUES (:family_id, :user_id, :created_at)"
            ),
            {
                "family_id": family_id,
                "user_id": user_id,
                "created_at": datetime.now(UTC),
            },
        )
    access_token = issue_access_token(
        user_id=user_id,
        security_stamp=security_stamp,
    )
    return user_id, str(family_id), access_token


def _session_cookie_name() -> str:
    from echoroo.core.settings import get_settings

    return get_settings().web_session_cookie_name


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_user_without_2fa_is_blocked_with_403(
    client: AsyncClient,
    session_factory: object,
) -> None:
    _, session_id, access_token = await _seed_user_and_session(
        session_factory, two_factor_enabled=False
    )
    response = await client.post(
        "/web-api/v1/projects",
        cookies={_session_cookie_name(): session_id},
        headers=_auth_headers(access_token),
    )
    # 2FA enforcement is the layer that owns the 403 response. Anything
    # else (CSRF, validation) would land on a different status code, so
    # asserting both code and detail keeps the test specific.
    assert response.status_code == 403
    body = response.json()
    assert body == {
        "detail": "2FA enrollment required",
        "next_action": "/web-api/v1/auth/2fa/setup/totp",
    }


@pytest.mark.asyncio
async def test_user_with_2fa_passes_through_enforcement(
    client: AsyncClient,
    session_factory: object,
) -> None:
    _, session_id, access_token = await _seed_user_and_session(
        session_factory, two_factor_enabled=True
    )
    response = await client.post(
        "/web-api/v1/projects",
        cookies={_session_cookie_name(): session_id},
        headers=_auth_headers(access_token),
    )
    # 2FA enforcement should NOT block this request. Downstream layers
    # (CSRF rejection because no CSRF token is sent, route-level
    # validation, etc.) may still return 403 — but the body shape will
    # NOT carry the enforcement contract, and the cooldown 423 must
    # not surface either.
    assert response.status_code != 423
    if response.status_code == 403:
        body = response.json()
        # The 2FA-enforcement 403 has both ``detail`` and
        # ``next_action``. Any other 403 (CSRF, etc.) does not.
        assert body.get("next_action") != "/web-api/v1/auth/2fa/setup/totp"
        assert body.get("detail") != "2FA enrollment required"


@pytest.mark.asyncio
async def test_cooldown_user_blocked_with_423_on_protected_post(
    client: AsyncClient,
    session_factory: object,
) -> None:
    cooldown_until = datetime.now(UTC) + timedelta(hours=1)
    _, session_id, access_token = await _seed_user_and_session(
        session_factory,
        two_factor_enabled=True,
        cooldown_until=cooldown_until,
    )
    response = await client.post(
        "/web-api/v1/projects",
        cookies={_session_cookie_name(): session_id},
        headers=_auth_headers(access_token),
    )
    assert response.status_code == 423
    body = response.json()
    assert body["detail"] == "2FA reset cooldown active"
    assert int(response.headers["Retry-After"]) > 0


@pytest.mark.asyncio
async def test_cooldown_user_get_request_not_blocked_by_enforcement(
    client: AsyncClient,
    session_factory: object,
) -> None:
    """``GET /api/v1/projects`` is outside the cooldown pattern set.

    The ``/api/v1/*`` prefix is currently disabled in the auth router
    (Phase 15 swap-in) so the response may surface a 401 from the
    legacy auth dependency. The contract tested here is that the 2FA
    enforcement middleware is NOT what blocks the request — i.e. the
    response code is anything *other than* 423.
    """
    cooldown_until = datetime.now(UTC) + timedelta(hours=1)
    _, session_id, access_token = await _seed_user_and_session(
        session_factory,
        two_factor_enabled=True,
        cooldown_until=cooldown_until,
    )
    response = await client.get(
        "/api/v1/projects",
        cookies={_session_cookie_name(): session_id},
        headers=_auth_headers(access_token),
    )
    assert response.status_code != 423
