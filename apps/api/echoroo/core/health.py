"""Readiness probes backing the ``/health/ready`` endpoint.

The cheap liveness probe (``/health``) stays static so container
orchestrators (k8s / ECS) can hammer it without touching any dependency.
This module backs the *readiness* surface, which verifies the three hard
runtime dependencies — PostgreSQL, Redis, and S3 — each with a short,
bounded timeout so a hung dependency cannot wedge the probe.

Security contract
-----------------

Probe results expose only a component name and ``ok`` / ``fail``. They
MUST NOT leak endpoint URLs, bucket names, credentials, or underlying
exception text (which can echo connection strings). All failure detail is
written to the server log; the HTTP response body carries the component
name and status only.

Relationship to ``boot_checks``
-------------------------------

``core.boot_checks`` runs *once* at startup and fails the process fast on
missing infrastructure. This module runs *per request* and never raises —
it reports status. It reuses the S3 ``head_bucket`` helper from
``boot_checks`` so the two surfaces probe the object store identically.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from sqlalchemy import text

from echoroo.core.boot_checks import _head_bucket_sync
from echoroo.core.database import AsyncSessionLocal
from echoroo.core.redis import get_redis_connection

logger = logging.getLogger(__name__)

# Per-probe timeout (seconds). Kept short so the readiness endpoint responds
# quickly even when a dependency is unreachable.
READINESS_PROBE_TIMEOUT_S: Final[float] = 2.0

# Stable component names surfaced in the response body. Chosen to name the
# dependency class only — never the concrete endpoint / host.
COMPONENT_DATABASE: Final[str] = "database"
COMPONENT_REDIS: Final[str] = "redis"
COMPONENT_S3: Final[str] = "s3"

_STATUS_OK: Final[str] = "ok"
_STATUS_FAIL: Final[str] = "fail"


async def _check_database(session_factory: Any) -> bool:
    """Return ``True`` if a ``SELECT 1`` round-trips within the timeout."""
    try:
        async with session_factory() as session:
            await asyncio.wait_for(
                session.execute(text("SELECT 1")),
                timeout=READINESS_PROBE_TIMEOUT_S,
            )
        return True
    except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
        logger.warning(
            "Readiness probe: database check failed (%s: %s)",
            exc.__class__.__name__,
            exc,
        )
        return False


async def _check_redis() -> bool:
    """Return ``True`` if Redis answers ``PING`` within the timeout."""
    try:
        redis = await get_redis_connection()
        await asyncio.wait_for(redis.ping(), timeout=READINESS_PROBE_TIMEOUT_S)
        return True
    except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
        logger.warning(
            "Readiness probe: redis check failed (%s: %s)",
            exc.__class__.__name__,
            exc,
        )
        return False


async def _check_s3() -> bool:
    """Return ``True`` if ``head_bucket`` succeeds within the timeout."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_head_bucket_sync),
            timeout=READINESS_PROBE_TIMEOUT_S,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
        logger.warning(
            "Readiness probe: s3 check failed (%s: %s)",
            exc.__class__.__name__,
            exc,
        )
        return False


async def check_readiness(
    session_factory: Any | None = None,
) -> tuple[bool, dict[str, str]]:
    """Probe all runtime dependencies concurrently.

    Args:
        session_factory: async session factory used for the database probe.
            Defaults to :data:`echoroo.core.database.AsyncSessionLocal`. The
            app injects its configured factory so tests can override it.

    Returns:
        A ``(ready, checks)`` tuple. ``ready`` is ``True`` only when every
        dependency responded. ``checks`` maps each component name to
        ``"ok"`` or ``"fail"`` — no other detail is included.
    """
    factory = session_factory if session_factory is not None else AsyncSessionLocal

    db_ok, redis_ok, s3_ok = await asyncio.gather(
        _check_database(factory),
        _check_redis(),
        _check_s3(),
    )

    checks = {
        COMPONENT_DATABASE: _STATUS_OK if db_ok else _STATUS_FAIL,
        COMPONENT_REDIS: _STATUS_OK if redis_ok else _STATUS_FAIL,
        COMPONENT_S3: _STATUS_OK if s3_ok else _STATUS_FAIL,
    }
    return (db_ok and redis_ok and s3_ok), checks
