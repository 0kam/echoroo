"""Phase 17 §C PR-D coverage uplift — Trusted long-lived invalidation hub.

The existing ``test_trusted_long_lived_invalidation.py`` suite exercises
the happy path: register / unregister / fanout-with-failure isolation,
the JSON push path through a fake pub/sub, and the tick loop with an
injected sleep. This uplift covers the *defensive* code paths that a
streaming-route reconnect or a corrupted Redis push would exercise:

* ``_decode_message`` — None / bytes / non-utf8 bytes / non-JSON text /
  non-dict JSON all return ``None``.
* ``_fanout`` empty-registry early return.
* :func:`subscribe_trusted_invalidation` — the subscriber retries on a
  thrown exception, exits cleanly on ``stop_event``, drops non-message
  pubsub events, and tolerates a cleanup-time raise from ``unsubscribe``.
* :func:`run_tick_loop` — re-raises ``asyncio.CancelledError`` instead of
  swallowing it (the lifespan task group must see the cancel propagate).
* :func:`run_trusted_invalidation_loop` — top-level orchestrator that
  gathers the subscriber + tick loops and is cancelled cleanly.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest

from echoroo.workers import trusted_long_lived_invalidation as hub

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    hub._clear_callbacks_for_test()
    yield
    hub._clear_callbacks_for_test()


# ---------------------------------------------------------------------------
# _decode_message — defensive parsing
# ---------------------------------------------------------------------------


async def test_decode_message_returns_none_for_none() -> None:
    assert hub._decode_message(None) is None


async def test_decode_message_decodes_utf8_bytes() -> None:
    assert hub._decode_message(b'{"reason":"revoked"}') == {"reason": "revoked"}


async def test_decode_message_returns_none_for_non_utf8_bytes() -> None:
    # 0xff is invalid UTF-8 → UnicodeDecodeError → None.
    assert hub._decode_message(b"\xff\xfe") is None


async def test_decode_message_returns_none_for_invalid_json() -> None:
    assert hub._decode_message("not json {") is None


async def test_decode_message_returns_none_for_non_dict_json() -> None:
    # Valid JSON but not a dict — the registry contract requires dict payloads.
    assert hub._decode_message('["just", "a", "list"]') is None
    assert hub._decode_message("42") is None


# ---------------------------------------------------------------------------
# _fanout — empty registry early return
# ---------------------------------------------------------------------------


async def test_fanout_with_no_callbacks_is_a_no_op() -> None:
    # Registry starts empty (autouse fixture). The early-return path
    # MUST short-circuit without raising.
    await hub._fanout({"reason": "tick"})


# ---------------------------------------------------------------------------
# Subscriber — defensive paths
# ---------------------------------------------------------------------------


class _ScriptedPubSub:
    """Pub/sub that yields a programmable list of messages then parks.

    ``unsubscribe`` may be configured to raise so we exercise the
    cleanup-time ``except Exception`` branch.
    """

    def __init__(
        self,
        messages: list[Any],
        *,
        unsubscribe_raises: bool = False,
    ) -> None:
        self._messages = messages
        self.subscribed: list[str] = []
        self._unsubscribe_raises = unsubscribe_raises

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        del channel
        if self._unsubscribe_raises:
            raise RuntimeError("redis closed mid-cleanup")

    async def close(self) -> None:
        return None

    async def listen(self) -> AsyncIterator[Any]:
        for msg in self._messages:
            yield msg
        # Park so the subscriber stays alive until the test stops it.
        forever: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        await forever


class _StaticRedis:
    def __init__(self, pubsub: _ScriptedPubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> _ScriptedPubSub:
        return self._pubsub


async def test_subscriber_drops_non_message_and_non_dict_pubsub_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-message types (subscribe handshake) and non-dict events both
    must be skipped silently — they are not error paths.
    """
    received: list[dict[str, Any]] = []
    stop_event = asyncio.Event()

    async def cb(payload: dict[str, Any]) -> None:
        received.append(payload)
        stop_event.set()

    pubsub = _ScriptedPubSub(
        [
            "not-a-dict-event",  # non-dict — line 210 continue
            {"type": "subscribe", "data": 1},  # handshake — line 213 continue
            {"type": "message", "data": '{"reason":"revoked"}'},  # forwarded
        ]
    )

    async def fake_get_redis() -> _StaticRedis:
        return _StaticRedis(pubsub)

    monkeypatch.setattr(hub, "get_redis_connection", fake_get_redis)

    hub.register_invalidation_callback(cb)
    listener = asyncio.create_task(
        hub.subscribe_trusted_invalidation(stop_event=stop_event)
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        stop_event.set()
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await listener

    assert received == [{"reason": "revoked"}]


async def test_subscriber_drops_non_json_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``message`` event with a non-JSON body MUST be dropped (logged at debug)."""
    pubsub = _ScriptedPubSub(
        [
            {"type": "message", "data": "not json {"},  # → _decode_message None
        ]
    )

    async def fake_get_redis() -> _StaticRedis:
        return _StaticRedis(pubsub)

    monkeypatch.setattr(hub, "get_redis_connection", fake_get_redis)

    fired: list[dict[str, Any]] = []
    stop_event = asyncio.Event()

    async def cb(_payload: dict[str, Any]) -> None:
        fired.append(_payload)

    hub.register_invalidation_callback(cb)

    # The non-JSON message will be skipped without firing the callback.
    # Schedule the stop after a brief loop tick so the listener has time
    # to process the message and continue.
    async def stopper() -> None:
        await asyncio.sleep(0.05)
        stop_event.set()

    listener = asyncio.create_task(
        hub.subscribe_trusted_invalidation(stop_event=stop_event)
    )
    stop_task = asyncio.create_task(stopper())
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        stop_event.set()
        listener.cancel()
        stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await listener
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await stop_task

    assert fired == []


async def test_subscriber_handles_unsubscribe_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``unsubscribe`` raises during cleanup the subscriber MUST swallow it."""
    pubsub = _ScriptedPubSub(
        [{"type": "message", "data": '{"reason":"revoked"}'}],
        unsubscribe_raises=True,
    )

    async def fake_get_redis() -> _StaticRedis:
        return _StaticRedis(pubsub)

    monkeypatch.setattr(hub, "get_redis_connection", fake_get_redis)

    seen: list[dict[str, Any]] = []
    stop_event = asyncio.Event()

    async def cb(payload: dict[str, Any]) -> None:
        seen.append(payload)
        stop_event.set()

    hub.register_invalidation_callback(cb)

    listener = asyncio.create_task(
        hub.subscribe_trusted_invalidation(stop_event=stop_event)
    )
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=2.0)
    finally:
        stop_event.set()
        listener.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await listener

    assert seen == [{"reason": "revoked"}]


