"""Step-up challenge state service (spec/011 §FR-011-206, T300/T301).

The ``POST /web-api/v1/auth/step-up/begin`` endpoint mints an opaque
``challenge_id`` and persists a short-lived record that describes the
factors the caller MUST satisfy in the subsequent
``POST /web-api/v1/auth/step-up/complete`` request. The state lives in
Redis so the begin / complete pair scales across multiple API workers
without a sticky session, and so the begin window expires automatically
if the caller never finishes.

State shape
-----------
The record is stored under the key
``step_up_challenge:{user_id}:{scope}`` (one slot per user per scope so
a fresh ``begin`` immediately invalidates the previous incomplete
challenge — the contract YAML allows the begin endpoint to be retried).
The value is JSON-encoded::

    {
      "challenge_id": "<uuid4>",
      "factors_required": ["password", "totp"],
      "issued_at": "<iso8601 utc>"
    }

TTL is :data:`STEP_UP_CHALLENGE_TTL_SECONDS` (5 min — matches
:data:`echoroo.services.step_up_token_service.STEP_UP_TOKEN_TTL_SECONDS`).

Concurrency
-----------
:func:`consume_challenge` fetches **and** deletes the record in a single
Redis round-trip via ``GETDEL`` (redis-py >= 4.4, fakeredis >= 2.1).
Two concurrent ``complete`` calls observing the same ``(user_id, scope)``
slot therefore see exactly one ``GETDEL`` win the race: the loser
receives ``None`` and is mapped to
:class:`StepUpChallengeNotFoundError` → ``401`` at the API boundary.
This closes the previous non-atomic ``GET`` → in-process validation →
``DELETE`` window, where two parallel completions of the same
challenge could both succeed before the deletion landed.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

#: TTL applied to every challenge record. Mirrors the step-up JWT TTL
#: so the begin / complete window is bounded by the same clock.
STEP_UP_CHALLENGE_TTL_SECONDS: Final[int] = 300

#: Redis key prefix. One record per (user_id, scope) pair — a new
#: ``begin`` invocation OVERWRITES (and therefore invalidates) the
#: outstanding record. This intentionally matches the "begin again"
#: semantics of the TOTP / WebAuthn challenge stores in
#: ``services/two_factor_service.py`` and ``services/webauthn_service.py``.
_KEY_PREFIX: Final[str] = "step_up_challenge"


class StepUpChallengeError(Exception):
    """Base class for challenge-store failures."""


class StepUpChallengeNotFoundError(StepUpChallengeError):
    """Raised when no challenge record exists for (user_id, scope)."""


class StepUpChallengeMismatchError(StepUpChallengeError):
    """Raised when the supplied ``challenge_id`` does not match the record."""


def _challenge_key(user_id: UUID, scope: str) -> str:
    """Build the Redis key for the (user_id, scope) slot.

    ``scope`` is included in the key (rather than the value) so a future
    expansion to additional step-up scopes (e.g. one for high-risk DSR
    exports) does not need a key-format migration.
    """
    return f"{_KEY_PREFIX}:{user_id}:{scope}"


async def create_challenge(
    redis: Redis,
    *,
    user_id: UUID,
    scope: str,
    factors_required: Sequence[str],
    ttl_seconds: int = STEP_UP_CHALLENGE_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Mint a fresh challenge record and persist it under the user/scope key.

    Overwrites any existing record for the same ``(user_id, scope)`` pair
    — the contract YAML permits a caller to abandon an in-progress
    challenge by simply re-calling ``begin``. The previous record's TTL
    is discarded because the new ``SET`` re-arms the EX window.

    Returns:
        ``(challenge_id, issued_at)`` — the caller forwards
        ``challenge_id`` to the frontend and uses ``issued_at`` only for
        audit / telemetry detail.
    """
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    if not factors_required:
        raise ValueError("factors_required must be non-empty")

    challenge_id = str(uuid.uuid4())
    issued_at = datetime.now(UTC)
    record = {
        "challenge_id": challenge_id,
        "factors_required": list(factors_required),
        "issued_at": issued_at.isoformat(),
    }
    await redis.set(
        _challenge_key(user_id, scope),
        json.dumps(record),
        ex=ttl_seconds,
    )
    return challenge_id, issued_at


