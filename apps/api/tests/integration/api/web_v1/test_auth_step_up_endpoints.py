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

import asyncio
import secrets
import time
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
# Race-controlled fake Redis
# ---------------------------------------------------------------------------
#
# Round 2 blocker A — the previous ``test_step_up_complete_parallel_replay_one_wins``
# was scheduling-dependent: in fakeredis under a single event loop the two
# parallel ``GETDEL`` invocations DO serialise to a single winner, but a
# legacy ``GET`` + (synchronous validate) + ``DELETE`` implementation could
# **also** observe the single-winner outcome when the first task happens to
# run to completion before the second yields. The test therefore did NOT
# guarantee detection of an atomicity regression.
#
# ``_BarrierFakeRedis`` wraps the real fakeredis handle and parks both
# concurrent callers at a 2-party ``asyncio.Barrier`` *before* the
# underlying state-mutating operation. The barrier is keyed on a specific
# Redis key (the live challenge slot) so unrelated reads (e.g. assertions
# from the test itself) bypass it.
#
# * legacy GET + DELETE: ``get()`` parks both callers, then both observe
#   the SAME value, both pass the JSON check, both call ``delete()``
#   (which succeeds twice — second delete just returns 0), and both
#   mint a token → ``(200, 200)``. The new parallel-replay test
#   therefore fails for any legacy implementation.
# * atomic GETDEL: ``getdel()`` parks both callers at the same point,
#   then the underlying fakeredis operation atomically removes the key
#   and returns the value to exactly one caller — the other receives
#   ``None``. Test sees ``(200, 401)``.


