"""Readiness probes backing the ``/health/ready`` endpoint.

The cheap liveness probe (``/health``) stays static so container
orchestrators (k8s / ECS) can hammer it without touching any dependency.
This module backs the *readiness* surface, which verifies the four hard
runtime dependencies — PostgreSQL, Redis, storage, and the local keyring —
each with a short, bounded timeout so a hung dependency cannot wedge the
probe.

Security contract
-----------------

Probe results expose only a component name and ``ok`` / ``fail``. They MUST
NOT leak endpoint URLs, storage paths, credentials, or underlying exception
text (which can echo connection strings). When the keyring is loaded, the
readiness response may additionally expose ``keyring_state``: a 16-hex
digest of selected ids, fingerprints, TOTP versions, and key ids. It exposes
no ids, key material, or paths. All failure detail is written to the server
log; the HTTP response body carries component status only, apart from that
state digest.

Relationship to ``boot_checks``
-------------------------------

``core.boot_checks`` runs *once* at startup and fails the process fast on
missing infrastructure. This module runs *per request* and never raises —
it performs the light storage readiness check so the two surfaces agree on
whether the provisioned tree is usable.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from sqlalchemy import text

from echoroo.core import keyring, storage
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
COMPONENT_STORAGE: Final[str] = "storage"
COMPONENT_KEYRING: Final[str] = "keyring"

_STATUS_OK: Final[str] = "ok"
_STATUS_FAIL: Final[str] = "fail"


class _ReadinessChecks(dict[str, str]):
    """Component statuses with the loaded keyring state for the app route."""

    def __init__(self, values: dict[str, str], *, keyring_state: str | None) -> None:
        super().__init__(values)
        self.keyring_state = keyring_state


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


async def _check_storage() -> bool:
    """Return ``True`` if the light storage readiness check succeeds."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(storage.ensure_ready),
            timeout=READINESS_PROBE_TIMEOUT_S,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
        logger.warning(
            "Readiness probe: storage check failed (%s: %s)",
            exc.__class__.__name__,
            exc,
        )
        return False


async def _check_keyring() -> tuple[bool, str | None]:
    """Return keyring readiness and its non-sensitive loaded state digest."""
    try:
        result = keyring.keyring_status()
    except Exception as exc:  # noqa: BLE001 — any keyring failure means "not ready"
        logger.warning(
            "Readiness probe: keyring check failed (%s)",
            exc.__class__.__name__,
        )
        return False, None

    state = result.get("state")
    return True, state if isinstance(state, str) else None


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
        ``"ok"`` or ``"fail"``; the internal result also carries the loaded
        keyring state digest for the application route.
    """
    factory = session_factory if session_factory is not None else AsyncSessionLocal

    db_ok, redis_ok, storage_ok, keyring_result = await asyncio.gather(
        _check_database(factory),
        _check_redis(),
        _check_storage(),
        _check_keyring(),
    )
    keyring_ok, keyring_state = keyring_result

    checks = _ReadinessChecks(
        {
            COMPONENT_DATABASE: _STATUS_OK if db_ok else _STATUS_FAIL,
            COMPONENT_REDIS: _STATUS_OK if redis_ok else _STATUS_FAIL,
            COMPONENT_STORAGE: _STATUS_OK if storage_ok else _STATUS_FAIL,
            COMPONENT_KEYRING: _STATUS_OK if keyring_ok else _STATUS_FAIL,
        },
        keyring_state=keyring_state if keyring_ok else None,
    )
    return (db_ok and redis_ok and storage_ok and keyring_ok), checks