async def consume_challenge(
    redis: Redis,
    *,
    user_id: UUID,
    scope: str,
    challenge_id: str,
) -> list[str]:
    """Fetch-and-delete the persisted record in a single Redis round-trip.

    Uses Redis ``GETDEL`` so the read and the delete are atomic from the
    server's perspective. Two concurrent ``complete`` calls targeting
    the same ``(user_id, scope)`` slot therefore observe exactly one
    winner — the loser sees ``None`` and is mapped to
    :class:`StepUpChallengeNotFoundError`. This closes the race window
    in the previous non-atomic ``GET`` then ``DELETE`` implementation,
    where two parallel completions could both succeed before the
    deletion landed.

    The record is removed regardless of ``challenge_id`` match — a wrong
    ``challenge_id`` strongly implies the caller is either retrying a
    stale window or actively probing, and in either case the safe
    behaviour is to drop the record so the next ``begin`` issues a fresh
    one. The frontend may need to re-run ``begin`` after a mismatch.

    Args:
        redis: Async Redis connection. Must support ``GETDEL`` —
            redis-py >= 4.4 / fakeredis >= 2.1; verified at startup
            because the production codebase pins ``redis>=5.2.0`` and
            ``fakeredis>=2.23`` in ``pyproject.toml``.
        user_id: Authenticated session user — keyed into the slot.
        scope: Step-up scope (e.g. ``"admin_recovery"``).
        challenge_id: ``challenge_id`` returned by the matching
            ``begin`` call. Compared with the stored record verbatim.

    Returns:
        ``factors_required`` list from the matched record, so the
        completion handler can apply the SAME constraint the begin
        handler advertised (defence in depth — refuses the call if the
        client tries to satisfy a different factor set than was
        originally negotiated).

    Raises:
        StepUpChallengeNotFoundError: No record under the key (expired
            TTL, already consumed by a parallel winner, never issued,
            or the stored JSON / factor list is malformed).
        StepUpChallengeMismatchError: Record exists but ``challenge_id``
            does not match. The record is already deleted by the
            atomic ``GETDEL``.
    """
    key = _challenge_key(user_id, scope)
    # Atomic fetch-and-delete. Redis ``GETDEL`` returns the value and
    # removes the key in a single server-side operation, so concurrent
    # completes targeting the same slot cannot both observe a record.
    raw = await redis.getdel(key)
    if raw is None:
        raise StepUpChallengeNotFoundError(
            "Step-up challenge not found or expired; restart the begin flow."
        )

    try:
        record = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Corrupt step-up challenge record for user=%s scope=%s",
            user_id,
            scope,
        )
        raise StepUpChallengeNotFoundError(
            "Step-up challenge record is corrupt; restart the begin flow."
        ) from exc

    stored_id = record.get("challenge_id")
    if not isinstance(stored_id, str) or stored_id != challenge_id:
        raise StepUpChallengeMismatchError(
            "Step-up challenge_id does not match the active record."
        )

    factors = record.get("factors_required")
    if not isinstance(factors, list) or not all(isinstance(f, str) for f in factors):
        # Defensive: refuse a record with a malformed factor list rather
        # than letting the completion handler silently degrade the
        # AND-condition. Treat as "not found" so the frontend simply
        # restarts.
        raise StepUpChallengeNotFoundError(
            "Step-up challenge record has malformed factors_required."
        )
    return list(factors)


__all__ = [
    "STEP_UP_CHALLENGE_TTL_SECONDS",
    "StepUpChallengeError",
    "StepUpChallengeMismatchError",
    "StepUpChallengeNotFoundError",
    "consume_challenge",
    "create_challenge",
]