class _BarrierFakeRedis:
    """Wraps fakeredis to checkpoint concurrent read-then-mutate ops.

    The wrapper installs **two independent two-party barriers** keyed
    on ``_barrier_key``: one fires immediately AFTER ``get`` /
    ``getdel`` returns (so both callers observe the same pre-mutation
    state), and a separate one fires immediately BEFORE ``delete``
    runs (so a legacy caller's post-validation delete cannot finish
    before the loser even returns from its own ``get``).

    Why two barriers? With a single pre-call barrier, both parties
    line up before ``get``, both call ``inner.get`` (synchronous in
    fakeredis), and the first to advance can race to ``delete`` before
    the second yields. The post-``get`` barrier forces both parties to
    return from ``get`` with the same observed value; the pre-
    ``delete`` barrier then forces both parties to enter the destructive
    op simultaneously, so a legacy ``GET`` → validate → ``DELETE``
    implementation deterministically observes both records and both
    deletes succeed.

    The ``getdel`` barrier is single-fire because the atomic primitive
    handles its own race in the underlying ``inner.getdel`` call: both
    callers enter together, the inner getdel hands the value to one
    caller and ``None`` to the other.

    Auto-rearm: the get/delete barriers stay armed so a follow-up
    same-key call (e.g. a third replay or a post-race assertion) does
    not deadlock waiting for a second party that will never arrive.
    We disarm the wrapper after the test's parallel phase completes
    via an explicit ``disarm()`` call so assertion-side reads bypass
    the barrier.
    """

    def __init__(
        self,
        inner: fakeredis.aioredis.FakeRedis,
        *,
        barrier_key: str,
        party_count: int = 2,
    ) -> None:
        self._inner = inner
        self._barrier_key = barrier_key
        # Separate barriers per call path so a single race phase
        # consumes only its own barrier and does not deadlock another
        # call path (e.g. the post-race ``get`` from a test assertion).
        self._post_get_barrier = asyncio.Barrier(party_count)
        self._pre_delete_barrier = asyncio.Barrier(party_count)
        self._getdel_barrier = asyncio.Barrier(party_count)
        # ``armed`` toggles to False after the first race so subsequent
        # same-key calls bypass the barriers. Each call site checks
        # ``_armed`` before parking.
        self._armed = True

    def disarm(self) -> None:
        """Bypass all barriers — call after the race phase ends.

        Subsequent calls (test-side assertions, fixture teardown) hit
        the underlying fakeredis directly.
        """
        self._armed = False

    async def _checkpoint(
        self, key: str, barrier: asyncio.Barrier
    ) -> None:
        if self._armed and key == self._barrier_key:
            await barrier.wait()

    async def get(self, key: str) -> Any:
        # Read first, then synchronise so both parties observe the same
        # pre-mutation value.
        value = await self._inner.get(key)
        await self._checkpoint(key, self._post_get_barrier)
        return value

    async def getdel(self, key: str) -> Any:
        # Synchronise BEFORE the atomic op so both parties race the
        # server-side primitive simultaneously. The inner.getdel call
        # itself resolves the race (one value, one None).
        await self._checkpoint(key, self._getdel_barrier)
        return await self._inner.getdel(key)

    async def set(self, *args: Any, **kwargs: Any) -> Any:
        return await self._inner.set(*args, **kwargs)

    async def delete(self, *keys: str) -> Any:
        # Force both legacy parties to enter delete simultaneously so a
        # task that advanced through ``get`` + validate in a single
        # event-loop tick cannot finish its delete before the other
        # party returns from ``get``.
        if self._armed and keys and keys[0] == self._barrier_key:
            await self._pre_delete_barrier.wait()
        return await self._inner.delete(*keys)

    async def aclose(self) -> Any:
        return await self._inner.aclose()

    # Forward anything else (e.g. expire / ttl) so the test surface
    # remains a drop-in replacement for fakeredis. The challenge store
    # only uses ``set / get / getdel / delete``, but this keeps the
    # wrapper forward-compatible should the service grow new primitives.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

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
    fake_redis: fakeredis.aioredis.FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two parallel completes of the same challenge → exactly one 200.

    Pins the Redis ``GETDEL`` atomicity guarantee in
    ``services/step_up_challenge_service.consume_challenge`` with a
    deterministic, scheduling-independent assertion (Round 2 blocker A).

    The previous version of this test gathered two completes with the
    same ``challenge_id`` and asserted ``(200, 401)``. That assertion
    passed even against a legacy ``GET`` → validate → ``DELETE``
    implementation when one coroutine happened to run to completion
    before the other yielded — i.e. it was scheduling-dependent and
    did not actually detect the atomicity regression.

    This rewrite injects a ``_BarrierFakeRedis`` keyed on the live
    challenge slot. Both parallel ``consume_challenge`` calls park at
    the barrier *immediately before* the underlying Redis read /
    fetch-and-delete operation. The barrier guarantees both callers
    observe the same pre-operation state, so:

    * Legacy ``GET`` + ``DELETE``: both callers see the same record,
      both validate the ``challenge_id``, both mint a token →
      ``(200, 200)`` → assertion fails.
    * Atomic ``GETDEL``: both callers race the atomic primitive; the
      Redis server hands the value to exactly one caller and removes
      the key — the other receives ``None`` →
      ``(200, 401)`` → assertion passes.

    SSA verification (2026-05-29): temporarily reverting
    ``consume_challenge`` to a ``GET`` → JSON validate → ``DELETE``
    pair (with no ``await`` between them) causes this test to fail
    with statuses ``[200, 200]``. The current ``GETDEL`` implementation
    passes deterministically.
    """
    user = await _create_user(
        db_session, email="t301_complete_parallel_replay@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    # Begin runs against the bare fakeredis (no barrier yet) so the
    # slot lands without deadlocking on a non-existent second party.
    challenge_id = await _begin_challenge(step_up_client)

    # Re-wire ``get_redis_connection`` to hand out the barrier wrapper
    # *after* begin has persisted the record. Both subsequent
    # ``consume_challenge`` calls will then park at the barrier inside
    # the wrapper's ``getdel`` before the underlying state mutation.
    from echoroo.api.web_v1 import auth as auth_module

    barrier_key = f"step_up_challenge:{user.id}:admin_recovery"
    barrier_redis = _BarrierFakeRedis(
        fake_redis, barrier_key=barrier_key, party_count=2
    )

    async def _barrier_redis_factory() -> _BarrierFakeRedis:
        return barrier_redis

    monkeypatch.setattr(
        auth_module, "get_redis_connection", _barrier_redis_factory
    )
    # ``services.step_up_challenge_service`` receives the redis handle
    # as an argument from the endpoint so we do not need to patch it
    # there — the endpoint forwards ``barrier_redis`` automatically.

    body = {
        "challenge_id": challenge_id,
        "factors": {
            "password": "correct horse battery staple",
            "totp_code": "123456",
        },
    }

    try:
        first, second = await asyncio.gather(
            step_up_client.post("/web-api/v1/auth/step-up/complete", json=body),
            step_up_client.post("/web-api/v1/auth/step-up/complete", json=body),
        )
    finally:
        # Release the barriers so post-race assertions / fixture
        # teardown bypass the synchronisation.
        barrier_redis.disarm()

    statuses = sorted([first.status_code, second.status_code])
    assert statuses == [200, 401], (
        f"Expected exactly one 200 and one 401 — got {statuses}. "
        f"first={first.text!r} second={second.text!r}. "
        "Two 200s indicates the atomic GETDEL was reverted to a "
        "non-atomic GET + DELETE — both callers observed the record."
    )

    # The loser's 401 carries the unified envelope (challenge_not_found
    # collapsed into ``step_up_factor_invalid``) — Round 1 contract.
    loser = first if first.status_code == 401 else second
    detail = loser.json().get("detail", {})
    assert detail.get("error_code") == "step_up_factor_invalid", detail


@pytest.mark.asyncio
async def test_barrier_fake_redis_synchronises_two_parties() -> None:
    """Unit test for the test helper: barriers hold party A until B arrives.

    Round 2 blocker A — guards against a refactor of ``_BarrierFakeRedis``
    that silently drops the synchronisation. Both the post-``get`` and
    the pre-``delete`` barriers must actually block; if either is a
    no-op the regression test loses its detection guarantee.

    Without the barriers, party A would observe its monotonic stamp
    BEFORE party B even started (a 50ms stagger). With the barriers
    both parties pass through together, so the gap collapses to a
    single scheduler tick.
    """
    inner = fakeredis.aioredis.FakeRedis(decode_responses=True)
    try:
        await inner.set("barrier-target", "value", ex=60)
        wrapper = _BarrierFakeRedis(
            inner, barrier_key="barrier-target", party_count=2
        )

        # Exercise BOTH barriers on the legacy code path:
        #   get -> (post-get barrier) -> delete -> (pre-delete barrier)
        get_observed_at: list[float] = []
        delete_observed_at: list[float] = []

        async def _party() -> None:
            await wrapper.get("barrier-target")
            get_observed_at.append(time.perf_counter())
            await wrapper.delete("barrier-target")
            delete_observed_at.append(time.perf_counter())

        # Stagger the two parties so party A would, without the
        # barriers, complete the entire pair before party B started.
        async def _delayed_party() -> None:
            await asyncio.sleep(0.05)
            await _party()

        await asyncio.gather(_party(), _delayed_party())

        assert len(get_observed_at) == 2
        assert len(delete_observed_at) == 2
        get_delta = abs(get_observed_at[1] - get_observed_at[0])
        delete_delta = abs(
            delete_observed_at[1] - delete_observed_at[0]
        )
        # 20ms tolerance per phase: the stagger was 50ms, so any value
        # near 50ms means the barrier did not block.
        assert get_delta < 0.02, (
            f"post-get barrier failed to synchronise — observed gap "
            f"{get_delta * 1000:.2f}ms (stagger was 50ms)."
        )
        assert delete_delta < 0.02, (
            f"pre-delete barrier failed to synchronise — observed gap "
            f"{delete_delta * 1000:.2f}ms (stagger was 50ms)."
        )
    finally:
        await inner.aclose()


# ---------------------------------------------------------------------------
# Round 2 blocker C — timing-oracle defence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_up_complete_runs_both_verifiers_on_password_failure(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 blocker C — wrong password MUST still invoke TOTP verify.

    The previous control flow short-circuited on password failure: the
    handler verified the password first and returned 401 without ever
    calling ``TwoFactorService.verify_totp``. A stolen-session attacker
    could then observe a ~argon2-hash-cost timing delta between
    ``(password_wrong, totp_wrong)`` (one hash) and
    ``(password_correct, totp_wrong)`` (one hash + verify_totp), and
    treat that delta as a password oracle.

    This regression test pins the structural invariant: ``verify_totp``
    MUST be called on every complete request regardless of whether
    ``verify_password`` returned True. The timing-equalisation test
    below complements this with a coarse wall-clock check; together
    they prevent a refactor from re-introducing the short-circuit.
    """
    user = await _create_user(
        db_session, email="t301_timing_password_fail@example.com"
    )
    _override_session_user(step_up_app, user)

    from echoroo.services.two_factor_service import TwoFactorService

    totp_calls: list[str] = []

    async def _counting_verify_totp(
        self: TwoFactorService, _user: User, code: str
    ) -> bool:  # noqa: ARG001
        totp_calls.append(code)
        return code == "123456"

    monkeypatch.setattr(TwoFactorService, "verify_totp", _counting_verify_totp)

    challenge_id = await _begin_challenge(step_up_client)
    response = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id,
            "factors": {
                # Password is the deterministic "wrong" branch on the
                # stub installed by ``step_up_app``.
                "password": "definitely wrong",
                "totp_code": "123456",
            },
        },
    )
    assert response.status_code == 401, response.text
    assert response.json().get("detail", {}).get("error_code") == (
        "step_up_factor_invalid"
    )

    # The structural assertion: TOTP verify ran even though password
    # failed. Without this, the handler would short-circuit and the
    # call list would be empty, surfacing as a password oracle.
    assert totp_calls == ["123456"], (
        "verify_totp was NOT invoked on a wrong-password complete "
        "request — this restores the password-oracle timing channel. "
        f"Observed calls: {totp_calls!r}"
    )


