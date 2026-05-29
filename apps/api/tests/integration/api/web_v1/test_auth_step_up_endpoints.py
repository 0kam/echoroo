"""Integration tests for step-up begin / complete endpoints (spec/011 T300/T301).

Covers ``POST /web-api/v1/auth/step-up/begin`` and
``POST /web-api/v1/auth/step-up/complete``. The two endpoints together
issue an ``admin_recovery``-scoped step-up JWT (FR-011-206) for the
downstream admin password-reset / 2FA-disable flow.

Test surface
~~~~~~~~~~~~

* T300 begin:
    - Anonymous caller → 401 ``auth_required``.
    - Authenticated user with TOTP enabled → 200 + ``factors_required``
      = ``["password", "totp"]`` + ``challenge_id`` (UUID4).
    - Authenticated user WITHOUT 2FA enrollment → 409
      ``step_up_2fa_not_enrolled``.
    - Re-issuing begin OVERWRITES the previous record so the second
      ``challenge_id`` differs and the first is invalidated.
    - Response headers carry ``Cache-Control: no-store…`` +
      ``Referrer-Policy: no-referrer`` per contract.

* T301 complete:
    - Anonymous caller → 401.
    - Missing / wrong / expired ``challenge_id`` → 401 with the **uniform**
      envelope ``step_up_factor_invalid`` (password-oracle avoidance —
      every credential-shaped failure carries the same error_code +
      message; the internal reason is recorded only on the platform
      audit log).
    - Wrong password → 401 ``step_up_factor_invalid``.
    - Wrong TOTP → 401 ``step_up_factor_invalid``.
    - ``must_change_password=True`` → 423 ``must_change_password``.
    - Malformed (non-UUID4) ``challenge_id`` → 422.
    - Parallel replay of the same ``challenge_id`` → exactly one 200
      and one 401 (GETDEL atomicity guarantee).
    - Happy path → 200, body carries ``step_up_token`` + ``expires_at``
      + ``scope_set=["admin_recovery"]``, response headers carry
      ``Cache-Control: no-store…``, and the issued JWT decodes with
      ``scope=admin_recovery`` + ``factors={password:true, second_factor:totp}``.

Spec refs: FR-011-206, contracts/admin-password-reset.yaml T300/T301.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any
from uuid import UUID

import fakeredis.aioredis
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.auth import router as auth_router
from echoroo.core.database import get_db
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.user import User
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_RECOVERY,
    STEP_UP_TOKEN_TYPE,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str,
    two_factor_enabled: bool = True,
    must_change_password: bool = False,
) -> User:
    """Create a user with a fixed password hash + TOTP enrollment toggle.

    ``password_hash`` is a stable placeholder — the tests monkeypatch
    :func:`echoroo.api.web_v1.auth.verify_password` so the real
    argon2 verifier never runs and any test-supplied plaintext maps to
    a deterministic verdict.
    """
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$step-up-test-placeholder",
        display_name=f"User {email}",
        security_stamp=secrets.token_hex(32),
        two_factor_enabled=two_factor_enabled,
        two_factor_secret_encrypted=(
            b"placeholder-encrypted-totp-secret"
            if two_factor_enabled
            else None
        ),
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    redis: fakeredis.aioredis.FakeRedis = fakeredis.aioredis.FakeRedis(
        decode_responses=True
    )
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest_asyncio.fixture
async def step_up_app(
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    """Minimal FastAPI app with the auth router + step-up dependencies stubbed.

    We patch:
    * ``get_redis_connection`` to return the in-process fakeredis (so
      the challenge store sees the same handle the test asserts on).
    * ``_write_platform_audit`` to a no-op (audit visibility is owned
      by ``test_step_up_required_for_admin_recovery.py`` and the audit
      writer's own coverage; pulling it in here would force every test
      to allocate a fresh AsyncSessionLocal against the production DB).
    * ``verify_password`` to a deterministic stub keyed on a hard-coded
      "correct" plaintext so the M-1 invariant (password verification
      before factor flag set) is testable without the argon2 hasher.
    """
    from echoroo.api.web_v1 import auth as auth_module

    app = FastAPI()
    app.include_router(auth_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db

    async def _fake_redis_factory() -> fakeredis.aioredis.FakeRedis:
        return fake_redis

    monkeypatch.setattr(auth_module, "get_redis_connection", _fake_redis_factory)

    async def _no_audit(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(auth_module, "_write_platform_audit", _no_audit)

    def _stub_verify_password(plain: str, _hashed: str) -> bool:
        # Deterministic stub: only "correct horse battery staple" verifies.
        # Empty / wrong inputs always fail. This lets us cover the M-1
        # invariant without spinning up a real argon2 hasher per test.
        return plain == "correct horse battery staple"

    monkeypatch.setattr(auth_module, "verify_password", _stub_verify_password)

    return app


@pytest_asyncio.fixture
async def step_up_client(step_up_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=step_up_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client


def _override_session_user(app: FastAPI, user: User | None) -> None:
    """Stamp ``user`` (or anonymous) onto :data:`OptionalCurrentUser`.

    Mirrors the pattern from
    ``tests/security/test_step_up_required_for_admin_recovery.py``.
    Passing ``None`` simulates an unauthenticated caller.
    """

    async def _override() -> User | None:
        return user

    app.dependency_overrides[get_current_user_optional] = _override


def _patch_totp_verifier(
    monkeypatch: pytest.MonkeyPatch,
    *,
    accept_code: str | None = "123456",
    raise_exc: BaseException | None = None,
) -> None:
    """Stub ``TwoFactorService.verify_totp`` so we don't decrypt real secrets.

    When ``raise_exc`` is set the verifier raises it (e.g. simulate
    locked / rate-limited). Otherwise the call returns ``True`` only
    when the submitted code matches ``accept_code``.
    """
    from echoroo.services.two_factor_service import TwoFactorService

    async def _stub(
        self: TwoFactorService, user: User, code: str
    ) -> bool:  # noqa: ARG001
        if raise_exc is not None:
            raise raise_exc
        return code == accept_code

    monkeypatch.setattr(TwoFactorService, "verify_totp", _stub)


# ---------------------------------------------------------------------------
# T300 — begin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_up_begin_requires_authentication(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
) -> None:
    """Anonymous caller → 401 ``auth_required`` (no Redis record written)."""
    _override_session_user(step_up_app, None)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/begin",
        json={"scope": "admin_recovery"},
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "auth_required", detail


@pytest.mark.asyncio
async def test_step_up_begin_returns_challenge_id_and_factors(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Happy path: factors_required derived from user's 2FA enrollment."""
    user = await _create_user(
        db_session, email="t300_begin_happy@example.com", two_factor_enabled=True
    )
    _override_session_user(step_up_app, user)

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/begin",
        json={"scope": "admin_recovery"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["factors_required"] == ["password", "totp"]
    # ``challenge_id`` is a UUID4.
    UUID(body["challenge_id"], version=4)

    # Contract-mandated no-store headers.
    assert "no-store" in (response.headers.get("cache-control") or ""), response.headers
    assert response.headers.get("referrer-policy") == "no-referrer", response.headers

    # The record landed under the expected key.
    raw = await fake_redis.get(f"step_up_challenge:{user.id}:admin_recovery")
    assert raw is not None, "challenge record was not persisted"


@pytest.mark.asyncio
async def test_step_up_begin_refuses_when_no_2fa_enrolled(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """User without TOTP cannot satisfy AND-condition → 409 + no record."""
    user = await _create_user(
        db_session,
        email="t300_begin_no_2fa@example.com",
        two_factor_enabled=False,
    )
    _override_session_user(step_up_app, user)

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/begin",
        json={"scope": "admin_recovery"},
    )
    assert response.status_code == 409, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_2fa_not_enrolled", detail


@pytest.mark.asyncio
async def test_step_up_begin_overwrites_previous_challenge(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """Re-issuing begin invalidates the previous slot (challenge_id changes)."""
    user = await _create_user(
        db_session, email="t300_begin_overwrite@example.com"
    )
    _override_session_user(step_up_app, user)

    first = await step_up_client.post(
        "/web-api/v1/auth/step-up/begin", json={"scope": "admin_recovery"}
    )
    second = await step_up_client.post(
        "/web-api/v1/auth/step-up/begin", json={"scope": "admin_recovery"}
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["challenge_id"] != second.json()["challenge_id"]

    # Only the second record is live.
    raw = await fake_redis.get(f"step_up_challenge:{user.id}:admin_recovery")
    assert raw is not None
    import json as _json

    assert _json.loads(raw)["challenge_id"] == second.json()["challenge_id"]


@pytest.mark.asyncio
async def test_step_up_begin_rejects_unknown_scope(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """``scope`` is a Literal; unknown values yield 422 from pydantic."""
    user = await _create_user(db_session, email="t300_begin_bad_scope@example.com")
    _override_session_user(step_up_app, user)

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/begin", json={"scope": "admin_destructive"}
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# T301 — complete
# ---------------------------------------------------------------------------


async def _begin_challenge(
    client: AsyncClient,
) -> str:
    response = await client.post(
        "/web-api/v1/auth/step-up/begin",
        json={"scope": "admin_recovery"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["challenge_id"])


@pytest.mark.asyncio
async def test_step_up_complete_requires_authentication(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
) -> None:
    """Anonymous caller → 401 (no token minted).

    Uses a syntactically valid UUID4 (variant nibble = 8/9/a/b, version
    nibble = 4) so the schema-level validation does not 422 ahead of
    the authentication check.
    """
    _override_session_user(step_up_app, None)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "deadbeef-dead-4eef-bead-beefdeadbeef",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "auth_required", detail


@pytest.mark.asyncio
async def test_step_up_complete_happy_path_issues_admin_recovery_token(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: begin → complete with correct password+TOTP → 200 + JWT."""
    user = await _create_user(
        db_session, email="t301_complete_happy@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    challenge_id = await _begin_challenge(step_up_client)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope_set"] == ["admin_recovery"]
    assert isinstance(body["step_up_token"], str) and body["step_up_token"]
    assert isinstance(body["expires_at"], str) and body["expires_at"]

    # Contract-mandated no-store headers.
    assert "no-store" in (response.headers.get("cache-control") or ""), response.headers
    assert response.headers.get("referrer-policy") == "no-referrer", response.headers

    # Decode the JWT and assert the M-1 invariants are encoded.
    settings = get_settings()
    decoded = jwt.decode(
        body["step_up_token"],
        settings.web_session_secret,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert decoded["type"] == STEP_UP_TOKEN_TYPE
    assert decoded["scope"] == SCOPE_ADMIN_RECOVERY
    assert decoded["sub"] == str(user.id)
    assert decoded["ss"] == user.security_stamp
    assert decoded["factors"] == {"password": True, "second_factor": "totp"}


@pytest.mark.asyncio
async def test_step_up_complete_rejects_wrong_password(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrong password → 401 ``step_up_factor_invalid`` (no token minted).

    Verifies the password-oracle-avoidance unification: a wrong-password
    failure carries the same envelope as a wrong-TOTP / wrong-challenge
    failure so the caller cannot determine which factor was rejected.
    """
    user = await _create_user(
        db_session, email="t301_complete_wrongpw@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    challenge_id = await _begin_challenge(step_up_client)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "wrong password",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_step_up_complete_rejects_wrong_totp(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrong TOTP → 401 ``step_up_factor_invalid`` (no token minted).

    Same envelope as wrong-password and wrong-challenge — see docstring
    on ``test_step_up_complete_rejects_wrong_password``.
    """
    user = await _create_user(
        db_session, email="t301_complete_wrongtotp@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    challenge_id = await _begin_challenge(step_up_client)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "000000",
            },
        },
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_step_up_complete_without_active_challenge_returns_401(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare complete (no preceding begin) → 401 ``step_up_factor_invalid``.

    Collapsed into the unified envelope so a probing caller cannot
    distinguish "challenge expired" from "password wrong".
    """
    user = await _create_user(
        db_session, email="t301_complete_no_begin@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "11111111-1111-4111-8111-111111111111",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_step_up_complete_with_mismatched_challenge_id_returns_401(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Begin issued challenge_id A; complete sends challenge_id B → 401 + record dropped.

    Uses the unified ``step_up_factor_invalid`` envelope (the previous
    ``step_up_challenge_mismatch`` variant leaked which factor failed).
    """
    user = await _create_user(
        db_session, email="t301_complete_mismatch@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    await _begin_challenge(step_up_client)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "22222222-2222-4222-8222-222222222222",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail

    # Defence-in-depth: the record is DROPPED even on mismatch (the
    # GETDEL atomic primitive removes the key before validation runs)
    # so a probing caller cannot brute-force the challenge_id space.
    raw = await fake_redis.get(f"step_up_challenge:{user.id}:admin_recovery")
    assert raw is None


@pytest.mark.asyncio
async def test_step_up_complete_is_single_use(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once consumed the challenge is gone; replay returns ``not_found``."""
    user = await _create_user(
        db_session, email="t301_complete_replay@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    challenge_id = await _begin_challenge(step_up_client)
    first = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert first.status_code == 200

    replay = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert replay.status_code == 401, replay.text
    detail = replay.json().get("detail", {})
    # Uniform envelope — caller cannot distinguish "already consumed"
    # from "wrong credentials".
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_step_up_complete_blocks_must_change_password_user(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user in forced-change cannot mint a step-up token → 423."""
    user = await _create_user(
        db_session,
        email="t301_complete_must_change_pw@example.com",
        must_change_password=True,
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    # Seed a challenge record directly so the test doesn't hit begin
    # (begin would also work, but this isolates the must_change_password
    # branch from the begin success path).
    from echoroo.services.step_up_challenge_service import create_challenge

    challenge_id, _ = await create_challenge(
        fake_redis,
        user_id=user.id,
        scope="admin_recovery",
        factors_required=["password", "totp"],
    )
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 423, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "must_change_password", detail


@pytest.mark.asyncio
async def test_step_up_complete_rejects_malformed_challenge_id(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """``challenge_id`` is a strict UUID4 — non-UUID inputs yield 422.

    Defence in depth: the schema rejects probing values (free-form
    strings, UUID1 / UUID3 / UUID5 timestamps, etc.) before they reach
    the Redis lookup, so an attacker cannot spam the challenge store
    with arbitrary keys to learn timing differences.
    """
    user = await _create_user(
        db_session, email="t301_complete_bad_uuid@example.com"
    )
    _override_session_user(step_up_app, user)

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "not-a-uuid-at-all",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_step_up_complete_parallel_replay_one_wins(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two parallel completes of the same challenge → exactly one 200.

    Pins the Redis ``GETDEL`` atomicity guarantee in
    ``services/step_up_challenge_service.consume_challenge``. Without
    the atomic fetch-and-delete, two parallel completes could both
    observe the record between ``GET`` and ``DELETE`` and both mint a
    privileged step-up JWT — a high-severity privilege escalation in
    the admin recovery surface.

    Implementation note: the in-process fakeredis is single-threaded
    per event-loop tick, but two ``await redis.getdel(key)`` coroutines
    interleaved by ``asyncio.gather`` exercise the same code path the
    production Redis would — the loser of the race observes ``None``
    on the second ``GETDEL`` and falls into the unified 401 envelope.

    If the atomic primitive is reverted to ``GET`` + ``DELETE``, both
    branches will observe the record, both will mint a token, and this
    test will fail with two 200 statuses.
    """
    import asyncio

    user = await _create_user(
        db_session, email="t301_complete_parallel_replay@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    challenge_id = await _begin_challenge(step_up_client)

    body = {
        "challenge_id": challenge_id,
        "factors": {
            "password": "correct horse battery staple",
            "totp_code": "123456",
        },
    }

    first, second = await asyncio.gather(
        step_up_client.post("/web-api/v1/auth/step-up/complete", json=body),
        step_up_client.post("/web-api/v1/auth/step-up/complete", json=body),
    )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 401], (
        f"Expected exactly one 200 and one 401 — got {statuses}. "
        f"first={first.text!r} second={second.text!r}"
    )

    # The loser's 401 carries the unified envelope (challenge_not_found
    # collapsed into ``step_up_factor_invalid``).
    loser = first if first.status_code == 401 else second
    detail = loser.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_step_up_complete_after_ttl_expiry_returns_unified_401(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A challenge older than ``STEP_UP_CHALLENGE_TTL_SECONDS`` is gone.

    The challenge store sets ``EX=300`` on the key. After the TTL
    window elapses the key vanishes and the next complete observes
    ``None`` → the unified ``step_up_factor_invalid`` envelope. This
    test seeds the record directly with a 1-second TTL so we do not
    need to manipulate the event-loop clock; ``asyncio.sleep`` then
    advances real time past the TTL so fakeredis evicts the key.
    """
    import asyncio

    user = await _create_user(
        db_session, email="t301_complete_ttl_boundary@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    from echoroo.services.step_up_challenge_service import create_challenge

    # 1-second TTL so the test does not need to wait the full 5 minutes
    # the production code uses. This still exercises the
    # ``consume_challenge`` → ``getdel returns None`` path.
    challenge_id, _ = await create_challenge(
        fake_redis,
        user_id=user.id,
        scope="admin_recovery",
        factors_required=["password", "totp"],
        ttl_seconds=1,
    )

    # Sleep past the TTL — fakeredis honours the EX window on real
    # wall-clock time. 1.5s gives a comfortable margin for slow CI.
    await asyncio.sleep(1.5)

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 401, response.text
    detail = response.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_step_up_complete_rejects_unknown_factor_keys(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """``factors`` rejects unknown keys (``extra="forbid"`` on the schema)."""
    user = await _create_user(
        db_session, email="t301_complete_extra_keys@example.com"
    )
    _override_session_user(step_up_app, user)

    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "33333333-3333-4333-8333-333333333333",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
                "evil_field": "should not be accepted",
            },
        },
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Unit-level coverage for the Redis helper (defence in depth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_up_challenge_service_consume_rejects_corrupt_record(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A corrupt JSON payload under the key behaves like ``not_found``.

    A future operator running ``redis-cli SET`` by hand (or a botched
    serialisation refactor) should never give the completion handler
    a hand-crafted record. The helper degrades safely.
    """
    from uuid import uuid4

    from echoroo.services.step_up_challenge_service import (
        StepUpChallengeNotFoundError,
        consume_challenge,
    )

    user_id = uuid4()
    await fake_redis.set(
        f"step_up_challenge:{user_id}:admin_recovery",
        "not-json-at-all",
        ex=60,
    )
    with pytest.raises(StepUpChallengeNotFoundError):
        await consume_challenge(
            fake_redis,
            user_id=user_id,
            scope="admin_recovery",
            challenge_id="anything",
        )


@pytest.mark.asyncio
async def test_step_up_challenge_service_consume_rejects_malformed_factors(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """A record missing ``factors_required`` degrades to ``not_found``."""
    import json
    from uuid import uuid4

    from echoroo.services.step_up_challenge_service import (
        StepUpChallengeNotFoundError,
        consume_challenge,
    )

    user_id = uuid4()
    await fake_redis.set(
        f"step_up_challenge:{user_id}:admin_recovery",
        json.dumps({"challenge_id": "abc", "factors_required": "not-a-list"}),
        ex=60,
    )
    with pytest.raises(StepUpChallengeNotFoundError):
        await consume_challenge(
            fake_redis,
            user_id=user_id,
            scope="admin_recovery",
            challenge_id="abc",
        )


@pytest.mark.asyncio
async def test_step_up_challenge_service_create_rejects_empty_factors(
    fake_redis: fakeredis.aioredis.FakeRedis,
) -> None:
    """``create_challenge`` refuses an empty factors_required list."""
    from uuid import uuid4

    from echoroo.services.step_up_challenge_service import create_challenge

    with pytest.raises(ValueError):
        await create_challenge(
            fake_redis,
            user_id=uuid4(),
            scope="admin_recovery",
            factors_required=[],
        )
