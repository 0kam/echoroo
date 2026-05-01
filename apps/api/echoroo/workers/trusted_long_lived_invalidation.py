"""Live invalidation hub for long-lived Trusted-overlay sessions (T514, NFR-008a).

Background
----------
WebSocket / SSE / streaming endpoints hold a connection open across many
HTTP requests, so the per-request DB read in
:func:`echoroo.services.trusted_service.get_active_trusted_capabilities`
is bypassed for the duration of the stream. NFR-008a requires that any
revoke / expiry / capability edit takes effect on those long-lived
connections within **5 minutes**.

This module owns the two paths that satisfy that bound:

1. **Push path — Redis pub/sub.** Every mutation in
   :mod:`echoroo.services.trusted_service` (Owner-driven revoke, edit)
   and :mod:`echoroo.workers.trusted_auto_expire` (FR-044 lapse) calls
   :func:`echoroo.services.trusted_service._publish_trusted_invalidation`
   on :data:`echoroo.services.trusted_service.TRUSTED_INVALIDATION_CHANNEL`.
   The subscriber here fans the message out to every callback registered
   via :func:`register_invalidation_callback`. WebSocket / SSE handlers
   register themselves at the start of a connection and unregister on
   disconnect — the callback typically closes the connection so the
   client reconnects with the freshly-rebuilt capability set.

2. **Poll path — 5-minute tick.** Even with the push path in place a
   subscriber could miss a message (Redis client reconnect, message
   redelivery semantics on cluster failover, etc.). The tick task wakes
   every five minutes and calls each registered callback with
   ``reason="tick"`` so streaming handlers can re-evaluate
   ``active_trusted_capabilities`` + ``security_stamp`` on a wall-clock
   schedule. This is the upper-bound safety net referenced in NFR-008a.

Phase 11+ note
--------------
echoroo currently has no WebSocket / SSE endpoints, so no callbacks are
registered out of the box — this module ships as the *infrastructure
seam* the future streaming routes will plug into. Until then the
subscriber loop and the tick task run, see no callbacks, and log a
single startup line that confirms the hub is alive.

Threading model
---------------
The subscriber + tick are *coroutines*, not Celery tasks. They run inside
the FastAPI lifespan task group (``asyncio.create_task`` from
``echoroo.main:lifespan``) so they share the API process's Redis client
pool. The Celery worker process does **not** start them — Celery's
worker model (sync task functions wrapped in :func:`asyncio.run` per
invocation) is unsuitable for a single long-lived listener.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from echoroo.core.redis import get_redis_connection
from echoroo.services.trusted_service import TRUSTED_INVALIDATION_CHANNEL

logger = logging.getLogger(__name__)


#: Cadence for the safety-net poll tick (NFR-008a 5-minute upper bound).
TICK_INTERVAL_SECONDS: int = 5 * 60


#: Type alias for a callback registered by a WebSocket / SSE handler.
#: ``payload`` is the parsed JSON message from the Redis channel for
#: ``push`` invocations, or a synthetic ``{"reason": "tick"}`` dict on
#: each :data:`TICK_INTERVAL_SECONDS` boundary.
InvalidationCallback = Callable[[dict[str, Any]], Awaitable[None]]


# ---------------------------------------------------------------------------
# Callback registry
# ---------------------------------------------------------------------------


#: In-process registry of subscribers. Mutated only from the asyncio
#: event loop, so a plain list is sufficient — no lock needed. Streaming
#: handlers add themselves on connect via
#: :func:`register_invalidation_callback` and remove themselves on
#: disconnect via :func:`unregister_invalidation_callback`.
_CALLBACKS: list[InvalidationCallback] = []


def register_invalidation_callback(callback: InvalidationCallback) -> None:
    """Register ``callback`` to receive Trusted invalidation messages.

    Idempotent: registering the same callable twice is a no-op so a
    handler that re-runs through its connect path (e.g. on reconnect
    inside a single asyncio task) does not duplicate fan-out.
    """
    if callback in _CALLBACKS:
        return
    _CALLBACKS.append(callback)


def unregister_invalidation_callback(callback: InvalidationCallback) -> None:
    """Remove ``callback`` from the registry.

    Silently no-ops if the callback was never registered so disconnect
    cleanup paths do not need to track their own state.
    """
    with contextlib.suppress(ValueError):
        _CALLBACKS.remove(callback)


def registered_callback_count() -> int:
    """Return the number of currently-registered callbacks (test helper)."""
    return len(_CALLBACKS)


def _clear_callbacks_for_test() -> None:
    """Reset the registry — only used by unit tests between cases."""
    _CALLBACKS.clear()


# ---------------------------------------------------------------------------
# Fan-out helpers
# ---------------------------------------------------------------------------


async def _fanout(payload: dict[str, Any]) -> None:
    """Invoke every registered callback with ``payload``.

    Failures from one callback MUST NOT stop the rest from running —
    a misbehaving WebSocket handler should not block invalidation for
    other live streams. We log + swallow exceptions per-callback.
    """
    if not _CALLBACKS:
        return
    # Snapshot the list so a callback that unregisters itself mid-fanout
    # does not break iteration.
    snapshot = list(_CALLBACKS)
    for cb in snapshot:
        try:
            await cb(payload)
        except Exception as exc:  # noqa: BLE001 — best effort; fan-out continues
            logger.warning(
                "trusted invalidation callback %r raised: %r",
                getattr(cb, "__qualname__", repr(cb)),
                exc,
            )


def _decode_message(raw: Any) -> dict[str, Any] | None:
    """Decode a Redis pub/sub message body into a dict, or ``None``.

    The Redis client in :mod:`echoroo.core.redis` is configured with
    ``decode_responses=True`` so the body arrives as :class:`str`. Older
    deployments may still emit :class:`bytes`; we tolerate both shapes.
    """
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = str(raw)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


# ---------------------------------------------------------------------------
# Subscriber loop
# ---------------------------------------------------------------------------


async def subscribe_trusted_invalidation(
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Listen on :data:`TRUSTED_INVALIDATION_CHANNEL` and fan out messages.

    Loops until ``stop_event`` is set (defaults to a never-set sentinel
    so the coroutine runs for the lifetime of the process). Each message
    is decoded with :func:`_decode_message` and forwarded to every
    registered callback. Connection errors are logged + retried with a
    1-second backoff so a Redis blip does not permanently drop the
    listener.
    """
    stop = stop_event or asyncio.Event()
    backoff_seconds: float = 1.0

    while not stop.is_set():
        try:
            client = await get_redis_connection()
            pubsub = client.pubsub()
            await pubsub.subscribe(TRUSTED_INVALIDATION_CHANNEL)
            logger.info(
                "trusted invalidation subscriber active on channel %s",
                TRUSTED_INVALIDATION_CHANNEL,
            )
            try:
                async for message in pubsub.listen():
                    if stop.is_set():
                        break
                    if not isinstance(message, dict):
                        continue
                    if message.get("type") != "message":
                        # Skip "subscribe" / "unsubscribe" handshake events.
                        continue
                    payload = _decode_message(message.get("data"))
                    if payload is None:
                        logger.debug(
                            "trusted invalidation: dropping non-JSON message"
                        )
                        continue
                    await _fanout(payload)
            finally:
                try:
                    await pubsub.unsubscribe(TRUSTED_INVALIDATION_CHANNEL)
                    await pubsub.close()
                except Exception:  # noqa: BLE001 — cleanup is best-effort
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — keep the listener alive
            if stop.is_set():
                break
            logger.warning(
                "trusted invalidation subscriber error %r — retrying in %.1fs",
                exc,
                backoff_seconds,
            )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=backoff_seconds)


