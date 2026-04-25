"""Integration coverage for first-party auth TOTP endpoints (T150b)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fakeredis.aioredis
import pyotp
import pytest
from httpx import ASGITransport, AsyncClient

from tests.integration.api.web_v1.test_auth import _create_user

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dev extra may be absent locally
    PostgresContainer = None  # type: ignore[assignment,misc]

API_ROOT = Path(__file__).resolve().parents[4]
ALEMBIC_INI = API_ROOT / "alembic.ini"


class _FastBackupHasher:
    def hash(self, code: str) -> str:
        return f"test-hash:{code}"

    def verify(self, hashed: str, code: str) -> bool:
        return hashed == f"test-hash:{code}"


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


@pytest.fixture(name="session_factory")
async def session_factory_fixture(upgraded_db: str) -> AsyncIterator[object]:
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


@pytest.fixture(name="client")
async def client_fixture(
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


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _patch_totp_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.services import two_factor_service as two_factor_module
    from echoroo.services.two_factor_service import TwoFactorService

    async def get_fake_redis() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    async def no_audit(self: TwoFactorService, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(auth_module, "get_redis_connection", get_fake_redis)
    monkeypatch.setattr(two_factor_module.kms, "wrap_dek", lambda plaintext: bytes(plaintext))
    monkeypatch.setattr(two_factor_module.kms, "unwrap_dek", lambda wrapped: bytes(wrapped))
    monkeypatch.setattr(two_factor_module, "_backup_code_hasher", _FastBackupHasher())
    monkeypatch.setattr(TwoFactorService, "_record_audit_event", no_audit)


async def _setup_interim(client: AsyncClient, email: str = "user@example.com") -> str:
    response = await client.post(
        "/web-api/v1/auth/login",
        json={"email": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200
    return str(response.json()["interim_token"])


async def _issue_interim_token_for_user(
    session_factory: object,
    user_id: Any,
    scope: str,
) -> str:
    from echoroo.api.web_v1.auth import _issue_interim_token
    from echoroo.models.user import User

    async with session_factory() as session:  # type: ignore[operator]
        user = await session.get(User, user_id)
        assert user is not None
        return _issue_interim_token(user=user, scope=scope)


async def _enroll_user(
    session_factory: object,
    user_id: Any,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> tuple[str, list[str]]:
    from echoroo.models.user import User
    from echoroo.services import two_factor_service as two_factor_module
    from echoroo.services.two_factor_service import TwoFactorService

    async with session_factory() as session:  # type: ignore[operator]
        user = await session.get(User, user_id)
        assert user is not None
        service = TwoFactorService(session, fake_redis)
        artifacts = await service.begin_enrollment(user)
        backup_codes = await service.confirm_enrollment(
            user,
            artifacts.secret,
            pyotp.TOTP(artifacts.secret).now(),
        )
        assert user.two_factor_secret_encrypted is not None
        secret = two_factor_module._decrypt_totp_secret(user.two_factor_secret_encrypted)
        return secret, backup_codes


@pytest.mark.asyncio
async def test_totp_setup_returns_secret_and_provisioning_uri(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, two_factor_enabled=False)
    interim_token = await _setup_interim(client)

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": interim_token},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["secret"]) == 32
    assert body["provisioning_uri"].startswith("otpauth://totp/")
    assert body["issuer"] == "Echoroo"
    assert body["account_name"] == "user@example.com"
    assert body["next_interim_token"]


@pytest.mark.asyncio
async def test_totp_setup_rejects_2fa_enabled_user_409(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=True)

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_setup"
            )
        },
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_totp_setup_rejects_replay_of_interim_token(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, two_factor_enabled=False)
    interim_token = await _setup_interim(client)

    first = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": interim_token},
    )
    replay = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": interim_token},
    )

    assert first.status_code == 200
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_totp_setup_rejects_stale_security_stamp(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.models.user import User

    user = await _create_user(session_factory, security_stamp="a" * 64)
    interim_token = await _setup_interim(client)
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        db_user = await session.get(User, user.id)
        assert db_user is not None
        db_user.security_stamp = "b" * 64

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": interim_token},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_totp_setup_confirm_enables_2fa_and_issues_session(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.core.settings import get_settings
    from echoroo.models.user import User

    user = await _create_user(session_factory, two_factor_enabled=False)
    setup = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": await _setup_interim(client)},
    )
    assert setup.status_code == 200
    setup_body = setup.json()

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp/confirm",
        json={
            "interim_token": setup_body["next_interim_token"],
            "secret": setup_body["secret"],
            "totp_code": pyotp.TOTP(setup_body["secret"]).now(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["backup_codes"]) == 8
    assert body["access_token"]
    assert body["expires_in"] == get_settings().web_access_token_ttl_seconds
    assert get_settings().web_refresh_cookie_name in response.cookies
    async with session_factory() as session:  # type: ignore[operator]
        db_user = await session.get(User, user.id)
        assert db_user is not None
        assert db_user.two_factor_enabled is True


@pytest.mark.asyncio
async def test_totp_setup_confirm_rejects_wrong_code_401(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, two_factor_enabled=False)
    setup = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": await _setup_interim(client)},
    )
    assert setup.status_code == 200

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp/confirm",
        json={
            "interim_token": setup.json()["next_interim_token"],
            "secret": setup.json()["secret"],
            "totp_code": "000000",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid TOTP code"


@pytest.mark.asyncio
async def test_totp_setup_confirm_rate_limit_429(
    client: AsyncClient,
    session_factory: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.services.two_factor_service import TwoFactorRateLimitedError, TwoFactorService

    await _create_user(session_factory, two_factor_enabled=False)
    setup = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": await _setup_interim(client)},
    )
    assert setup.status_code == 200

    async def rate_limited(self: TwoFactorService, *_args: Any) -> list[str]:
        raise TwoFactorRateLimitedError("limited")

    monkeypatch.setattr(TwoFactorService, "confirm_enrollment", rate_limited)
    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp/confirm",
        json={
            "interim_token": setup.json()["next_interim_token"],
            "secret": setup.json()["secret"],
            "totp_code": pyotp.TOTP(setup.json()["secret"]).now(),
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"


@pytest.mark.asyncio
async def test_2fa_challenge_with_valid_totp_issues_session(
    client: AsyncClient,
    session_factory: object,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory, two_factor_enabled=False)
    secret, _backup_codes = await _enroll_user(session_factory, user.id, fake_redis)
    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_challenge"
            ),
            "method": "totp",
            "code": pyotp.TOTP(secret).now(),
        },
    )

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert get_settings().web_refresh_cookie_name in response.cookies


@pytest.mark.asyncio
async def test_2fa_challenge_with_wrong_totp_returns_401(
    client: AsyncClient,
    session_factory: object,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)

    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_challenge"
            ),
            "method": "totp",
            "code": "000000",
        },
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_2fa_challenge_with_backup_code_consumes_and_issues_session(
    client: AsyncClient,
    session_factory: object,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=False)
    _secret, backup_codes = await _enroll_user(session_factory, user.id, fake_redis)

    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_challenge"
            ),
            "method": "backup_code",
            "code": backup_codes[0],
        },
    )
    replay = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_challenge"
            ),
            "method": "backup_code",
            "code": backup_codes[0],
        },
    )

    assert response.status_code == 200
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_2fa_challenge_rate_limit_429(
    client: AsyncClient,
    session_factory: object,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)

    for _ in range(5):
        response = await client.post(
            "/web-api/v1/auth/2fa/challenge",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory, user.id, "2fa_challenge"
                ),
                "method": "totp",
                "code": "000000",
            },
        )
        assert response.status_code == 401
    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_challenge"
            ),
            "method": "totp",
            "code": "000000",
        },
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "900"


@pytest.mark.asyncio
async def test_2fa_challenge_lockout_after_10_consecutive_failures_returns_423(
    client: AsyncClient,
    session_factory: object,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _enroll_user(session_factory, user.id, fake_redis)

    observed: list[int] = []
    for _ in range(10):
        response = await client.post(
            "/web-api/v1/auth/2fa/challenge",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory, user.id, "2fa_challenge"
                ),
                "method": "totp",
                "code": "000000",
            },
        )
        observed.append(response.status_code)

    assert observed[:5] == [401, 401, 401, 401, 401]
    assert observed[5:9] == [429, 429, 429, 429]
    assert observed[9] == 423


@pytest.mark.asyncio
async def test_2fa_challenge_rejects_2fa_disabled_user_409(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=False)

    response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory, user.id, "2fa_challenge"
            ),
            "method": "totp",
            "code": "000000",
        },
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_interim_token_jti_single_use_replay_rejected(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, two_factor_enabled=False)
    setup = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": await _setup_interim(client)},
    )
    assert setup.status_code == 200
    payload = {
        "interim_token": setup.json()["next_interim_token"],
        "secret": setup.json()["secret"],
        "totp_code": "000000",
    }

    first = await client.post("/web-api/v1/auth/2fa/setup/totp/confirm", json=payload)
    replay = await client.post("/web-api/v1/auth/2fa/setup/totp/confirm", json=payload)

    assert first.status_code == 401
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_interim_token_deleted_user_rejected(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.models.user import User

    user = await _create_user(session_factory, two_factor_enabled=False)
    interim_token = await _setup_interim(client)
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        db_user = await session.get(User, user.id)
        assert db_user is not None
        db_user.deleted_at = datetime.now(UTC)

    response = await client.post(
        "/web-api/v1/auth/2fa/setup/totp",
        json={"interim_token": interim_token},
    )

    assert response.status_code == 401
