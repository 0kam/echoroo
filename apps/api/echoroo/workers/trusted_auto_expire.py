"""Celery worker that auto-expires Trusted overlay rows (Phase 10 / T516, FR-044).

Background
----------
A :class:`echoroo.models.project_trusted_user.ProjectTrustedUser` row is
born with ``status='active'`` and an absolute ``expires_at`` wall-clock
timestamp. Per FR-044 the row's capability MUST stop applying the moment
``expires_at`` is in the past — but the gate already enforces that at
request time by filtering on ``expires_at > now`` (see
:func:`echoroo.services.trusted_service.get_active_trusted_capabilities`).

This worker runs as a defence-in-depth janitor that flips the row's
``status`` field to ``expired`` so:

1. The Owner / Admin management UI (T520) does not need to compute
   "live" status from the timestamp — a simple ``status='active'``
   filter is sufficient.
2. The 7-day expiry notifier (T515) can use ``status='active'`` as its
   eligibility filter without race conditions against rows that have
   already lapsed.
3. The Redis pub/sub broadcast wakes any active WebSocket / SSE
   subscriber (NFR-008a) so the client-side cache invalidates within
   the documented 5-minute window.

Schedule
--------
Wired into :data:`echoroo.workers.celery_app.app.conf.beat_schedule`
under the ``trusted-auto-expire-hourly`` entry — fires every hour at
the 5-minute mark so it does not collide with the on-the-hour upload
janitor.

Idempotency
-----------
The UPDATE filters on ``status='active' AND expires_at <= now`` so
re-running the task on the same dataset is a no-op (rows already in
``expired`` / ``revoked`` are skipped). The Redis broadcast is
best-effort — losing a message only delays the WebSocket invalidation
to the next 5-minute tick of T514's loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.redis import get_redis_connection
from echoroo.models.enums import ProjectTrustedStatus
from echoroo.services.audit_service import AuditLogService
from echoroo.services.trusted_service import TRUSTED_INVALIDATION_CHANNEL
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)

#: Audit action recorded against ``project_audit_log`` for each batch flip.
_AUDIT_ACTION: str = "project.trusted_user.auto_expire"


async def _flip_to_expired_returning(
    session: AsyncSession,
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Atomically flip every due overlay to ``expired`` and return the rows.

    Uses a single ``UPDATE ... RETURNING`` so the SELECT (which rows
    are due) and the UPDATE (which rows we own) are the *same*
    statement. This eliminates the race between the prior SELECT
    snapshot and a separate UPDATE: a concurrent worker (or operator
    revoke) racing on the same row will only flip rows the other did
    not. Each invocation returns exactly the rows whose status this
    statement transitioned from ``active`` to ``expired`` (FR-044).

    The returned dicts carry ``id``, ``project_id``, ``user_id``, and
    ``expires_at`` so the caller can publish invalidations + audit
    without a follow-up SELECT.
    """
    stmt = sa.text(
        """
        UPDATE project_trusted_users
           SET status = :expired,
               updated_at = :now
         WHERE status = :active
           AND expires_at <= :now
        RETURNING id, project_id, user_id, expires_at
        """
    )
    result = await session.execute(
        stmt,
        {
            "expired": ProjectTrustedStatus.EXPIRED.value,
            "active": ProjectTrustedStatus.ACTIVE.value,
            "now": now,
        },
    )
    return [dict(row) for row in result.mappings().all()]


async def _publish_invalidation(
    *,
    user_id: str,
    project_id: str,
) -> None:
    """Publish a single invalidation message on the Trusted Redis channel.

    Mirrors the payload shape used by
    :func:`echoroo.services.trusted_service._publish_trusted_invalidation`
    so the T514 subscriber sees a uniform schema regardless of whether the
    flip came from an explicit revoke or from this auto-expire pass.
    """
    payload = json.dumps(
        {"user_id": user_id, "project_id": project_id, "reason": "expired"},
        sort_keys=True,
    )
    try:
        client = await get_redis_connection()
        await client.publish(TRUSTED_INVALIDATION_CHANNEL, payload)
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "trusted_auto_expire invalidation publish failed "
            "(NFR-008a soft alert): user_id=%s project_id=%s error=%r",
            user_id,
            project_id,
            exc,
        )


