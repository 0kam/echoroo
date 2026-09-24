"""Startup boot probes — fail fast on missing critical infrastructure.

The application historically deferred all infrastructure validation to the
first request that touched a dependency, surfacing a missing / misconfigured
Redis or storage as a confusing generic 500 deep inside a user flow. These probes
move that failure to boot time so a misconfigured deployment crashes loudly
(in production / staging) or logs a clear ERROR (in development) before it
ever serves traffic.

Probe policy matrix
-------------------

    Probe         Timeout   dev            staging / production
    -----         -------   ------------   ---------------------
    Redis ping    2s        HARD FAIL      HARD FAIL
    Storage ready  5s       log ERROR,     HARD FAIL
                            continue

Redis is required in every environment (rate limiting, sessions, Celery
broker), so a Redis failure is always fatal. Storage in development may be
unavailable while a developer works offline on an unrelated feature, so we log
an ERROR and let the app boot. In staging / production a storage failure is
fatal.

The local keyring is always loaded and validated at boot. It is part of the
application's security boundary, so a missing, invalid, or unprovisioned ring
is fatal in every environment. Loading it also disables process dumpability
before the application can serve traffic.

Escape hatch
------------

Setting ``ECHOROO_SKIP_BOOT_CHECKS=1`` (or any truthy Settings value) skips
all probes and logs a single line saying so. Tests set this via an autouse
fixture so app construction does not require live Redis / storage; integration
tests that exercise the probes themselves unset it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from echoroo.core import keyring, storage
from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings

logger = logging.getLogger(__name__)

# Probe timeouts (seconds).
REDIS_PING_TIMEOUT_S: Final[float] = 2.0
STORAGE_READY_TIMEOUT_S: Final[float] = 5.0

# Environments where a storage probe failure is fatal. Development tolerates a
# missing storage tree (logs ERROR + continues) so offline work is unblocked.
_STORAGE_HARD_FAIL_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"staging", "production"})


class BootCheckError(RuntimeError):
    """Raised when a fatal boot probe fails.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError``
    handlers (and the process-level crash on an unhandled exception during
    lifespan startup) treat it as fatal.
    """


def _probe_keyring() -> None:
    """Load and validate the configured keyring before serving traffic."""
    try:
        keyring.get_keyring()
    except keyring.KeyringError:
        raise BootCheckError(
            "The configured local keyring is unavailable or invalid at boot. "
            "Check the provisioned keyring and KEYRING_* settings."
        ) from None


async def _probe_redis() -> None:
    """Ping Redis with a bounded timeout.

    Raises:
        BootCheckError: when Redis is unreachable or the ping times out.
    """
    try:
        redis = await get_redis_connection()
        await asyncio.wait_for(redis.ping(), timeout=REDIS_PING_TIMEOUT_S)
    except TimeoutError as exc:
        raise BootCheckError(
            f"Redis ping timed out after {REDIS_PING_TIMEOUT_S:g}s. "
            "Check REDIS_URL and that the Redis server is reachable."
        ) from exc
    except Exception as exc:  # noqa: BLE001 — surface any connection error as fatal
        raise BootCheckError(
            "Redis is unreachable at boot. "
            "Check REDIS_URL and that the Redis server is running. "
            f"Underlying error: {exc.__class__.__name__}: {exc}"
        ) from exc


def _ensure_storage_ready_sync() -> None:
    """Run the full synchronous storage readiness probe.

    Storage probing is blocking, so this runs in a worker thread via
    :func:`asyncio.to_thread` inside :func:`_probe_storage`.
    """
    storage.ensure_ready(full=True)


async def _probe_storage() -> None:
    """Check the provisioned storage tree with a bounded timeout.

    Failure handling depends on ``ENVIRONMENT``:

    * staging / production → :class:`BootCheckError` (fatal).
    * development → log an ERROR and return (non-fatal).

    Raises:
        BootCheckError: only in staging / production on probe failure.
    """
    settings = get_settings()
    environment = settings.ENVIRONMENT
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_ensure_storage_ready_sync),
            timeout=STORAGE_READY_TIMEOUT_S,
        )
        return
    except TimeoutError as exc:
        message = (
            f"Storage readiness timed out after {STORAGE_READY_TIMEOUT_S:g}s. "
            "Check STORAGE_ROOT and that the provisioned storage tree is "
            "reachable."
        )
        cause: Exception = exc
    except Exception as exc:  # noqa: BLE001 — any storage / connection error
        message = (
            "The provisioned storage tree is not ready at boot. "
            "Check STORAGE_ROOT, its provisioning marker, and its permissions. "
            f"Underlying error: {exc.__class__.__name__}: {exc}"
        )
        cause = exc

    if environment in _STORAGE_HARD_FAIL_ENVIRONMENTS:
        raise BootCheckError(message) from cause
    logger.error(
        "%s (ENVIRONMENT=%s — continuing because storage boot failures are non-fatal in development)",
        message,
        environment,
    )


async def run_boot_checks() -> None:
    """Run all startup boot probes honouring the skip escape hatch.

    Always probes the keyring and Redis (fatal in every environment). Probes
    storage (fatal only in staging / production). Honours
    ``ECHOROO_SKIP_BOOT_CHECKS``.

    Raises:
        BootCheckError: when a fatal probe fails.
    """
    settings = get_settings()
    if settings.ECHOROO_SKIP_BOOT_CHECKS:
        logger.info(
            "ECHOROO_SKIP_BOOT_CHECKS is set — skipping all boot probes (keyring, Redis, storage)."
        )
        return

    logger.info("Running startup boot probes (keyring, Redis, storage)...")
    _probe_keyring()
    await _probe_redis()
    await _probe_storage()
    logger.info("Startup boot probes passed.")


def run_boot_checks_sync() -> None:
    """Synchronous wrapper around :func:`run_boot_checks`.

    Intended for the Celery ``worker_ready`` signal handler, which runs in a
    synchronous context. Uses :func:`asyncio.run` to drive the async probes
    on a fresh event loop.

    Raises:
        BootCheckError: when a fatal probe fails.
    """
    asyncio.run(run_boot_checks())
