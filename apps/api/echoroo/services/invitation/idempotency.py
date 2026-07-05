"""Idempotency-key storage helpers (FR-053).

Idempotency (FR-053):

* :func:`accept_invitation` requires a live Redis client (non-Optional)
  and accepts an optional ``idempotency_key``. The resulting outcome is
  pinned to the key in Redis (24 h TTL). A retry with the same key
  returns the cached outcome marker (``is_replay=True``); a retry with
  a *different* token under the same key raises
  :class:`InvitationConflictError` (HTTP 409). Read / write faults
  surface as :class:`InvitationInfraUnavailableError` (HTTP 503,
  fail-closed) so a partial Redis outage cannot bypass the dedupe
  guarantee.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .constants import _IDEMPOTENCY_KEY_PREFIX, _IDEMPOTENCY_TTL_SECONDS
from .errors import InvitationInfraUnavailableError

if TYPE_CHECKING:
    from redis.asyncio import Redis


@dataclass(frozen=True)
class _IdempotencyRecord:
    """Internal cache shape for FR-053 idempotency-key storage."""

    invitation_id: str
    token_hash: str
    is_replay: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def _idempotency_redis_key(idempotency_key: str) -> str:
    return f"{_IDEMPOTENCY_KEY_PREFIX}{idempotency_key}"


async def _get_idempotent_outcome(
    redis: Redis,
    idempotency_key: str,
) -> _IdempotencyRecord | None:
    """Return the cached :class:`_IdempotencyRecord` for ``idempotency_key``.

    Returns ``None`` when no record exists. **Fail-closed**: any Redis
    transport / runtime fault is converted to
    :class:`InvitationInfraUnavailableError` (HTTP 503) so the caller
    cannot bypass the FR-053 idempotency guard during a partial outage.
    A silent ``None`` would let an attacker reuse the same key with a
    different token and get a fresh accept; mapping the fault to 503
    forces the client to retry against a healthy primary instead.
    """
    try:
        raw = await redis.get(_idempotency_redis_key(idempotency_key))
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation idempotency cache (Redis) is unavailable"
        ) from exc
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return _IdempotencyRecord(
        invitation_id=str(data.get("invitation_id", "")),
        token_hash=str(data.get("token_hash", "")),
        is_replay=True,
        created_at=str(data.get("created_at", "")),
    )


async def _set_idempotent_outcome(
    redis: Redis,
    idempotency_key: str,
    record: _IdempotencyRecord,
) -> None:
    """Pin ``record`` to ``idempotency_key`` (24 h TTL).

    We use ``SET ... NX`` so we never overwrite a pre-existing record
    (the conflict path in :func:`accept_invitation` relies on the cached
    row remaining stable for the lifetime of the key).

    **Fail-closed**: any Redis transport / runtime fault surfaces as
    :class:`InvitationInfraUnavailableError`. Without the cached pin the
    24 h dedupe contract for FR-053 cannot be guaranteed (a subsequent
    retry would hit a cold cache and we would have no way to detect a
    different-token replay). A failed ``SET NX`` against an existing key
    is **not** a fault — it means a concurrent accept already pinned the
    same key, which is the expected idempotent path; we treat that as
    success.
    """
    payload = json.dumps(
        {
            "invitation_id": record.invitation_id,
            "token_hash": record.token_hash,
            "created_at": record.created_at,
        },
        sort_keys=True,
    )
    try:
        await redis.set(
            _idempotency_redis_key(idempotency_key),
            payload,
            ex=_IDEMPOTENCY_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed for any redis fault
        raise InvitationInfraUnavailableError(
            "invitation idempotency cache (Redis) is unavailable"
        ) from exc