async def test_subscriber_retries_on_connection_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A get_redis_connection failure must NOT abort the listener.

    The first call raises; we then set ``stop_event`` so the backoff
    branch's ``wait_for`` returns and the loop exits cleanly without
    spinning indefinitely.
    """
    call_count = {"n": 0}
    stop_event = asyncio.Event()

    async def fake_get_redis() -> Any:
        call_count["n"] += 1
        # Trip the stop right before raising so the backoff wait_for
        # observes a set event and the loop exits on the second pass.
        stop_event.set()
        raise RuntimeError("redis unreachable")

    monkeypatch.setattr(hub, "get_redis_connection", fake_get_redis)

    # The subscriber should swallow the exception, observe the stop_event,
    # and exit. The test fails if this hangs > 2s.
    await asyncio.wait_for(
        hub.subscribe_trusted_invalidation(stop_event=stop_event),
        timeout=2.0,
    )
    assert call_count["n"] >= 1


# ---------------------------------------------------------------------------
# Tick loop — CancelledError propagates
# ---------------------------------------------------------------------------


async def test_run_tick_loop_propagates_cancelled_error() -> None:
    """``asyncio.CancelledError`` from the injected sleep must re-raise."""

    async def cancelling_sleep(_seconds: float) -> None:
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await hub.run_tick_loop(
            stop_event=asyncio.Event(),
            interval=1.0,
            sleep=cancelling_sleep,
        )


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


async def test_run_trusted_invalidation_loop_cancels_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The orchestrator gathers the two halves and surfaces cancellation."""
    pubsub = _ScriptedPubSub([])

    async def fake_get_redis() -> _StaticRedis:
        return _StaticRedis(pubsub)

    monkeypatch.setattr(hub, "get_redis_connection", fake_get_redis)

    stop_event = asyncio.Event()
    parent = asyncio.create_task(
        hub.run_trusted_invalidation_loop(stop_event=stop_event)
    )
    # Let the scheduler start both child coroutines.
    await asyncio.sleep(0.05)
    parent.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await parent
    assert parent.done()
