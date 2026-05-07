"""Integration coverage for first-party auth WebAuthn endpoints (T150c)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from echoroo.services.webauthn_service import (
    StoredCredential,
    WebAuthnDuplicateCredentialError,
    WebAuthnReplayDetectedError,
)
from tests.integration.api.web_v1.test_auth import _create_user

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
    container = PostgresContainer("pgvector/pgvector:pg16")
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
            for table in ("refresh_tokens", "token_families", "superusers", "users"):
                await session.execute(text(f"DELETE FROM {table}"))
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
    from echoroo.repositories.superuser_credentials import InMemorySuperuserCredentialStore
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
    monkeypatch.setattr(
        auth_module,
        "_superuser_credential_store",
        InMemorySuperuserCredentialStore(),
    )
    auth_module._register_windows.clear()  # noqa: SLF001 - test isolation

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.state.audit_events = audit_events
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="https://testserver",
    ) as test_client:
        test_client.app = app  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def _patch_redis(
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    async def get_fake_redis() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    monkeypatch.setattr(auth_module, "get_redis_connection", get_fake_redis)


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


async def _seed_superuser(session_factory: object, user_id: Any) -> None:
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        await session.execute(
            text("INSERT INTO superusers (user_id, added_at) VALUES (:uid, now())"),
            {"uid": user_id},
        )


def _stored_credential(
    *,
    credential_id: str = "credential-1",
    sign_count: int = 1,
    last_used_at: str | None = None,
) -> StoredCredential:
    return {
        "credential_id": credential_id,
        "public_key": "public-key",
        "sign_count": sign_count,
        "transports": ["usb"],
        "aaguid": "aaguid",
        "name": "YubiKey 5 NFC",
        "registered_at": "2026-01-01T00:00:00Z",
        "last_used_at": last_used_at,
    }


@pytest.mark.asyncio
async def test_webauthn_register_begin_returns_options_with_new_interim_token(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)

    with patch.object(
        auth_module.webauthn_service,
        "begin_registration",
        new=AsyncMock(return_value={"challenge": "abc", "rp": {"id": "example.com"}}),
    ):
        response = await client.post(
            "/web-api/v1/auth/2fa/webauthn/register",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory,
                    user.id,
                    "webauthn_register",
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["options"]["challenge"] == "abc"
    assert body["next_interim_token"]


@pytest.mark.asyncio
async def test_webauthn_register_begin_rejects_non_superuser_403(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=True)

    response = await client.post(
        "/web-api/v1/auth/2fa/webauthn/register",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory,
                user.id,
                "webauthn_register",
            )
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "WebAuthn registration is restricted to superusers"


@pytest.mark.asyncio
async def test_webauthn_register_complete_rejects_non_superuser_403(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=True)

    response = await client.post(
        "/web-api/v1/auth/2fa/webauthn/register",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory,
                user.id,
                "webauthn_register_complete",
            ),
            "credential": {"id": "credential-1"},
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webauthn_register_complete_persists_credential(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)
    stored = _stored_credential()

    with patch.object(
        auth_module.webauthn_service,
        "complete_registration",
        new=AsyncMock(return_value=stored),
    ):
        response = await client.post(
            "/web-api/v1/auth/2fa/webauthn/register",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory,
                    user.id,
                    "webauthn_register_complete",
                ),
                "credential": {"id": "credential-1"},
                "name": "Primary hardware key",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "credential_id": "credential-1",
        "name": "Primary hardware key",
        "registered_at": "2026-01-01T00:00:00Z",
    }
    credentials = await auth_module._superuser_credential_store.get_credentials(user.id)  # noqa: SLF001
    assert credentials[0]["name"] == "Primary hardware key"


@pytest.mark.asyncio
async def test_webauthn_register_complete_duplicate_credential_returns_409(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)

    with patch.object(
        auth_module.webauthn_service,
        "complete_registration",
        new=AsyncMock(side_effect=WebAuthnDuplicateCredentialError()),
    ):
        response = await client.post(
            "/web-api/v1/auth/2fa/webauthn/register",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory,
                    user.id,
                    "webauthn_register_complete",
                ),
                "credential": {"id": "credential-1"},
            },
        )

    assert response.status_code == 409
    assert client.app.state.audit_events[-1]["action"] == (  # type: ignore[attr-defined]
        "auth.webauthn_duplicate_credential_rejected"
    )
    assert client.app.state.audit_events[-1]["actor_user_id"] == user.id  # type: ignore[attr-defined]
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "user_id": str(user.id)
    }


@pytest.mark.asyncio
async def test_webauthn_register_complete_rejects_replay(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)
    interim_token = await _issue_interim_token_for_user(
        session_factory,
        user.id,
        "webauthn_register_complete",
    )

    with patch.object(
        auth_module.webauthn_service,
        "complete_registration",
        new=AsyncMock(return_value=_stored_credential()),
    ):
        first = await client.post(
            "/web-api/v1/auth/2fa/webauthn/register",
            json={"interim_token": interim_token, "credential": {"id": "credential-1"}},
        )
        replay = await client.post(
            "/web-api/v1/auth/2fa/webauthn/register",
            json={"interim_token": interim_token, "credential": {"id": "credential-1"}},
        )

    assert first.status_code == 200
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_webauthn_challenge_begin_returns_options(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)

    with patch.object(
        auth_module.webauthn_service,
        "begin_authentication",
        new=AsyncMock(return_value={"challenge": "auth", "allowCredentials": []}),
    ):
        response = await client.post(
            "/web-api/v1/auth/2fa/webauthn/challenge",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory,
                    user.id,
                    "2fa_challenge",
                )
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["options"]["challenge"] == "auth"
    assert body["next_interim_token"]


@pytest.mark.asyncio
async def test_webauthn_challenge_complete_issues_real_session(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)
    await auth_module._superuser_credential_store.save_credentials(  # noqa: SLF001
        user.id,
        [_stored_credential()],
    )
    updated = _stored_credential(sign_count=2, last_used_at="2026-01-01T00:01:00Z")

    with patch.object(
        auth_module.webauthn_service,
        "complete_authentication",
        new=AsyncMock(return_value=updated),
    ):
        response = await client.post(
            "/web-api/v1/auth/2fa/webauthn/challenge",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory,
                    user.id,
                    "webauthn_challenge_complete",
                ),
                "credential": {"id": "credential-1"},
            },
        )

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert get_settings().web_refresh_cookie_name in response.cookies
    credentials = await auth_module._superuser_credential_store.get_credentials(user.id)  # noqa: SLF001
    assert credentials[0]["sign_count"] == 2
    assert credentials[0]["last_used_at"] == "2026-01-01T00:01:00Z"


@pytest.mark.asyncio
async def test_webauthn_challenge_complete_sign_count_regression_returns_401(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1 import auth as auth_module

    user = await _create_user(session_factory, two_factor_enabled=True)
    await _seed_superuser(session_factory, user.id)
    await auth_module._superuser_credential_store.save_credentials(  # noqa: SLF001
        user.id,
        [_stored_credential()],
    )

    with patch.object(
        auth_module.webauthn_service,
        "complete_authentication",
        new=AsyncMock(side_effect=WebAuthnReplayDetectedError()),
    ):
        response = await client.post(
            "/web-api/v1/auth/2fa/webauthn/challenge",
            json={
                "interim_token": await _issue_interim_token_for_user(
                    session_factory,
                    user.id,
                    "webauthn_challenge_complete",
                ),
                "credential": {"id": "credential-1"},
            },
        )

    assert response.status_code == 401
    assert any(
        event["action"] == "auth.webauthn_replay_detected"
        for event in client.app.state.audit_events  # type: ignore[attr-defined]
    )


@pytest.mark.asyncio
async def test_webauthn_challenge_complete_rejects_non_superuser_403(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=True)

    response = await client.post(
        "/web-api/v1/auth/2fa/webauthn/challenge",
        json={
            "interim_token": await _issue_interim_token_for_user(
                session_factory,
                user.id,
                "webauthn_challenge_complete",
            ),
            "credential": {"id": "credential-1"},
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_webauthn_challenge_jti_collision_with_totp_challenge_rejected(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, two_factor_enabled=False)
    await _seed_superuser(session_factory, user.id)
    interim_token = await _issue_interim_token_for_user(
        session_factory,
        user.id,
        "2fa_challenge",
    )

    totp_response = await client.post(
        "/web-api/v1/auth/2fa/challenge",
        json={"interim_token": interim_token, "method": "totp", "code": "000000"},
    )
    webauthn_response = await client.post(
        "/web-api/v1/auth/2fa/webauthn/challenge",
        json={"interim_token": interim_token},
    )

    assert totp_response.status_code == 409
    assert webauthn_response.status_code == 401