# ---------------------------------------------------------------------------
# Tick loop (5-minute safety net)
# ---------------------------------------------------------------------------


async def run_tick_loop(
    *,
    stop_event: asyncio.Event | None = None,
    interval: float = TICK_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Wake every ``interval`` seconds and notify each callback.

    The ``sleep`` parameter is injected so tests can advance time without
    waiting on the wall clock. Each tick fans out a synthetic
    ``{"reason": "tick"}`` payload so handlers do not have to special-case
    the push vs. poll path.
    """
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        try:
            await sleep(interval)
        except asyncio.CancelledError:
            raise
        if stop.is_set():
            break
        await _fanout({"reason": "tick"})


# ---------------------------------------------------------------------------
# Top-level entry point used by FastAPI lifespan
# ---------------------------------------------------------------------------


async def run_trusted_invalidation_loop(
    *,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Start the subscriber + tick loops as concurrent tasks.

    The FastAPI lifespan hook (Phase 11+, when WebSocket / SSE routes
    land) will ``asyncio.create_task(run_trusted_invalidation_loop())``
    once and rely on this coroutine to manage both halves. Cancelling
    the parent task propagates ``CancelledError`` through the gather and
    cleanly tears down both loops.
    """
    stop = stop_event or asyncio.Event()
    await asyncio.gather(
        subscribe_trusted_invalidation(stop_event=stop),
        run_tick_loop(stop_event=stop),
    )


__all__ = [
    "InvalidationCallback",
    "TICK_INTERVAL_SECONDS",
    "register_invalidation_callback",
    "registered_callback_count",
    "run_tick_loop",
    "run_trusted_invalidation_loop",
    "subscribe_trusted_invalidation",
    "unregister_invalidation_callback",
]
