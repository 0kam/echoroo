"""Rate-limit helpers (FR-056).

Rate limiting (FR-056) is implemented in :func:`check_rate_limits` —
50 issues / hour / actor and 200 issues / hour / project. Implementation
uses Redis ``INCR`` + ``EXPIRE`` so concurrent issues from a single
actor cannot race past the window. **Fail-closed**: if Redis is
unreachable :func:`create_invitation` raises so callers cannot bypass
the cap. Production wiring always injects a live client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from .constants import (
    _RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_ACTOR_KEY_PREFIX,
    RATE_LIMIT_ACTOR_PER_HOUR,
    RATE_LIMIT_PROJECT_KEY_PREFIX,
    RATE_LIMIT_PROJECT_PER_HOUR,
)
from .errors import InvitationInfraUnavailableError, InvitationRateLimitError

if TYPE_CHECKING:
    from redis.asyncio import Redis


async def check_rate_limits(
    redis: Redis,
    *,
    actor_user_id: UUID,
    project_id: UUID,
) -> None:
    """Increment + verify the per-actor and per-project rate counters.

    FR-056: Owner/Admin 50/h, project 200/h. Both keys live in Redis with
    a fixed-window TTL; the increment-then-compare pattern ensures the
    counter survives the request even if the caller subsequently aborts
    (worst case: a few "consumed" counts that did not result in a row,
    which is acceptable — over-counting tightens the limit, never loosens).

    **Fail-closed**: callers MUST pass a live :class:`Redis`. A missing or
    unreachable Redis surfaces as :class:`InvitationInfraUnavailableError`
    so the issuer cannot bypass the cap by waiting out an outage.
    """
    actor_key = f"{RATE_LIMIT_ACTOR_KEY_PREFIX}{actor_user_id}"
    project_key = f"{RATE_LIMIT_PROJECT_KEY_PREFIX}{project_id}"

    try:
        actor_count = await redis.incr(actor_key)
        if actor_count == 1:
            await redis.expire(actor_key, _RATE_LIMIT_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation rate limiter (Redis) is unavailable"
        ) from exc
    if actor_count > RATE_LIMIT_ACTOR_PER_HOUR:
        raise InvitationRateLimitError(
            f"actor {actor_user_id} exceeded invitation rate limit "
            f"({RATE_LIMIT_ACTOR_PER_HOUR}/h)"
        )

    try:
        project_count = await redis.incr(project_key)
        if project_count == 1:
            await redis.expire(project_key, _RATE_LIMIT_WINDOW_SECONDS)
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation rate limiter (Redis) is unavailable"
        ) from exc
    if project_count > RATE_LIMIT_PROJECT_PER_HOUR:
        raise InvitationRateLimitError(
            f"project {project_id} exceeded invitation rate limit "
            f"({RATE_LIMIT_PROJECT_PER_HOUR}/h)"
        )