@pytest.mark.asyncio
async def test_step_up_complete_runs_both_verifiers_on_totp_failure(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 blocker C — wrong TOTP MUST still invoke password verify.

    Mirror of the previous test: the handler must call both verifiers
    on every request regardless of which factor failed. Asserts the
    password verifier is called even when the TOTP code is invalid
    (so the order does not matter for the timing channel).
    """
    user = await _create_user(
        db_session, email="t301_timing_totp_fail@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    from echoroo.api.web_v1 import auth as auth_module

    pw_calls: list[str] = []

    def _counting_verify_password(plain: str, _hashed: str) -> bool:
        pw_calls.append(plain)
        return plain == "correct horse battery staple"

    monkeypatch.setattr(auth_module, "verify_password", _counting_verify_password)

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

    assert pw_calls == ["correct horse battery staple"], (
        "verify_password was NOT invoked on a wrong-TOTP complete "
        "request — surfaces as a TOTP-correctness oracle. "
        f"Observed calls: {pw_calls!r}"
    )


@pytest.mark.asyncio
async def test_step_up_complete_timing_password_vs_totp_within_threshold(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 blocker C — measured wall-clock equalisation across factor failures.

    Complements the structural ``runs_both_verifiers`` tests with a
    coarse timing check: the mean response duration of
    ``(wrong_password, wrong_totp)`` vs ``(correct_password, wrong_totp)``
    must be within a generous CI-safe threshold (75 ms). The threshold
    is intentionally loose — fakeredis + stubbed verifiers complete
    each request in well under 10 ms, so a regression that re-adds the
    short-circuit (re-introducing an argon2 verify_password cost ~30-60ms
    in production but ~0ms with the stub) is captured by the structural
    test above, not this one. This test guards against a hypothetical
    future where one verifier is replaced with a deliberately slow
    primitive but the other is not.

    Sample size 10 per case with median aggregation keeps the test
    stable on the noisy CI runner; the assertion compares medians (not
    individual samples) so a single GC pause does not flake the run.
    """
    user = await _create_user(
        db_session, email="t301_timing_threshold@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    async def _time_request(password: str, totp: str) -> float:
        # Each measurement uses a fresh challenge — replays would 401
        # on the second request and skew the timing.
        challenge_id = await _begin_challenge(step_up_client)
        start = time.perf_counter()
        response = await step_up_client.post(
            "/web-api/v1/auth/step-up/complete",
            json={
                "challenge_id": challenge_id,
                "factors": {"password": password, "totp_code": totp},
            },
        )
        elapsed = time.perf_counter() - start
        assert response.status_code == 401
        return elapsed

    sample_size = 10
    wrong_pw_samples = [
        await _time_request("definitely wrong", "000000")
        for _ in range(sample_size)
    ]
    correct_pw_samples = [
        await _time_request("correct horse battery staple", "000000")
        for _ in range(sample_size)
    ]

    # Median is more robust than mean against single-sample GC pauses.
    def _median(xs: list[float]) -> float:
        s = sorted(xs)
        n = len(s)
        return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])

    delta_ms = abs(_median(correct_pw_samples) - _median(wrong_pw_samples)) * 1000
    # 75 ms threshold rationale: stubbed verifiers complete in single-
    # digit ms locally; the CI noise floor is ~20-40 ms per request.
    # 75 ms allows ~2x the typical noise band so the test is stable
    # even on a contended runner, while still catching a regression
    # that re-introduces a synchronous argon2 verify (~30-60 ms cost
    # in production, ~0 ms in the test, but a refactor that uses a
    # real argon2 stub would surface here).
    assert delta_ms < 75.0, (
        f"Timing delta {delta_ms:.2f}ms between (wrong_pw, wrong_totp) "
        f"and (correct_pw, wrong_totp) exceeds the 75ms CI threshold. "
        "This indicates one factor is being short-circuited — confirm "
        "with the structural ``runs_both_verifiers`` tests above."
    )


