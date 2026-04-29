"""Daily sweep that nulls expired invitation emails (Phase 14 / T902, FR-106).

Background
----------
:class:`echoroo.models.project.ProjectInvitation` rows persist the
invitee's email address in two columns:

* ``email``       — plaintext, kept solely for operator readability
                    of the outgoing message.
* ``email_hash``  — HMAC-SHA-256 keyed digest used by the runtime
                    membership lookup (FR-055).

Once an invitation has been ``accepted`` / ``declined`` / ``expired``
for 30 days the plaintext column has no operational use — the
recipient already has a session if they accepted, or the invitation
is closed. FR-106 requires us to NULL the plaintext while keeping
the HMAC hash so audit replay (FR-054) still works.

Schedule
--------
Wired into :data:`echoroo.workers.celery_app.app.conf.beat_schedule`
under ``invitation-email-null-daily`` — fires daily at 02:30 UTC,
sandwiched between the GBIF vernacular sync (02:00) and the
trusted-expiry-notifier (03:00) so a slow UPDATE on one job does
not starve the others.

Idempotency
-----------
The UPDATE filters on ``email IS NOT NULL`` so re-running the task on
the same dataset is a no-op (rows already nulled are skipped). No
audit row is written: PII null-out is automated GDPR compliance, not
a human-driven operator action — emitting one row per swept
invitation would only add noise to the operator dashboard. The
invariant is that any row whose state-machine has been terminal for
30 days SHALL have ``email IS NULL``; the operator can probe the
invariant directly in production via SQL if needed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)

#: FR-106: 30 days after the row reached a terminal status before we
#: scrub the plaintext. Lifted as a constant so test fixtures can
#: shorten the window without seeding the system_settings table.
INVITATION_EMAIL_NULL_AFTER: Final[timedelta] = timedelta(days=30)

#: Terminal statuses that make a row eligible for scrub. The
#: status-specific cutoff column for each is encoded directly in the
#: UPDATE statement; this tuple exists only as documentation.
#: ``revoked`` rows never carried plaintext the recipient had not
#: already received via email, so the same window applies.
_TERMINAL_STATUSES: Final[tuple[str, ...]] = (
    "accepted",
    "declined",
    "expired",
    "revoked",
)


async def _sweep_eligible_rows(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> int:
    """NULL ``email`` for every terminal row past the cutoff.

    Uses a single ``UPDATE ... RETURNING id`` so the eligible-row
    selection and the mutation are the same statement; a concurrent
    operator-triggered UPDATE racing on the same row never observes
    a half-applied state. The returned count drives the operator
    metric / log line.

    The cutoff predicate is evaluated against the **status-specific**
    transition timestamp, not ``updated_at``, because FR-106 measures
    the 30-day window from "settled" — i.e. when the row reached its
    terminal status — not from the most recent administrative edit.
    Using ``updated_at`` would let an unrelated bookkeeping touch
    (for example a future ``invited_by`` repair migration) reset the
    countdown on every affected row. The mapping is:

    * ``accepted`` → ``accepted_at``
    * ``declined`` → ``declined_at``
    * ``revoked``  → ``revoked_at``
    * ``expired``  → ``expires_at`` (the boundary itself; FR-043)

    A defensive ``<column> IS NOT NULL`` guard accompanies each
    branch even though the ``invitation_settle_columns_align`` CHECK
    constraint at
    :mod:`echoroo.models.project.ProjectInvitation` already enforces
    the invariant — a future schema migration that ever loosens that
    constraint must not silently scrub rows that lack a transition
    timestamp.
    """
    stmt = sa.text(
        """
        UPDATE project_invitations
           SET email = NULL,
               updated_at = :now
         WHERE email IS NOT NULL
           AND (
               (status = 'accepted' AND accepted_at IS NOT NULL
                    AND accepted_at < :cutoff)
            OR (status = 'declined' AND declined_at IS NOT NULL
                    AND declined_at < :cutoff)
            OR (status = 'revoked' AND revoked_at IS NOT NULL
                    AND revoked_at < :cutoff)
            OR (status = 'expired' AND expires_at IS NOT NULL
                    AND expires_at < :cutoff)
           )
        RETURNING id
        """
    )
    result = await session.execute(
        stmt,
        {
            "now": datetime.now(UTC),
            "cutoff": cutoff,
        },
    )
    return len(result.fetchall())


async def _run_sweep(
    *,
    now: datetime | None = None,
    null_after: timedelta = INVITATION_EMAIL_NULL_AFTER,
) -> dict[str, Any]:
    """Async pipeline backing :func:`sweep_invitation_emails`.

    Splits the work across:

    1. Compute the cutoff (``now - 30d``).
    2. Issue the single ``UPDATE ... RETURNING id`` statement.
    3. Commit so the scrub is durable.

    Returns a summary dict suitable for the Celery result backend.
    """
    now_eff = now or datetime.now(UTC)
    cutoff = now_eff - null_after

    async with AsyncSessionLocal() as session:
        try:
            scrubbed = await _sweep_eligible_rows(session, cutoff=cutoff)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    if scrubbed:
        logger.info(
            "invitation_email_null: scrubbed %d invitation email(s) "
            "(cutoff=%s)",
            scrubbed,
            cutoff.isoformat(),
        )
    else:
        logger.debug(
            "invitation_email_null: no rows past cutoff (cutoff=%s)",
            cutoff.isoformat(),
        )
    return {
        "status": "ok",
        "scrubbed": scrubbed,
        "evaluated_at": now_eff.isoformat(),
        "cutoff": cutoff.isoformat(),
    }


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.invitation_email_null.sweep_invitation_emails",
)
def sweep_invitation_emails() -> dict[str, Any]:
    """NULL ``project_invitations.email`` 30 days after terminal status (FR-106).

    Returns:
        Summary dict with the number of rows scrubbed, e.g.
        ``{"status": "ok", "scrubbed": 12, ...}``.
    """
    return asyncio.run(_run_sweep())


__all__ = [
    "INVITATION_EMAIL_NULL_AFTER",
    "sweep_invitation_emails",
]