async def _record_audit(
    *,
    expired_count: int,
    expired_invitation_ids: list[str],
    project_ids: list[str],
) -> None:
    """Write a single ``project_audit_log`` row summarising the batch.

    Spec-wise FR-044 only requires the *capability* to lapse — the
    audit layer is bonus observability so operators can confirm the
    worker ran. Per the spec the row is recorded **once per task
    execution**, not once per affected project: the action is a system
    background job, the actor is ``NULL`` (no human triggered it), and
    the payload carries the full list of affected invitation IDs +
    projects so triage can fan out from the single row.

    The ``project_id`` column is required by the audit table so we
    pick the lexicographically smallest affected project as the
    "anchor" and record the rest in the ``detail`` payload. When no
    projects were affected the row is skipped entirely.

    Failure here is WARNING-logged only; the row flip itself has
    already committed.
    """
    if not expired_count or not project_ids:
        return
    anchor_project_id = sorted(project_ids)[0]
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                service = AuditLogService(audit_session)
                await service.write_project_event(
                    actor_user_id=None,
                    project_id=_uuid_from_str(anchor_project_id),
                    action=_AUDIT_ACTION,
                    request_id="",
                    ip="",
                    user_agent="",
                    detail={
                        "expired_count": expired_count,
                        "expired_invitation_ids": expired_invitation_ids,
                        "project_ids": sorted(project_ids),
                    },
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "trusted_auto_expire audit write failed (FR-088 soft alert): "
            "expired_count=%d error=%r",
            expired_count,
            exc,
        )


def _uuid_from_str(value: str) -> Any:
    """Convert a string UUID to :class:`uuid.UUID` lazily.

    ``project_id`` arrives from a SQLAlchemy mapping as a Python
    :class:`uuid.UUID` already in normal operation, but tests sometimes
    pass plain strings — coerce so the audit writer's typed argument is
    always satisfied.
    """
    from uuid import UUID

    return value if isinstance(value, UUID) else UUID(str(value))


async def _run_auto_expire() -> dict[str, int]:
    """Async implementation backing the Celery task.

    Pipeline
    --------
    1. ``UPDATE ... RETURNING`` — atomically flip every active overlay
       whose ``expires_at <= now`` to ``status='expired'`` and return
       the affected rows. This is a single statement so a concurrent
       worker (or operator revoke) cannot cause a double-publish or a
       missed publish: each task invocation publishes exactly the rows
       the same statement transitioned.
    2. Commit so the status flip is durable before any external
       side-effects fire.
    3. Publish a Redis invalidation per affected (user, project) pair
       so the WebSocket subscriber wakes within the documented 5 min
       window (NFR-008a). Publish failures are swallowed inside
       ``_publish_invalidation`` so a partial Redis outage does not
       fail the task — the status flip itself has already committed.
    4. Write a single ``project_audit_log`` row summarising the batch.

    Returns a summary dict suitable for the Celery result backend:
    ``{"expired": N}``.
    """
    now = datetime.now(UTC)

    async with AsyncSessionLocal() as session:
        try:
            expired_rows = await _flip_to_expired_returning(session, now=now)
            if not expired_rows:
                logger.info("trusted_auto_expire: no overlays past expiry")
                return {"expired": 0}
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    expired_count = len(expired_rows)

    # Publish invalidations + audit AFTER the main TX has committed so a
    # broadcast cannot precede the durable status flip. Each row in
    # ``expired_rows`` was atomically claimed by the UPDATE above, so
    # there is no risk of double-publishing the same overlay across
    # concurrent worker invocations.
    project_ids: list[str] = []
    invitation_ids: list[str] = []
    for row in expired_rows:
        project_ids.append(str(row["project_id"]))
        invitation_ids.append(str(row["id"]))
        await _publish_invalidation(
            user_id=str(row["user_id"]),
            project_id=str(row["project_id"]),
        )

    await _record_audit(
        expired_count=expired_count,
        expired_invitation_ids=sorted(set(invitation_ids)),
        project_ids=sorted(set(project_ids)),
    )

    logger.info(
        "trusted_auto_expire: flipped %d overlay(s) to expired",
        expired_count,
    )
    return {"expired": expired_count}


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.trusted_auto_expire.auto_expire_trusted_users",
)
def auto_expire_trusted_users() -> dict[str, int]:
    """Flip overdue Trusted overlay rows to ``status='expired'`` (FR-044).

    Returns:
        Summary dict with the number of rows flipped, e.g.
        ``{"expired": 3}``. The Celery result backend records this for
        observability dashboards (Grafana panel "trusted overlays
        expired per hour").
    """
    return asyncio.run(_run_auto_expire())


__all__ = [
    "auto_expire_trusted_users",
]