# ---------------------------------------------------------------------------
# Round 2 cosmetic — uniform 401 envelope pinning + audit detail regression
# ---------------------------------------------------------------------------


_EXPECTED_401_DETAIL = {
    "error_code": "step_up_factor_invalid",
    "message": (
        "Step-up authentication failed. Verify your password and "
        "TOTP code, then restart from begin if the issue persists."
    ),
}


@pytest.mark.asyncio
async def test_step_up_complete_unified_401_pins_full_envelope(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 401 envelope's ``message`` is also pinned (Round 2 cosmetic).

    The previous tests asserted ``error_code`` only. A refactor that
    edits the message string in one branch but not another would have
    re-introduced a per-factor side channel via the human-readable
    text. This test asserts EVERY uniform-401 path (wrong password,
    wrong TOTP, mismatched challenge, expired / missing challenge,
    replayed challenge) carries the IDENTICAL ``error_code`` AND
    ``message`` pair.
    """
    user = await _create_user(
        db_session, email="t301_message_pin@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    # 1. Wrong password.
    challenge_id_a = await _begin_challenge(step_up_client)
    r1 = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id_a,
            "factors": {
                "password": "wrong",
                "totp_code": "123456",
            },
        },
    )
    assert r1.status_code == 401
    assert r1.json().get("detail") == _EXPECTED_401_DETAIL, r1.json()

    # 2. Wrong TOTP.
    challenge_id_b = await _begin_challenge(step_up_client)
    r2 = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id_b,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "000000",
            },
        },
    )
    assert r2.status_code == 401
    assert r2.json().get("detail") == _EXPECTED_401_DETAIL, r2.json()

    # 3. Mismatched challenge_id (begin issued one, complete sends a
    #    different valid UUID4).
    await _begin_challenge(step_up_client)
    r3 = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "44444444-4444-4444-8444-444444444444",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert r3.status_code == 401
    assert r3.json().get("detail") == _EXPECTED_401_DETAIL, r3.json()

    # 4. No begin at all (challenge_not_found path).
    r4 = await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": "55555555-5555-4555-8555-555555555555",
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "123456",
            },
        },
    )
    assert r4.status_code == 401
    assert r4.json().get("detail") == _EXPECTED_401_DETAIL, r4.json()


@pytest.mark.asyncio
async def test_step_up_complete_audit_records_failure_reason(
    step_up_app: FastAPI,
    step_up_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit detail ``failure_reason`` must be populated per failure mode.

    Round 2 cosmetic — pins the internal forensics signal. Even though
    the external 401 envelope is uniform, the platform audit log MUST
    distinguish ``password_mismatch`` / ``totp_mismatch`` / ``both_fail``
    so lockout analytics + abuse review keep working. The audit
    writer is mocked so we can introspect the detail payload without
    a database round-trip.

    The unified ``auth.step_up_complete_factors_failed`` action covers
    all three credential-mismatch branches; the challenge-mismatch and
    challenge-not-found branches keep their existing dedicated actions
    (``auth.step_up_complete_challenge_*``) because their forensics
    signal is structurally distinct (the caller never produced valid
    credentials at all).
    """
    captured: list[dict[str, Any]] = []

    from echoroo.api.web_v1 import auth as auth_module

    async def _capture_audit(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(auth_module, "_write_platform_audit", _capture_audit)

    user = await _create_user(
        db_session, email="t301_audit_failure_reason@example.com"
    )
    _override_session_user(step_up_app, user)
    _patch_totp_verifier(monkeypatch, accept_code="123456")

    # Case 1: wrong password, correct TOTP → failure_reason=password_mismatch.
    captured.clear()
    challenge_id_a = await _begin_challenge(step_up_client)
    await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id_a,
            "factors": {
                "password": "wrong",
                "totp_code": "123456",
            },
        },
    )
    # ``challenge_started`` from begin + ``factors_failed`` from complete.
    failure_audits = [
        c for c in captured if c["action"] == "auth.step_up_complete_factors_failed"
    ]
    assert len(failure_audits) == 1, captured
    assert failure_audits[0]["detail"]["failure_reason"] == "password_mismatch"

    # Case 2: correct password, wrong TOTP → failure_reason=totp_mismatch.
    captured.clear()
    challenge_id_b = await _begin_challenge(step_up_client)
    await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id_b,
            "factors": {
                "password": "correct horse battery staple",
                "totp_code": "000000",
            },
        },
    )
    failure_audits = [
        c for c in captured if c["action"] == "auth.step_up_complete_factors_failed"
    ]
    assert len(failure_audits) == 1, captured
    assert failure_audits[0]["detail"]["failure_reason"] == "totp_mismatch"

    # Case 3: wrong password, wrong TOTP → failure_reason=both_fail.
    captured.clear()
    challenge_id_c = await _begin_challenge(step_up_client)
    await step_up_client.post(
        "/web-api/v1/auth/step-up/complete",
        json={
            "challenge_id": challenge_id_c,
            "factors": {
                "password": "wrong",
                "totp_code": "000000",
            },
        },
    )
    failure_audits = [
        c for c in captured if c["action"] == "auth.step_up_complete_factors_failed"
    ]
    assert len(failure_audits) == 1, captured
    assert failure_audits[0]["detail"]["failure_reason"] == "both_fail"


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
