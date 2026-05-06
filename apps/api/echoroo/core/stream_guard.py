"""Phase 17 backlog A-5: Streaming permission re-check infrastructure.

The HTTP response is committed when the first chunk is yielded — the status
line and headers cannot be changed afterwards. This module provides the
primitives required to honour the **Hybrid Contract** described in
``specs/006-permissions-redesign/PHASE17_BACKLOG.md``:

  * pre-start revoke → 403 (handled by :func:`gate_action` in the router).
  * post-start revoke → cannot change status; the stream MUST stop yielding
    protected data, write a ``stream.permission_revoked_mid_stream`` audit
    record, and terminate. CSV streams MAY append the sentinel
    :data:`SENTINEL_BYTES` so a human/audit reader can detect truncation;
    binary audio streams terminate without a sentinel (would corrupt media).

Public API
----------

* :func:`recheck_action_permission` — :func:`gate_action` equivalent,
  decision-only. Re-runs the full permission resolution against the current
  DB state and raises :class:`PermissionRevokedMidStream` on denial.
* :func:`audit_stream_revoked` — post-commit audit on a fresh
  ``AsyncSessionLocal`` (the request session is unsafe at this point).
* :data:`SENTINEL_BYTES` — CSV-only sentinel inserted before stream close.
* :data:`CSV_RECHECK_INTERVAL`, :data:`AUDIO_RECHECK_INTERVAL` — guard
  cadence (rows for CSV, 65 KiB chunks for audio).

Transaction isolation
---------------------

Callers MUST run on PostgreSQL READ COMMITTED (the echoroo default). Each
new SELECT is guaranteed to see the most recent committed write from any
other connection — a sibling request that revokes membership commits its
``DELETE`` / ``UPDATE`` and the next ``recheck_action_permission()`` call
observes the change.

Identity-map / population
-------------------------

The request-scoped :class:`AsyncSession` caches ORM rows in its identity
map. We bypass the cache by passing
``execution_options(populate_existing=True)`` so the second SELECT does
NOT silently re-use the stale Project / ApiKey row from the first
``gate_action`` call.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.permissions import (
    Action,
    Permission,
    decide_action_permission,
    load_project_or_404,
)
from echoroo.models.api_key import ApiKey

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import Request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: CSV-only sentinel appended to the body when a mid-stream revoke is
#: detected. Audit consumers / humans can grep for this marker to identify
#: truncated exports. Audio streams do NOT yield this sentinel because
#: arbitrary bytes inside an OGG / WAV container would corrupt playback.
SENTINEL_BYTES: Final[bytes] = b"\r\n--PERMISSION-REVOKED--\r\n"

#: Re-check the gate every N CSV rows. Chosen so a 100k-row export pays at
#: most ~1k extra SELECTs (~1% overhead) while bounding the post-revoke
#: leak to the next ~100 rows of latency.
CSV_RECHECK_INTERVAL: Final[int] = 100

#: Re-check the gate every N audio chunks (each chunk is the 65 KiB read
#: emitted by ``file.read(65536)``). At 8 chunks ≈ 512 KiB the overhead is
#: imperceptible on a multi-megabyte stream and the leak window is bounded
#: to ~half a second of audio at typical bitrates.
AUDIO_RECHECK_INTERVAL: Final[int] = 8


# ---------------------------------------------------------------------------
# Public exceptions
# ---------------------------------------------------------------------------


class PermissionRevokedMidStream(Exception):
    """Raised by :func:`recheck_action_permission` on mid-stream revoke.

    MUST be caught by stream wrappers; never propagated past the
    ``StreamingResponse`` boundary. Starlette has no way to convert a
    generator exception into an HTTP 4xx because the response status line
    has already been written.
    """


# ---------------------------------------------------------------------------
# Permission re-check
# ---------------------------------------------------------------------------


async def _refresh_api_key_scopes(
    db: AsyncSession,
    *,
    current_user: Any,
) -> tuple[bool, frozenset[Permission] | None]:
    """Re-read the ApiKey row that authenticated this request.

    Returns ``(revoked, refreshed_scopes)``.

    * ``revoked=True`` — the key is gone, deleted, or has ``revoked_at``
      set. The mid-stream guard MUST treat this as denial regardless of
      what the matrix would say.
    * ``revoked=False`` and ``refreshed_scopes is not None`` — translate
      ``ApiKey.granted_permissions`` into the freshly-evaluated
      :class:`Permission` set so :func:`is_allowed` intersects against
      the current scope (a sibling request may have shrunk the scope).
    * ``revoked=False`` and ``refreshed_scopes is None`` — caller did not
      authenticate via an API key (e.g. JWT session); the regular gate
      result applies unchanged.
    """
    api_key_id = getattr(current_user, "_api_key_id", None)
    if api_key_id is None:
        return False, None

    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.id == api_key_id)
        .execution_options(populate_existing=True)
    )
    key = result.scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        return True, None

    translated: set[Permission] = set()
    for scope in key.granted_permissions or ():
        try:
            translated.add(
                scope if isinstance(scope, Permission) else Permission(scope)
            )
        except ValueError:
            continue
    return False, frozenset(translated)


async def recheck_action_permission(
    *,
    db: AsyncSession,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
) -> None:
    """Re-evaluate the gate decision against the **current** DB state.

    Mirrors :func:`echoroo.core.permissions.gate_action` but is
    decision-only: instead of raising :class:`HTTPException` (which
    Starlette would silently swallow inside a streaming generator) it
    raises :class:`PermissionRevokedMidStream` on denial. The caller is
    expected to catch it, write the audit row, and stop yielding.

    Phase 17 backlog A-5 Round 2 R1-I1: the actual decision is now
    delegated to
    :func:`echoroo.core.permissions.decide_action_permission` so this
    function shares a single source of truth with
    :func:`gate_action`. Drift is therefore structurally impossible —
    when a future Phase adds another condition to the gate, the
    mid-stream guard picks it up automatically.

    ``refresh_api_key_scopes=True`` instructs the helper to:

      * bypass the identity-map cache when reloading the Project row
        (``populate_existing=True``), so a sibling-session revoke is
        observed.
      * re-fetch the ``ApiKey`` row from the DB (Codex C-2 fix: the
        scopes stamped on ``current_user._api_key_scopes`` are
        request-scoped and would not otherwise see a sibling-request
        revoke).
    """
    decision = await decide_action_permission(
        db=db,
        action=action,
        project_id=project_id,
        current_user=current_user,
        request=request,
        refresh_api_key_scopes=True,
    )
    if not decision.allowed:
        raise PermissionRevokedMidStream(decision.reason or "action_denied")


# Re-export for callers that prefer the canonical 404 helper for
# pre-start checks. Not used by recheck (we treat missing as revoke).
__all_helpers__ = (load_project_or_404,)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def audit_stream_revoked(
    *,
    project_id: UUID,
    user_id: UUID | None,
    stream_type: str,
    request_id: str = "",
    ip: str = "",
    user_agent: str = "",
    reason: str | None = None,
) -> None:
    """Write ``stream.permission_revoked_mid_stream`` to the platform log.

    Uses a fresh :class:`AsyncSessionLocal` (A-11 post-commit pattern):
    the request-scoped session is unsafe at this point because the
    streaming generator may have already issued / committed SQL on its
    underlying connection, and the audit writer requires a fresh
    SERIALIZABLE transaction (see ``audit_service._write`` docstring).

    Failures are soft-alerted: a streaming response that has already
    committed bytes cannot be retroactively failed, so the audit miss
    must not crash the request. Operators rely on the ``logger.warning``
    + downstream log alerting.
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            from echoroo.services.audit_service import AuditLogService

            audit = AuditLogService(audit_session)
            await audit.write_platform_event(
                actor_user_id=user_id,
                action="stream.permission_revoked_mid_stream",
                request_id=request_id,
                ip=ip,
                user_agent=user_agent,
                detail={
                    "project_id": str(project_id),
                    "stream_type": stream_type,
                    "reason": reason or "",
                },
            )
            await audit_session.commit()
    except Exception:  # noqa: BLE001 — soft-alert, must not crash the stream
        logger.warning(
            "stream_revoked audit failed for project_id=%s stream=%s reason=%s",
            project_id,
            stream_type,
            reason,
            exc_info=True,
        )


__all__ = [
    "AUDIO_RECHECK_INTERVAL",
    "CSV_RECHECK_INTERVAL",
    "PermissionRevokedMidStream",
    "SENTINEL_BYTES",
    "audit_stream_revoked",
    "recheck_action_permission",
]
