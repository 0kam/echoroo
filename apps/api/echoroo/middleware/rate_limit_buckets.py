"""Redis Lua token-bucket rate limiter (FR-054, FR-056, FR-082, T074).

This module supplies :class:`RateLimiter`, a small async helper that
performs an **atomic** token-bucket check against Redis using a Lua
script. The Lua executes server-side (via Redis ``EVAL``) so the
read-modify-write of the bucket state never races between two API
workers.

Bucket scheme:

* Each scope (``totp:<user>``, ``invite:<user>``, ``apikey:<id>``,
  ``ip:<addr>``, ...) maps to a single Redis hash:
  ``rl:<scope>`` with fields ``tokens`` and ``last_refill``.
* On each call we refill ``tokens`` based on
  ``(now - last_refill) * refill_per_sec``, capped at ``limit``.
* If at least one token is available, decrement and return
  ``allowed=True``. Otherwise return ``allowed=False`` and report the
  time until the next token (``retry_after_ms``).

The Lua script returns a 3-tuple ``{allowed, remaining,
retry_after_ms}`` so the Python side can populate response headers
without a second round-trip.

Production-time wiring: callers obtain a :class:`RateLimiter` from
``echoroo.core.redis.get_redis_connection()`` (Phase 3). For unit tests
the limiter accepts any object that implements
:meth:`RedisProtocol.execute_command` matching :class:`RedisProtocol`.

Scope helpers:

* :func:`scope_totp(user_id)` — ``totp:<user_uuid>``. FR-054.
* :func:`scope_invitation(user_id)` — ``invite:<user_uuid>``. FR-056.
* :func:`scope_api_key(api_key_id, category)` —
  ``apikey:<key_uuid>:<read|vote|upload>``. FR-082.
* :func:`scope_ip(ip)` — ``ip:<addr>`` for fallback per-IP buckets.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

# ---------------------------------------------------------------------------
# Lua script (executed server-side by Redis EVAL — not Python eval)
# ---------------------------------------------------------------------------

# KEYS[1]: bucket key (e.g. "rl:totp:<user>")
# ARGV[1]: limit (max tokens)
# ARGV[2]: refill_per_sec (float, encoded as string)
# ARGV[3]: now_ms (current time in milliseconds)
# ARGV[4]: bucket_ttl_ms (how long the bucket lives without traffic)
#
# Returns: { allowed (0/1), remaining_tokens_int, retry_after_ms_int }
TOKEN_BUCKET_LUA: Final[str] = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local refill_per_sec = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local ttl_ms = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "last_refill_ms")
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil or last_refill == nil then
  tokens = limit
  last_refill = now_ms
end

-- Refill based on time elapsed
local elapsed_ms = math.max(0, now_ms - last_refill)
local refill = (elapsed_ms / 1000.0) * refill_per_sec
tokens = math.min(limit, tokens + refill)
last_refill = now_ms

local allowed = 0
local retry_after_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  if refill_per_sec > 0 then
    retry_after_ms = math.ceil(((1 - tokens) / refill_per_sec) * 1000)
  else
    retry_after_ms = ttl_ms
  end
end

redis.call("HMSET", key, "tokens", tokens, "last_refill_ms", last_refill)
redis.call("PEXPIRE", key, ttl_ms)

return { allowed, math.floor(tokens), retry_after_ms }
"""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class RedisProtocol(Protocol):
    """Minimal subset of :class:`redis.asyncio.Redis` used by the limiter.

    We use ``execute_command`` to run the Lua script via the Redis
    ``EVAL`` command. This avoids a name clash with Python's builtin
    ``eval`` and is fully supported by ``redis.asyncio.Redis``.
    """

    def execute_command(
        self,
        *args: Any,
    ) -> Awaitable[Any]: ...


# ---------------------------------------------------------------------------
# Result + scope helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single :meth:`RateLimiter.check` call."""

    allowed: bool
    remaining: int
    retry_after_ms: int


def scope_totp(user_id: UUID) -> str:
    """FR-054: TOTP attempts limited per (IP, user) — caller composes both."""
    return f"totp:{user_id}"


def scope_invitation(user_id: UUID) -> str:
    """FR-056: invitation send / accept rate limit per user."""
    return f"invite:{user_id}"


def scope_api_key(api_key_id: UUID, category: str) -> str:
    """FR-082: API key scope buckets.

    ``category`` is one of ``"read"``, ``"vote"``, ``"upload"``. The
    caller decides the per-category limits (read 600/min, vote 60/min,
    upload 10/min — see plan §Performance).
    """
    return f"apikey:{api_key_id}:{category}"


def scope_ip(ip: str) -> str:
    return f"ip:{ip}"


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BucketSpec:
    """Static description of a token bucket.

    Attributes:
        limit: Maximum tokens the bucket can hold (== burst capacity).
        refill_per_sec: Steady-state refill rate in tokens / second.
            For "60 / minute", pass ``60 / 60.0 == 1.0``.
        ttl_seconds: How long an idle bucket lives in Redis. Should be
            generous enough to span natural quiet periods (e.g. 1h).
    """

    limit: int
    refill_per_sec: float
    ttl_seconds: int = 3600


class RateLimiter:
    """Token-bucket rate limiter against a Redis instance.

    Construction:

        ``RateLimiter(redis)`` accepts any ``redis.asyncio.Redis`` (or
        a stub implementing :class:`RedisProtocol`). The limiter does
        not own the connection — the caller manages lifecycle.

    Usage:

        ``await limiter.check(scope_totp(uid), BucketSpec(10, 10/900.0))``

    Returns :class:`RateLimitResult`. Callers translate ``allowed=False``
    to HTTP 429 with ``Retry-After: ceil(retry_after_ms / 1000)``.
    """

    KEY_PREFIX: Final[str] = "rl:"

    def __init__(self, redis: RedisProtocol) -> None:
        self._redis = redis

    async def check(
        self,
        scope: str,
        spec: BucketSpec,
        *,
        now_ms: int | None = None,
    ) -> RateLimitResult:
        """Atomically consume one token from ``scope``.

        Args:
            scope: Bucket scope. Use the :func:`scope_*` helpers.
            spec: Bucket parameters.
            now_ms: Override clock for tests.
        """
        key = f"{self.KEY_PREFIX}{scope}"
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        ttl_ms = spec.ttl_seconds * 1000
        raw = await self._redis.execute_command(
            "EVAL",
            TOKEN_BUCKET_LUA,
            1,
            key,
            str(spec.limit),
            str(spec.refill_per_sec),
            str(now),
            str(ttl_ms),
        )
        # Redis returns a list of 3 numbers; redis-py decodes them as int.
        allowed_int = int(raw[0])
        remaining = int(raw[1])
        retry_after_ms = int(raw[2])
        return RateLimitResult(
            allowed=allowed_int == 1,
            remaining=remaining,
            retry_after_ms=retry_after_ms,
        )


__all__ = [
    "TOKEN_BUCKET_LUA",
    "BucketSpec",
    "RateLimitResult",
    "RateLimiter",
    "RedisProtocol",
    "scope_api_key",
    "scope_invitation",
    "scope_ip",
    "scope_totp",
]
