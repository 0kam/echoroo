"""Startup boot probes — fail fast on missing critical infrastructure.

The application historically deferred all infrastructure validation to the
first request that touched a dependency, surfacing a missing / misconfigured
Redis or S3 as a confusing generic 500 deep inside a user flow. These probes
move that failure to boot time so a misconfigured deployment crashes loudly
(in production / staging) or logs a clear ERROR (in development) before it
ever serves traffic.

Probe policy matrix
-------------------

    Probe         Timeout   dev            staging / production
    -----         -------   ------------   ---------------------
    Redis ping    2s        HARD FAIL      HARD FAIL
    S3 head_bucket 5s       log ERROR,     HARD FAIL
                            continue

Redis is required in every environment (rate limiting, sessions, Celery
broker), so a Redis failure is always fatal. S3 in development is backed by
LocalStack which should always be reachable; if it is not we log an ERROR but
let the app boot so a developer working offline on a non-S3 feature is not
blocked. In staging / production a missing S3 is fatal.

KMS is deliberately NOT probed at boot — production IAM policies may deny
``kms:DescribeKey`` even when the encrypt / decrypt / GenerateMac grants the
app actually uses are present (see ``core/kms.py``). First-use KMS errors are
surfaced with an actionable message by the wrapper in that module instead.

Escape hatch
------------

Setting ``ECHOROO_SKIP_BOOT_CHECKS=1`` (or any truthy Settings value) skips
all probes and logs a single line saying so. Tests set this via an autouse
fixture so app construction does not require live Redis / S3; integration
tests that exercise the probes themselves unset it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from echoroo.core.redis import get_redis_connection
from echoroo.core.s3 import get_s3_client
from echoroo.core.settings import get_settings

logger = logging.getLogger(__name__)

# Probe timeouts (seconds).
REDIS_PING_TIMEOUT_S: Final[float] = 2.0
S3_HEAD_BUCKET_TIMEOUT_S: Final[float] = 5.0

# Environments where an S3 probe failure is fatal. Development tolerates a
# missing S3 (logs ERROR + continues) so offline / non-S3 work is unblocked.
_S3_HARD_FAIL_ENVIRONMENTS: Final[frozenset[str]] = frozenset({"staging", "production"})


class BootCheckError(RuntimeError):
    """Raised when a fatal boot probe fails.

    Subclasses :class:`RuntimeError` so existing ``except RuntimeError``
    handlers (and the process-level crash on an unhandled exception during
    lifespan startup) treat it as fatal.
    """


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


def _head_bucket_sync() -> None:
    """Synchronous S3 ``head_bucket`` against the configured bucket.

    boto3 is blocking, so this runs in a worker thread via
    :func:`asyncio.to_thread` inside :func:`_probe_s3`.
    """
    settings = get_settings()
    client = get_s3_client()
    client.head_bucket(Bucket=settings.S3_BUCKET)


async def _probe_s3() -> None:
    """Check the configured S3 bucket is reachable with a bounded timeout.

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
            asyncio.to_thread(_head_bucket_sync),
            timeout=S3_HEAD_BUCKET_TIMEOUT_S,
        )
        return
    except TimeoutError as exc:
        message = (
            f"S3 head_bucket timed out after {S3_HEAD_BUCKET_TIMEOUT_S:g}s for "
            f"bucket {settings.S3_BUCKET!r}. Check S3_ENDPOINT_URL / S3_BUCKET "
            "and that the object store is reachable."
        )
        cause: Exception = exc
    except Exception as exc:  # noqa: BLE001 — any boto3 / connection error
        message = (
            f"S3 bucket {settings.S3_BUCKET!r} is not reachable at boot. "
            "Check S3_ENDPOINT_URL, S3_BUCKET, and the S3 credentials. "
            f"Underlying error: {exc.__class__.__name__}: {exc}"
        )
        cause = exc

    if environment in _S3_HARD_FAIL_ENVIRONMENTS:
        raise BootCheckError(message) from cause
    logger.error(
        "%s (ENVIRONMENT=%s — continuing because S3 boot failures are non-fatal in development)",
        message,
        environment,
    )


async def run_boot_checks() -> None:
    """Run all startup boot probes honouring the skip escape hatch.

    Always probes Redis (fatal in every environment). Probes S3
    (fatal only in staging / production). Honours
    ``ECHOROO_SKIP_BOOT_CHECKS``.

    Raises:
        BootCheckError: when a fatal probe fails.
    """
    settings = get_settings()
    if settings.ECHOROO_SKIP_BOOT_CHECKS:
        logger.info("ECHOROO_SKIP_BOOT_CHECKS is set — skipping all boot probes (Redis, S3).")
        return

    logger.info("Running startup boot probes (Redis, S3)...")
    await _probe_redis()
    await _probe_s3()
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
