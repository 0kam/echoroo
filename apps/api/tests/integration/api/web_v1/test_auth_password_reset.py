"""Integration coverage for first-party password reset endpoints (T150d)."""

from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

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


@pytest.fixture(name="session_factory")
async def session_factory_fixture(upgraded_db: str) -> AsyncIterator[object]:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(upgraded_db, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session, session.begin():
            for table in (
                "outbox_events",
                "password_reset_tokens",
                "refresh_tokens",
                "token_families",
                "users",
            ):
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
        test_client.app = app  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()


def _encode_token(token: bytes) -> str:
    return base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")


def _hash_token(token: bytes) -> str:
    return hashlib.sha256(token).hexdigest()


async def _create_user(
    session_factory: object,
    *,
    email: str = "user@example.com",
    password: str = "correct horse battery staple",
    security_stamp: str = "s" * 64,
    deleted_at: datetime | None = None,
    cooldown_until: datetime | None = None,
) -> Any:
    from echoroo.core.security import hash_password
    from echoroo.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        display_name="Test User",
        security_stamp=security_stamp,
        two_factor_enabled=True,
        deleted_at=deleted_at,
        two_factor_reset_cooldown_until=cooldown_until,
    )
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        session.add(user)
    return user


async def _create_reset_token(
    session_factory: object,
    *,
    user_id: Any,
    token: bytes = b"a" * 32,
    expires_at: datetime | None = None,
    used_at: datetime | None = None,
) -> str:
    from echoroo.models.password_reset_token import PasswordResetToken

    async with session_factory() as session, session.begin():  # type: ignore[operator]
        session.add(
            PasswordResetToken(
                user_id=user_id,
                token_hash=_hash_token(token),
                expires_at=expires_at or datetime.now(UTC) + timedelta(minutes=10),
                used_at=used_at,
            )
        )
    return _encode_token(token)


@pytest.mark.asyncio
async def test_request_returns_204_for_existing_user_and_enqueues_email(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, email="reset@example.com")

    response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "Reset@Example.com"},
    )

    assert response.status_code == 204
    assert response.content == b""
    async with session_factory() as session:  # type: ignore[operator]
        rows = (
            await session.execute(
                text("SELECT user_id, token_hash FROM password_reset_tokens")
            )
        ).mappings().all()
        events = (
            await session.execute(
                text("SELECT event_type, payload FROM outbox_events")
            )
        ).mappings().all()
    assert len(rows) == 1
    assert rows[0]["user_id"] == user.id
    assert len(rows[0]["token_hash"]) == 64
    assert len(events) == 1
    assert events[0]["event_type"] == "password_reset_email"
    assert events[0]["payload"]["user_id"] == str(user.id)
    assert "/password-reset/confirm?token=" in events[0]["payload"]["reset_url"]
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "email_hash": "hash:reset@example.com"
    }


@pytest.mark.asyncio
async def test_request_returns_204_for_unknown_email_no_enumeration_leak(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, email="known@example.com")

    existing_started = time.perf_counter()
    existing = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "known@example.com"},
    )
    existing_elapsed = time.perf_counter() - existing_started

    unknown_started = time.perf_counter()
    unknown = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "unknown@example.com"},
    )
    unknown_elapsed = time.perf_counter() - unknown_started

    assert existing.status_code == unknown.status_code == 204
    assert existing.content == unknown.content == b""
    assert abs(existing_elapsed - unknown_elapsed) < 0.15
    async with session_factory() as session:  # type: ignore[operator]
        event_count = (
            await session.execute(text("SELECT count(*) FROM outbox_events"))
        ).scalar_one()
    assert event_count == 1


@pytest.mark.asyncio
async def test_request_with_malformed_email_returns_204_no_enumeration_leak(
    client: AsyncClient,
    session_factory: object,
) -> None:
    await _create_user(session_factory, email="known@example.com")

    response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "not-an-email"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "email_validation_failed": True
    }
    async with session_factory() as session:  # type: ignore[operator]
        event_count = (
            await session.execute(text("SELECT count(*) FROM outbox_events"))
        ).scalar_one()
    assert event_count == 0


@pytest.mark.asyncio
async def test_request_during_2fa_reset_cooldown_returns_204_and_audits_block(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(
        session_factory,
        email="cooldown@example.com",
        cooldown_until=datetime.now(UTC) + timedelta(minutes=5),
    )

    response = await client.post(
        "/web-api/v1/auth/password-reset/request",
        json={"email": "cooldown@example.com"},
    )

    assert response.status_code == 204
    assert response.content == b""
    assert client.app.state.audit_events[-1]["action"] == (  # type: ignore[attr-defined]
        "auth.password_reset_blocked_during_cooldown"
    )
    assert client.app.state.audit_events[-1]["actor_user_id"] == user.id  # type: ignore[attr-defined]
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "email_hash": "hash:cooldown@example.com",
        "user_id": str(user.id),
    }
    async with session_factory() as session:  # type: ignore[operator]
        event_count = (
            await session.execute(text("SELECT count(*) FROM outbox_events"))
        ).scalar_one()
    assert event_count == 0


