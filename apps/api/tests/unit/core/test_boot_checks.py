"""Unit tests for the startup boot probes (``echoroo.core.boot_checks``).

Covers the four behaviours the W1 boot-validation feature must guarantee:

  1. Probes pass when Redis ping + S3 head_bucket succeed.
  2. A Redis ping timeout raises ``BootCheckError`` with a clear message.
  3. The ``ECHOROO_SKIP_BOOT_CHECKS`` escape hatch skips every probe.
  4. The S3 probe is fatal in staging / production but only logs an ERROR
     (and continues) in development.

The probes are driven directly at the coroutine level; Redis and the S3
client are stubbed so no live infrastructure is required.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest

from echoroo.core import boot_checks
from echoroo.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Reset the cached Settings singleton around every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _FakeRedisOk:
    async def ping(self) -> bool:
        return True


class _FakeRedisHang:
    async def ping(self) -> bool:
        # Sleep longer than the probe timeout so ``asyncio.wait_for`` fires.
        await asyncio.sleep(boot_checks.REDIS_PING_TIMEOUT_S + 5)
        return True


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    """Point ``get_settings`` at a constructed Settings instance."""
    monkeypatch.setattr(boot_checks, "get_settings", lambda: settings)


# Strong dummy secrets (>= 32 chars, none matching a weak default) so that
# constructing a ``Settings`` with ENVIRONMENT="production"/"staging" satisfies
# ``Settings.validate_production_secrets`` (see ``core/settings.py``). The
# invitation-token kid + HMAC key are supplied via env in ``tests/conftest.py``
# and already clear the prod/staging 32-char strength bar, so they are not
# repeated here.
#
# ``two_factor_reset_confirmation_hmac_key`` declares a ``validation_alias``
# (``TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY``) and the model does NOT enable
# ``populate_by_name``, so it must be passed under its alias — the snake_case
# field name is ignored on init. The other three fields have no alias and are
# accepted under their declared names.
_STRONG_PROD_SECRETS: dict[str, str] = {
    "JWT_SECRET_KEY": "prod-jwt-secret-key-strong-enough-32chars-padding",
    "web_session_secret": "prod-web-session-secret-strong-enough-32chars-pad",
    "S3_SECRET_KEY": "prod-s3-secret-key-strong-enough-32chars-padding",
    "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY": (
        "prod-2fa-reset-confirmation-hmac-strong-32chars-pad"
    ),
}


def _prod_settings(environment: str, **overrides: object) -> Settings:
    """Build a Settings instance that passes the prod/staging secret guards.

    The boot-check probe policy is env-conditional (S3 failures are fatal only
    in staging / production), so these tests must construct ``Settings`` with
    ENVIRONMENT="production"/"staging". That trips
    ``validate_production_secrets``, which requires strong values for every
    prod-enforced secret, so we inject ``_STRONG_PROD_SECRETS`` here.
    """
    return Settings(ENVIRONMENT=environment, **_STRONG_PROD_SECRETS, **overrides)


@pytest.mark.asyncio
async def test_run_boot_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both probes succeeding completes without raising."""
    settings = Settings(ENVIRONMENT="development", ECHOROO_SKIP_BOOT_CHECKS=False)
    _patch_settings(monkeypatch, settings)

    async def _ok_redis() -> _FakeRedisOk:
        return _FakeRedisOk()

    monkeypatch.setattr(boot_checks, "get_redis_connection", _ok_redis)
    monkeypatch.setattr(boot_checks, "_head_bucket_sync", lambda: None)

    await boot_checks.run_boot_checks()


@pytest.mark.asyncio
async def test_redis_timeout_raises_boot_check_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis ping timeout raises BootCheckError with an actionable message."""
    settings = Settings(ENVIRONMENT="development", ECHOROO_SKIP_BOOT_CHECKS=False)
    _patch_settings(monkeypatch, settings)
    # Shorten the timeout so the test is fast.
    monkeypatch.setattr(boot_checks, "REDIS_PING_TIMEOUT_S", 0.05)

    async def _hang_redis() -> _FakeRedisHang:
        return _FakeRedisHang()

    monkeypatch.setattr(boot_checks, "get_redis_connection", _hang_redis)

    with pytest.raises(boot_checks.BootCheckError) as exc_info:
        await boot_checks._probe_redis()
    assert "REDIS_URL" in str(exc_info.value)


@pytest.mark.asyncio
async def test_redis_connection_error_raises_boot_check_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Redis connection failure raises BootCheckError."""
    settings = Settings(ENVIRONMENT="development", ECHOROO_SKIP_BOOT_CHECKS=False)
    _patch_settings(monkeypatch, settings)

    async def _broken_redis() -> Any:
        raise ConnectionError("connection refused")

    monkeypatch.setattr(boot_checks, "get_redis_connection", _broken_redis)

    with pytest.raises(boot_checks.BootCheckError):
        await boot_checks._probe_redis()


@pytest.mark.asyncio
async def test_skip_flag_skips_all_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """ECHOROO_SKIP_BOOT_CHECKS short-circuits before any probe runs."""
    settings = _prod_settings("production", ECHOROO_SKIP_BOOT_CHECKS=True)
    _patch_settings(monkeypatch, settings)

    redis_called = False

    async def _redis() -> _FakeRedisOk:
        nonlocal redis_called
        redis_called = True
        return _FakeRedisOk()

    monkeypatch.setattr(boot_checks, "get_redis_connection", _redis)

    await boot_checks.run_boot_checks()
    assert redis_called is False


@pytest.mark.asyncio
async def test_s3_failure_fatal_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 head_bucket failure is fatal in production."""
    settings = _prod_settings("production", ECHOROO_SKIP_BOOT_CHECKS=False)
    _patch_settings(monkeypatch, settings)

    def _broken_head_bucket() -> None:
        raise OSError("bucket unreachable")

    monkeypatch.setattr(boot_checks, "_head_bucket_sync", _broken_head_bucket)

    with pytest.raises(boot_checks.BootCheckError):
        await boot_checks._probe_s3()


@pytest.mark.asyncio
async def test_s3_failure_non_fatal_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 head_bucket failure only logs an ERROR (no raise) in development."""
    settings = Settings(ENVIRONMENT="development", ECHOROO_SKIP_BOOT_CHECKS=False)
    _patch_settings(monkeypatch, settings)

    def _broken_head_bucket() -> None:
        raise OSError("bucket unreachable")

    monkeypatch.setattr(boot_checks, "_head_bucket_sync", _broken_head_bucket)

    # Must not raise — dev tolerates a missing S3.
    await boot_checks._probe_s3()


@pytest.mark.asyncio
async def test_s3_failure_fatal_in_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S3 head_bucket failure is fatal in staging too."""
    settings = _prod_settings("staging", ECHOROO_SKIP_BOOT_CHECKS=False)
    _patch_settings(monkeypatch, settings)

    def _broken_head_bucket() -> None:
        raise OSError("bucket unreachable")

    monkeypatch.setattr(boot_checks, "_head_bucket_sync", _broken_head_bucket)

    with pytest.raises(boot_checks.BootCheckError):
        await boot_checks._probe_s3()


def test_run_boot_checks_sync_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sync wrapper drives the async probes via asyncio.run."""
    settings = Settings(ENVIRONMENT="development", ECHOROO_SKIP_BOOT_CHECKS=True)
    _patch_settings(monkeypatch, settings)
    # Skip flag set → no live infra needed; the wrapper must complete.
    boot_checks.run_boot_checks_sync()
