"""Unit coverage for the Trusted-overlay invalidation hub (T514, NFR-008a).

The hub itself is plumbing — Redis pub/sub on the push path, an
asyncio.sleep-driven tick on the poll path. We exercise the contract
surface that downstream WebSocket / SSE handlers will rely on:

* :func:`register_invalidation_callback` / :func:`unregister_invalidation_callback`
  govern the in-process registry. Idempotent register, silent
  unregister, and exception-isolated fan-out are all asserted.
* :func:`subscribe_trusted_invalidation` decodes JSON messages from the
  Redis channel and forwards them to every registered callback. We
  drive a fake pub/sub stream that yields a synthetic ``message`` and
  then cooperatively stops.
* :func:`run_tick_loop` invokes every callback once per
  :data:`TICK_INTERVAL_SECONDS` boundary using the injected ``sleep``
  hook so the test does not wait on a real wall-clock timer.

The Redis client is monkey-patched at the module-level
``get_redis_connection`` binding so the fake pub/sub stream is the only
code-path the subscriber sees.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from echoroo.workers import trusted_long_lived_invalidation as hub

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Ensure each test starts with an empty callback list."""
    hub._clear_callbacks_for_test()
    yield
    hub._clear_callbacks_for_test()


# ---------------------------------------------------------------------------
# Registry semantics
# ---------------------------------------------------------------------------


async def test_register_callback_is_idempotent() -> None:
    received: list[dict[str, Any]] = []

    async def cb(payload: dict[str, Any]) -> None:
        received.append(payload)

    hub.register_invalidation_callback(cb)
    hub.register_invalidation_callback(cb)  # second call must be a no-op
    assert hub.registered_callback_count() == 1

    await hub._fanout({"reason": "tick"})
    assert received == [{"reason": "tick"}]


async def test_unregister_callback_silently_skips_unknown() -> None:
    async def cb(_payload: dict[str, Any]) -> None:
        return None

    # Not previously registered — must not raise.
    hub.unregister_invalidation_callback(cb)
    assert hub.registered_callback_count() == 0


async def test_fanout_isolates_callback_failures() -> None:
    """A callback that raises must not stop the rest of the fan-out."""
    invocations: list[str] = []

    async def good(_payload: dict[str, Any]) -> None:
        invocations.append("good")

    async def boom(_payload: dict[str, Any]) -> None:
        invocations.append("boom")
        raise RuntimeError("websocket dead")

    async def good_after(_payload: dict[str, Any]) -> None:
        invocations.append("after")

    hub.register_invalidation_callback(good)
    hub.register_invalidation_callback(boom)
    hub.register_invalidation_callback(good_after)

    await hub._fanout({"user_id": "u", "project_id": "p", "reason": "revoked"})
    # All three callbacks ran; the exception from ``boom`` did not abort
    # iteration.
    assert invocations == ["good", "boom", "after"]


# ---------------------------------------------------------------------------
# Subscriber loop — a single push from the Redis channel reaches callbacks
# ---------------------------------------------------------------------------


class _FakePubSub:
    """Minimal pub/sub double matching ``redis.asyncio`` surface used by the hub."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages
        self.subscribed: list[str] = []

    async def subscribe(self, channel: str) -> None:
        self.subscribed.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        # Cooperative shutdown indicator — ignored by tests.
        del channel

    async def close(self) -> None:
        return None

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        # First yield the subscribe confirmation, then each test message.
        yield {"type": "subscribe", "data": 1}
        for msg in self._messages:
            yield msg
        # Park indefinitely so the subscriber keeps waiting until the
        # stop_event is set by the test.
        forever: asyncio.Future[None] = asyncio.get_event_loop().create_future()
        await forever


class _FakeRedis:
    def __init__(self, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub

    def pubsub(self) -> _FakePubSub:
        return self._pubsub


async def test_subscriber_decodes_json_and_fans_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    async def cb(payload: dict[str, Any]) -> None:
        captured.append(payload)
        # Once the message has been forwarded, signal the loop to stop
        # so the test does not block forever inside ``listen``.
        stop_event.set()

    body = json.dumps(
        {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "project_id": "00000000-0000-0000-0000-000000000010",
            "reason": "revoked",
        },
        sort_keys=True,
    )
    fake_pubsub = _FakePubSub([{"type": "message", "data": body}])

    async def fake_get_redis() -> _FakeRedis:
        return _FakeRedis(fake_pubsub)

    monkeypatch.setattr(hub, "get_redis_connection", fake_get_redis)

    hub.register_invalidation_callback(cb)
    stop_event = asyncio.Event()

    # Run the subscriber and a stop-watchdog concurrently so the test
    # cannot hang if the fanout never lands.
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

    assert captured == [
        {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "project_id": "00000000-0000-0000-0000-000000000010",
            "reason": "revoked",
        }
    ]
    assert fake_pubsub.subscribed == [hub.TRUSTED_INVALIDATION_CHANNEL]


# ---------------------------------------------------------------------------
# 5-minute tick — drive the loop with a fake sleep so we do not block
# ---------------------------------------------------------------------------


async def test_tick_loop_invokes_registered_callbacks() -> None:
    received: list[dict[str, Any]] = []
    stop_event = asyncio.Event()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        # After three sleep boundaries, signal the loop to exit. The
        # loop pattern is ``sleep -> stop check -> fanout``, so two
        # fanouts require sleeps to come back twice without the
        # stop_event set on return; we trip it on the third call.
        if len(sleeps) >= 3:
            stop_event.set()

    async def cb(payload: dict[str, Any]) -> None:
        received.append(payload)

    hub.register_invalidation_callback(cb)
    await hub.run_tick_loop(stop_event=stop_event, interval=42.0, sleep=fake_sleep)

    # Two iterations × one callback fired with the synthetic tick payload.
    assert received == [{"reason": "tick"}, {"reason": "tick"}]
    # ``sleep`` was called with the configured interval at least twice
    # (the third call trips the stop_event to break out of the loop).
    assert sleeps[0] == 42.0
    assert sleeps[1] == 42.0
    assert len(sleeps) >= 2