@pytest.mark.asyncio
async def test_confirm_with_valid_token_rotates_password_and_security_stamp(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.core.security import verify_password
    from echoroo.models.user import User

    user = await _create_user(session_factory)
    encoded = await _create_reset_token(session_factory, user_id=user.id)

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "new correct horse battery staple"},
    )

    assert response.status_code == 204
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    async with session_factory() as session:  # type: ignore[operator]
        updated = await session.get(User, user.id)
        assert updated is not None
        used_at = (
            await session.execute(text("SELECT used_at FROM password_reset_tokens"))
        ).scalar_one()
    assert verify_password("new correct horse battery staple", updated.password_hash)
    assert updated.security_stamp != user.security_stamp
    assert used_at is not None


@pytest.mark.asyncio
async def test_confirm_with_expired_token_returns_400_generic(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory)
    encoded = await _create_reset_token(
        session_factory,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "new correct horse battery staple"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"
    assert client.app.state.audit_events[-1]["action"] == (  # type: ignore[attr-defined]
        "auth.password_reset_token_expired"
    )
    assert client.app.state.audit_events[-1]["actor_user_id"] == user.id  # type: ignore[attr-defined]
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "token_hash_prefix": _hash_token(b"a" * 32)[:8],
        "user_id": str(user.id),
    }


@pytest.mark.asyncio
async def test_confirm_with_used_token_returns_400_generic(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory)
    encoded = await _create_reset_token(
        session_factory,
        user_id=user.id,
        used_at=datetime.now(UTC),
    )

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "new correct horse battery staple"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"
    assert client.app.state.audit_events[-1]["action"] == (  # type: ignore[attr-defined]
        "auth.password_reset_token_reuse_attempted"
    )
    assert client.app.state.audit_events[-1]["actor_user_id"] == user.id  # type: ignore[attr-defined]
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "token_hash_prefix": _hash_token(b"a" * 32)[:8],
        "user_id": str(user.id),
    }


@pytest.mark.asyncio
async def test_confirm_with_unknown_token_returns_400_generic(client: AsyncClient) -> None:
    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={
            "token": _encode_token(b"z" * 32),
            "new_password": "new correct horse battery staple",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"
    assert client.app.state.audit_events[-1]["action"] == (  # type: ignore[attr-defined]
        "auth.password_reset_token_invalid"
    )
    assert client.app.state.audit_events[-1]["actor_user_id"] is None  # type: ignore[attr-defined]
    assert client.app.state.audit_events[-1]["detail"] == {  # type: ignore[attr-defined]
        "token_hash_prefix": _hash_token(b"z" * 32)[:8]
    }


@pytest.mark.asyncio
async def test_confirm_rejects_weak_password(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory)
    encoded = await _create_reset_token(session_factory, user_id=user.id)

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "short"},
    )

    assert response.status_code == 422
    assert "at least 8 characters" in response.text


@pytest.mark.asyncio
async def test_confirm_rejects_password_reuse_same_as_current(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory)
    encoded = await _create_reset_token(session_factory, user_id=user.id)

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "correct horse battery staple"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "new password must differ from current password"


@pytest.mark.asyncio
async def test_confirm_rotates_security_stamp_invalidates_existing_refresh_tokens(
    client: AsyncClient,
    session_factory: object,
) -> None:
    from echoroo.api.web_v1.auth import _issue_web_refresh_token
    from echoroo.core.auth import SqlTokenStore
    from echoroo.core.settings import get_settings

    user = await _create_user(session_factory)
    refresh_token, record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    await SqlTokenStore(session_factory).record_issued(record)
    encoded = await _create_reset_token(session_factory, user_id=user.id)

    reset = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "new correct horse battery staple"},
    )
    assert reset.status_code == 204

    client.cookies.set(get_settings().web_refresh_cookie_name, refresh_token)
    refresh = await client.post("/web-api/v1/auth/refresh")

    assert refresh.status_code == 401
    async with session_factory() as session:  # type: ignore[operator]
        revoked_at = (
            await session.execute(
                text("SELECT revoked_at FROM token_families WHERE family_id = :family"),
                {"family": record.family_id},
            )
        ).scalar_one()
    assert revoked_at is not None


@pytest.mark.asyncio
async def test_confirm_does_not_auto_login(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory)
    encoded = await _create_reset_token(session_factory, user_id=user.id)

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "new correct horse battery staple"},
    )

    assert response.status_code == 204
    assert "set-cookie" not in response.headers


@pytest.mark.asyncio
async def test_confirm_for_deleted_user_returns_400_generic(
    client: AsyncClient,
    session_factory: object,
) -> None:
    user = await _create_user(session_factory, deleted_at=datetime.now(UTC))
    encoded = await _create_reset_token(session_factory, user_id=user.id)

    response = await client.post(
        "/web-api/v1/auth/password-reset/confirm",
        json={"token": encoded, "new_password": "new correct horse battery staple"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired reset token"
