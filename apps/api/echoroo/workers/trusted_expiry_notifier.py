"""Celery worker that pre-emptively notifies expiring Trusted overlays (T515, FR-045).

Background
----------
Per FR-045 the system must warn both the Trusted user and the project's
Owner exactly seven days before the overlay's ``expires_at`` lapses so
they have a window to renew before access drops at the request gate.
This module implements that warning as a daily Celery beat job that:

1. Picks up every active overlay whose ``expires_at`` falls inside the
   ``[now + 6d, now + 7d]`` BETWEEN window (inclusive both ends) — a
   one-day band wide enough that a missed run does not silently
   swallow notifications, but narrow enough that a row is not
   double-notified across consecutive days. The boundary at exactly
   ``now + 7d`` is included so an overlay born exactly seven days ago
   is not silently skipped between consecutive runs.
2. Enqueues two outbox events per row — one for the Trusted user, one
   for the Owner — using the existing transactional outbox pipeline
   (:mod:`echoroo.services.outbox_service`). Idempotency keys embed the
   ``invitation_id`` and the calendar day so a re-run on the same UTC
   date is a no-op via the outbox's ``ON CONFLICT (idempotency_key) DO
   UPDATE`` semantics (research.md §6 / FR-076a).
3. Records a single ``project.trusted_user.expiry_notice`` audit row
   per Trusted overlay so operators can confirm the warning fired
   (FR-088 best-effort soft-alert).

The actual email rendering lives behind the
``trusted_user.expiry_notification`` outbox event_type — Phase 11+ adds
the dispatcher (mirrors the
:mod:`echoroo.workers.login_notification_dispatcher` shape). Until then
the outbox row simply queues for delivery and the notifier is unblocked.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import ProjectTrustedStatus
from echoroo.services import outbox_service
from echoroo.services.audit_service import AuditLogService
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


#: Outbox ``event_type`` consumed by the Phase 11+ dispatcher that
#: actually renders + sends the warning email through Resend. Kept in
#: this module so call-sites do not need to thread the constant through.
OUTBOX_EVENT_TRUSTED_EXPIRY: str = "trusted_user.expiry_notification"

#: Audit action stamped on the ``project_audit_log`` row that records the
#: notification fan-out (FR-045 + FR-088).
_AUDIT_ACTION: str = "project.trusted_user.expiry_notice"

#: Width of the eligibility band, in days. Rows whose ``expires_at`` is
#: earlier than this floor are skipped — they would have been picked up
#: on a previous run; a row whose ``expires_at`` is later than the
#: ceiling is also skipped — it will surface on a future run when its
#: window opens.
_NOTIFY_WINDOW_FLOOR_DAYS: int = 6
_NOTIFY_WINDOW_CEILING_DAYS: int = 7


async def _select_due_rows(
    session: AsyncSession,
    *,
    floor: datetime,
    ceiling: datetime,
) -> list[dict[str, Any]]:
    """Return overlay rows whose ``expires_at`` falls in ``[floor, ceiling]``.

    Inclusive on both ends (PostgreSQL ``BETWEEN`` semantics) so an
    overlay whose ``expires_at`` lands exactly at ``now + 7d`` is not
    silently dropped between consecutive runs.

    Joined against ``users`` and ``projects`` so the email enqueuer has
    access to the recipient address and the Owner ID without issuing a
    second round-trip per row.
    """
    stmt = sa.text(
        """
        SELECT
            ptu.id              AS trusted_user_id,
            ptu.invitation_id   AS invitation_id,
            ptu.project_id      AS project_id,
            ptu.user_id         AS user_id,
            ptu.expires_at      AS expires_at,
            u.email             AS user_email,
            p.owner_id          AS owner_id,
            p.name              AS project_name,
            owner.email         AS owner_email
          FROM project_trusted_users ptu
          JOIN users u           ON u.id = ptu.user_id
          JOIN projects p        ON p.id = ptu.project_id
          JOIN users owner       ON owner.id = p.owner_id
         WHERE ptu.status = :active
           AND ptu.expires_at BETWEEN :floor AND :ceiling
        """
    )
    result = await session.execute(
        stmt,
        {
            "active": ProjectTrustedStatus.ACTIVE.value,
            "floor": floor,
            "ceiling": ceiling,
        },
    )
    return [dict(row) for row in result.mappings().all()]


def _build_payload(
    *,
    role: str,
    recipient_email: str,
    invitation_id: UUID,
    project_id: UUID,
    project_name: str,
    user_id: UUID,
    expires_at: datetime,
) -> dict[str, Any]:
    """Render the outbox payload consumed by the dispatcher.

    ``role`` is one of ``"trusted_user"`` or ``"owner"`` so the
    dispatcher can pick the correct template without re-deriving the
    relationship from the project table.
    """
    return {
        "role": role,
        "recipient_email": recipient_email,
        "invitation_id": str(invitation_id),
        "project_id": str(project_id),
        "project_name": project_name,
        "user_id": str(user_id),
        "expires_at": expires_at.isoformat(),
    }


def _idempotency_key(
    *,
    role: str,
    invitation_id: UUID,
    notify_day: date,
) -> str:
    """Return a stable key per (overlay, role, UTC date).

    The day component prevents a second run on the same UTC date from
    sending duplicate emails — the outbox enqueue path collapses the
    second INSERT into the existing row via ``ON CONFLICT
    (idempotency_key) DO UPDATE``.
    """
    return f"trusted_expiry:{invitation_id}:{role}:{notify_day.isoformat()}"


async def _enqueue_one(
    session: AsyncSession,
    *,
    role: str,
    recipient_email: str,
    invitation_id: UUID,
    project_id: UUID,
    project_name: str,
    user_id: UUID,
    expires_at: datetime,
    notify_day: date,
) -> None:
    """Enqueue a single outbox row for one (overlay, role) pair."""
    payload = _build_payload(
        role=role,
        recipient_email=recipient_email,
        invitation_id=invitation_id,
        project_id=project_id,
        project_name=project_name,
        user_id=user_id,
        expires_at=expires_at,
    )
    idempotency_key = _idempotency_key(
        role=role,
        invitation_id=invitation_id,
        notify_day=notify_day,
    )
    await outbox_service.enqueue(
        session,
        event_type=OUTBOX_EVENT_TRUSTED_EXPIRY,
        payload=payload,
        idempotency_key=idempotency_key,
    )


async def _record_notice_audit(
    *,
    project_id: UUID,
    invitation_id: UUID,
    user_id: UUID,
    expires_at: datetime,
) -> None:
    """Best-effort audit row for the FR-045 notification fan-out.

    Uses a fresh :class:`AsyncSessionLocal` because the audit writer
    issues ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` which the
    outbox-enqueue session has already disqualified (it ran an INSERT).
    """
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                service = AuditLogService(audit_session)
                await service.write_project_event(
                    actor_user_id=None,
                    project_id=project_id,
                    action=_AUDIT_ACTION,
                    request_id="",
                    ip="",
                    user_agent="",
                    detail={
                        "invitation_id": str(invitation_id),
                        "user_id": str(user_id),
                        "expires_at": expires_at.isoformat(),
                    },
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "trusted_expiry_notifier audit write failed (FR-088 soft alert): "
            "invitation_id=%s error=%r",
            invitation_id,
            exc,
        )


async def _run_notify_expiring() -> dict[str, int]:
    """Async implementation backing the Celery task."""
    now = datetime.now(UTC)
    floor = now + timedelta(days=_NOTIFY_WINDOW_FLOOR_DAYS)
    ceiling = now + timedelta(days=_NOTIFY_WINDOW_CEILING_DAYS)
    notify_day = now.date()

    notified = 0
    skipped = 0

    async with AsyncSessionLocal() as session:
        try:
            due_rows = await _select_due_rows(
                session, floor=floor, ceiling=ceiling
            )
            if not due_rows:
                logger.info("trusted_expiry_notifier: no overlays in 7-day window")
                return {"notified": 0, "skipped": 0}

            for row in due_rows:
                # Defensive: skip rows whose recipient or owner email is
                # missing — the dispatcher would just dead-letter the
                # row anyway, and not enqueueing keeps the outbox table
                # tidy.
                user_email = row.get("user_email") or ""
                owner_email = row.get("owner_email") or ""
                if not user_email or not owner_email:
                    skipped += 1
                    logger.warning(
                        "trusted_expiry_notifier: skipping invitation_id=%s — "
                        "missing email (user=%s owner=%s)",
                        row["invitation_id"],
                        bool(user_email),
                        bool(owner_email),
                    )
                    continue

                project_id = _coerce_uuid(row["project_id"])
                invitation_id = _coerce_uuid(row["invitation_id"])
                user_id = _coerce_uuid(row["user_id"])
                expires_at = row["expires_at"]
                project_name = str(row.get("project_name") or "")

                await _enqueue_one(
                    session,
                    role="trusted_user",
                    recipient_email=user_email,
                    invitation_id=invitation_id,
                    project_id=project_id,
                    project_name=project_name,
                    user_id=user_id,
                    expires_at=expires_at,
                    notify_day=notify_day,
                )
                await _enqueue_one(
                    session,
                    role="owner",
                    recipient_email=owner_email,
                    invitation_id=invitation_id,
                    project_id=project_id,
                    project_name=project_name,
                    user_id=user_id,
                    expires_at=expires_at,
                    notify_day=notify_day,
                )
                notified += 1

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    # Audit fan-out runs AFTER the outbox enqueue commits so the audit
    # row is only ever recorded for events that durably reached the
    # outbox.
    for row in due_rows:
        if not row.get("user_email") or not row.get("owner_email"):
            continue
        await _record_notice_audit(
            project_id=_coerce_uuid(row["project_id"]),
            invitation_id=_coerce_uuid(row["invitation_id"]),
            user_id=_coerce_uuid(row["user_id"]),
            expires_at=row["expires_at"],
        )

    logger.info(
        "trusted_expiry_notifier: notified=%d skipped=%d", notified, skipped
    )
    return {"notified": notified, "skipped": skipped}


def _coerce_uuid(value: Any) -> UUID:
    """Normalise a SQLAlchemy mapping value to :class:`uuid.UUID`."""
    return value if isinstance(value, UUID) else UUID(str(value))


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.trusted_expiry_notifier.notify_expiring_trusted_users",
)
def notify_expiring_trusted_users() -> dict[str, int]:
    """Notify Trusted users + Owners 7 days before overlay expiry (FR-045).

    Returns:
        Summary dict ``{"notified": N, "skipped": M}`` where ``N`` counts
        overlays whose two-email fan-out enqueued cleanly and ``M``
        counts overlays skipped due to missing email columns.
    """
    return asyncio.run(_run_notify_expiring())


__all__ = [
    "OUTBOX_EVENT_TRUSTED_EXPIRY",
    "notify_expiring_trusted_users",
]
