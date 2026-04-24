"""Smoke tests for :mod:`echoroo.middleware.rate_limit_buckets` (T074).

The Lua script runs server-side in real Redis. For unit tests we avoid
spinning up a Redis container by simulating the script in Python — we
verify that ``RateLimiter.check`` correctly issues an EVAL command and
parses the response. The token-bucket *math* itself is implemented in
Lua and is exercised by the Phase 3 integration test (which uses the
``testcontainers[redis]`` fixture already in pyproject.toml).
"""

from __future__ import annotations

import math
from typing import Any
from uuid import uuid4

import pytest

from echoroo.middleware.rate_limit_buckets import (
    BucketSpec,
    RateLimiter,
    scope_api_key,
    scope_invitation,
    scope_ip,
    scope_totp,
)


class _SimulatedRedis:
    """Tiny in-memory simulator implementing the same bucket math as the Lua."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, float]] = {}
        self.calls: list[tuple[Any, ...]] = []

    async def execute_command(self, *args: Any) -> list[int]:
        self.calls.append(args)
        assert args[0] == "EVAL"
        # Skip script + numkeys
        key = args[3]
        limit = float(args[4])
        refill_per_sec = float(args[5])
        now_ms = float(args[6])

        bucket = self.store.setdefault(
            key, {"tokens": limit, "last_refill_ms": now_ms}
        )
        elapsed_ms = max(0.0, now_ms - bucket["last_refill_ms"])
        bucket["tokens"] = min(
            limit, bucket["tokens"] + (elapsed_ms / 1000.0) * refill_per_sec
        )
        bucket["last_refill_ms"] = now_ms

        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return [1, int(bucket["tokens"]), 0]
        retry_ms = (
            math.ceil(((1.0 - bucket["tokens"]) / refill_per_sec) * 1000)
            if refill_per_sec > 0
            else 0
        )
        return [0, 0, retry_ms]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_scope_helpers_compose_keys_correctly() -> None:
    """Scope helpers must produce stable, prefix-distinct keys."""
    user = uuid4()
    api_key = uuid4()
    assert scope_totp(user) == f"totp:{user}"
    assert scope_invitation(user) == f"invite:{user}"
    assert scope_api_key(api_key, "vote") == f"apikey:{api_key}:vote"
    assert scope_ip("203.0.113.1") == "ip:203.0.113.1"


@pytest.mark.asyncio
async def test_rate_limit_token_bucket_consumes_tokens() -> None:
    """Sequential calls must consume the bucket and eventually deny."""
    redis = _SimulatedRedis()
    limiter = RateLimiter(redis)
    spec = BucketSpec(limit=2, refill_per_sec=0.0)
    user = uuid4()
    scope = scope_totp(user)

    first = await limiter.check(scope, spec, now_ms=0)
    second = await limiter.check(scope, spec, now_ms=10)
    third = await limiter.check(scope, spec, now_ms=20)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    # First EVAL command went out with the right key prefix.
    assert redis.calls[0][3].startswith("rl:totp:")


@pytest.mark.asyncio
async def test_rate_limit_token_bucket_refills() -> None:
    """After enough time has passed, a new token must be available."""
    redis = _SimulatedRedis()
    limiter = RateLimiter(redis)
    # 1 token, refilling at 1 token/sec.
    spec = BucketSpec(limit=1, refill_per_sec=1.0)
    scope = scope_invitation(uuid4())

    a = await limiter.check(scope, spec, now_ms=0)
    b = await limiter.check(scope, spec, now_ms=100)  # +0.1s -> still empty
    c = await limiter.check(scope, spec, now_ms=2_000)  # +2s -> refilled

    assert a.allowed is True
    assert b.allowed is False
    assert c.allowed is True
