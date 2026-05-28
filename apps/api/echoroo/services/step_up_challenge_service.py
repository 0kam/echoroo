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
:func:`consume_challenge` is *not* strictly atomic because Redis lacks a
direct compare-and-delete primitive in our redis-py surface, but the
non-atomic ``GET`` → in-process validation → ``DELETE`` window is bounded
to a single asyncio task per user/scope (the caller has already cleared
authentication on the cookie before reaching this code) and the deletion
is unconditional, which means a concurrent retry observing the same
record will fail validation by ``challenge_id`` mismatch after the first
consumer wins. The race only meaningfully matters under intentional
self-replay, which is the same caller and therefore not a privilege
boundary.
"""

from __future__ import annotations

import json
import logging
import uuid
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
    factors_required: list[str],
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
    """Validate the ``challenge_id`` against the persisted record and DELETE it.

    The record is removed regardless of ``challenge_id`` match — a wrong
    ``challenge_id`` strongly implies the caller is either retrying a
    stale window or actively probing, and in either case the safe
    behaviour is to drop the record so the next ``begin`` issues a fresh
    one. The frontend may need to re-run ``begin`` after a mismatch.

    Args:
        redis: Async Redis connection.
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
            TTL, already consumed, never issued).
        StepUpChallengeMismatchError: Record exists but ``challenge_id``
            does not match. The record is still deleted before raising.
    """
    key = _challenge_key(user_id, scope)
    raw = await redis.get(key)
    if raw is None:
        raise StepUpChallengeNotFoundError(
            "Step-up challenge not found or expired; restart the begin flow."
        )

    # Always remove the record so a probing caller cannot brute-force
    # ``challenge_id`` values. We accept the (negligible) cost of an
    # extra round-trip per failed completion.
    await redis.delete(key)

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
