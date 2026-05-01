"""TDD coverage for TOTP brute-force protection (FR-054, FR-070).

Phase 4 contract:

* 5 TOTP failures within 15 minutes return ``False`` from
  :meth:`TwoFactorService.verify_totp`. The 6th call within the same
  window raises :class:`TwoFactorRateLimitedError` (the rate-limit gate).
  The wire response in the auth router is HTTP 429.

* 10 *consecutive* failures cross the lockout threshold and raise
  :class:`TwoFactorLockedError`. The wire response is HTTP 423 with
  ``Retry-After`` set to ``TOTP_LOCK_SECONDS`` so the client backs off.

* A successful verification clears both counters (the 15-minute fail
  count and the consecutive-fail counter).

* After the lockout window expires (the Redis key TTL elapses), the
  user can verify again. Tests simulate the TTL expiry by manually
  popping the lock key from the fake-Redis store.

The tests target :class:`TwoFactorService` directly (not the HTTP
endpoint) so we exercise the rate-limit/lockout state machine without
the noise of FastAPI request plumbing. The HTTP-level mapping to 429 /
423 is covered by ``tests/integration/api/web_v1/test_auth_totp.py``.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pyotp
import pytest
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from echoroo.models.user import User
from echoroo.services import two_factor_service as two_factor_module
from echoroo.services.two_factor_service import (
    TOTP_FAIL_LIMIT,
    TOTP_LOCK_THRESHOLD,
    TwoFactorLockedError,
    TwoFactorRateLimitedError,
    TwoFactorService,
)


class _Result:
    def __init__(self, value: Any = None, *, rowcount: int = 1) -> None:
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> Any:
        return self.value


class _FakeSession:
    def __init__(self, user: User) -> None:
        self.user = user
        self.commits = 0

    def add(self, _obj: Any) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, statement: Any, _params: Any = None) -> _Result:
        if isinstance(statement, Select):
            return _Result(self.user)
        if isinstance(statement, Update):
            return _Result(rowcount=1)
        return _Result()


class _FakeRedis:
    """Tiny fake Redis that supports the operations the service needs."""

    def __init__(self) -> None:
        self.values: dict[str, str | int] = {}

    async def incr(self, name: str) -> int:
        value = int(self.values.get(name, 0)) + 1
        self.values[name] = value
        return value

    async def expire(self, name: str, time: int) -> bool:
        return name in self.values and time > 0

    async def get(self, name: str) -> str | int | None:
        return self.values.get(name)

    async def set(
        self,
        name: str,
        value: str | int,
        ex: int | None = None,
    ) -> bool:
        self.values[name] = value
        return ex is None or ex > 0

    async def delete(self, *names: str) -> int:
        deleted = 0
        for name in names:
            if name in self.values:
                deleted += 1
                del self.values[name]
        return deleted


class _FastBackupHasher:
    def hash(self, code: str) -> str:
        return f"test-hash:{code}"

    def verify(self, hashed: str, code: str) -> bool:
        return hashed == f"test-hash:{code}"


@pytest.fixture(autouse=True)
def _patch_kms_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass KMS and audit-log writes — they are unrelated to brute force.

    Without these patches the service would attempt real ``boto3`` /
    Postgres I/O on every verification, which would dominate the test
    runtime and pollute the audit chain in CI.
    """

    async def no_audit(self: TwoFactorService, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        two_factor_module.kms,
        "wrap_dek",
        lambda plaintext: bytes(plaintext),
    )
    monkeypatch.setattr(
        two_factor_module.kms,
        "unwrap_dek",
        lambda wrapped: bytes(wrapped),
    )
    monkeypatch.setattr(TwoFactorService, "_record_audit_event", no_audit)
    monkeypatch.setattr(two_factor_module, "_backup_code_hasher", _FastBackupHasher())


def _user() -> User:
    return User(
        id=uuid4(),
        email="brute@example.com",
        password_hash="hash",
        security_stamp="initial-stamp" + "0" * (64 - len("initial-stamp")),
        two_factor_enabled=False,
    )


async def _confirmed_user() -> tuple[User, TwoFactorService, _FakeRedis, str]:
    """Build a 2FA-enrolled user with a known TOTP secret."""
    user = _user()
    redis = _FakeRedis()
    service = TwoFactorService(_FakeSession(user), redis)  # type: ignore[arg-type]
    artifacts = await service.begin_enrollment(user)
    code = pyotp.TOTP(artifacts.secret).now()
    await service.confirm_enrollment(user, artifacts.secret, code)
    assert user.two_factor_secret_encrypted is not None
    secret = two_factor_module._decrypt_totp_secret(user.two_factor_secret_encrypted)
    return user, service, redis, secret


# ---------------------------------------------------------------------------
# Case (a): 5 failures in 15 minutes → 6th raises rate-limit (HTTP 429)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_five_totp_failures_in_window_then_sixth_raises_rate_limited() -> None:
    user, service, _redis, _secret = await _confirmed_user()

    for attempt in range(TOTP_FAIL_LIMIT):
        result = await service.verify_totp(user, "000000")
        assert result is False, (
            f"failure #{attempt + 1} should return False, not raise"
        )

    # 6th failure crosses the rolling-window threshold.
    with pytest.raises(TwoFactorRateLimitedError):
        await service.verify_totp(user, "000000")


# ---------------------------------------------------------------------------
# Case (b): 10 consecutive failures → lockout (HTTP 423) for 15 minutes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ten_consecutive_totp_failures_trigger_lockout() -> None:
    user, service, redis, _secret = await _confirmed_user()

    # First 5 failures exhaust the rate-limit budget.
    for _ in range(TOTP_FAIL_LIMIT):
        assert await service.verify_totp(user, "000000") is False

    # Failures 6..9 keep raising rate-limited (the consecutive counter
    # advances on each call but the lockout threshold isn't reached yet).
    for _ in range(TOTP_LOCK_THRESHOLD - TOTP_FAIL_LIMIT - 1):
        with pytest.raises(TwoFactorRateLimitedError):
            await service.verify_totp(user, "000000")

    # Failure #10 trips the lockout — service raises the *locked* error
    # (HTTP 423) and persists the lock key in Redis.
    with pytest.raises(TwoFactorLockedError):
        await service.verify_totp(user, "000000")

    assert await redis.get(f"2fa:totp_lock:{user.id}") == "1"


# ---------------------------------------------------------------------------
# Case (c): a successful verify resets both counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_verification_resets_consecutive_counter() -> None:
    user, service, redis, secret = await _confirmed_user()

    # Burn 4 failures (1 below the rate-limit threshold).
    for _ in range(TOTP_FAIL_LIMIT - 1):
        assert await service.verify_totp(user, "000000") is False

    consec_key = f"2fa:totp_consecutive_fail:{user.id}"
    fail_key = f"2fa:totp_fail:{user.id}"
    assert int(redis.values.get(consec_key, 0)) == TOTP_FAIL_LIMIT - 1
    assert int(redis.values.get(fail_key, 0)) == TOTP_FAIL_LIMIT - 1

    # A genuine success clears BOTH counters so the user is back to a
    # fresh budget the moment they recover from a transient device-clock
    # glitch.
    assert await service.verify_totp(user, pyotp.TOTP(secret).now()) is True
    assert consec_key not in redis.values
    assert fail_key not in redis.values

    # And the user can keep failing 5 more times before the rate-limit
    # gate trips again — proving the counter really did reset, not just
    # the consecutive one.
    for _ in range(TOTP_FAIL_LIMIT):
        assert await service.verify_totp(user, "000000") is False
    with pytest.raises(TwoFactorRateLimitedError):
        await service.verify_totp(user, "000000")


# ---------------------------------------------------------------------------
# Case (d): the lockout window is finite — after it expires, verify works again
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lockout_expires_and_user_can_verify_again() -> None:
    user, service, redis, secret = await _confirmed_user()

    # Drive the lockout the same way as (b).
    for _ in range(TOTP_FAIL_LIMIT):
        assert await service.verify_totp(user, "000000") is False
    for _ in range(TOTP_LOCK_THRESHOLD - TOTP_FAIL_LIMIT - 1):
        with pytest.raises(TwoFactorRateLimitedError):
            await service.verify_totp(user, "000000")
    with pytest.raises(TwoFactorLockedError):
        await service.verify_totp(user, "000000")

    # While the lock is active even a *correct* code raises locked — the
    # user is barred from authenticating during the cool-down. This
    # protects against the trivial bypass "wait for the right TOTP
    # window then try again immediately".
    correct_code = pyotp.TOTP(secret).now()
    with pytest.raises(TwoFactorLockedError):
        await service.verify_totp(user, correct_code)

    # Simulate Redis TTL expiry on the lock key. We also clear the
    # consecutive counter to model the natural-time recovery — both keys
    # share the same ``TOTP_LOCK_SECONDS`` TTL so they expire together
    # in production.
    await redis.delete(
        f"2fa:totp_lock:{user.id}",
        f"2fa:totp_consecutive_fail:{user.id}",
        f"2fa:totp_fail:{user.id}",
    )

    # After the window expires the next correct code is accepted —
    # FR-070 requires the lockout to be time-bounded, not permanent.
    assert await service.verify_totp(user, pyotp.TOTP(secret).now()) is True
