"""Daily sweep that nulls expired trusted overlay emails (Phase 14 / T903, FR-108).

Background
----------
:class:`echoroo.models.project_trusted_user.ProjectTrustedUser` rows
persist the email captured at invitation accept-time in two columns:

* ``email_at_invitation``       — plaintext, kept solely so an
                                  operator triaging a Trusted overlay
                                  audit can recognise the recipient.
* ``email_at_invitation_hash``  — HMAC-SHA-256 keyed digest used by
                                  audit replay (FR-054).

Once an overlay has been ``revoked`` or has lapsed (``expired``) for
90 days the plaintext column has no operational use — the capability
no longer applies and any active dispute would already have been
filed within the spec's 30-day audit window. FR-108 therefore
mandates that we NULL the plaintext while keeping the HMAC hash so
audit replay still resolves the recipient by hash.

Schedule
--------
Wired into :data:`echoroo.workers.celery_app.app.conf.beat_schedule`
under ``trusted-email-null-daily`` — fires daily at 02:45 UTC, in
between the invitation sweep (02:30) and the trusted-expiry-notifier
(03:00) so the three sequential daily jobs never overlap.

Idempotency
-----------
The UPDATE filters on ``email_at_invitation IS NOT NULL`` so
re-running the task on the same dataset is a no-op. No audit row is
written: PII null-out is automated GDPR compliance, not a
human-driven operator action.

Status semantics
----------------
The eligibility predicate is::

    (status = 'revoked' AND revoked_at < now - 90d)
        OR (status = 'expired' AND expires_at < now - 90d)

``revoked_at`` is ``NULL`` for any non-revoked row (the migration
guarantees the timestamp / status columns are kept in sync via
``ck_trusted_users_status_timestamps`` on the data-model.md side; the
worker is defensive about NULLs by ANDing each branch on the
matching status discriminator). Active overlays are ineligible — a
caller can still re-link the row to a person until the capability
lapses.
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

#: FR-108: 90 days after the overlay reached a terminal lifecycle
#: state before we scrub the plaintext.
TRUSTED_EMAIL_NULL_AFTER: Final[timedelta] = timedelta(days=90)


async def _sweep_eligible_rows(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> int:
    """NULL ``email_at_invitation`` for every eligible row past the cutoff.

    A single ``UPDATE ... RETURNING id`` issues both branches of the
    eligibility predicate. The DB-side typing on the
    ``trusteduserstatus`` enum is satisfied by the ``CAST(:expired AS
    trusteduserstatus)`` form already used by
    :mod:`echoroo.workers.trusted_auto_expire`.
    """
    stmt = sa.text(
        """
        UPDATE project_trusted_users
           SET email_at_invitation = NULL,
               updated_at = :now
         WHERE email_at_invitation IS NOT NULL
           AND (
                (status = CAST(:revoked AS trusteduserstatus)
                    AND revoked_at IS NOT NULL
                    AND revoked_at < :cutoff)
             OR (status = CAST(:expired AS trusteduserstatus)
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
            "revoked": "revoked",
            "expired": "expired",
        },
    )
    return len(result.fetchall())


async def _run_sweep(
    *,
    now: datetime | None = None,
    null_after: timedelta = TRUSTED_EMAIL_NULL_AFTER,
) -> dict[str, Any]:
    """Async pipeline backing :func:`sweep_trusted_emails`.

    1. Compute the cutoff (``now - 90d``).
    2. Issue the ``UPDATE ... RETURNING id`` statement.
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
            "trusted_email_null: scrubbed %d trusted overlay email(s) "
            "(cutoff=%s)",
            scrubbed,
            cutoff.isoformat(),
        )
    else:
        logger.debug(
            "trusted_email_null: no rows past cutoff (cutoff=%s)",
            cutoff.isoformat(),
        )
    return {
        "status": "ok",
        "scrubbed": scrubbed,
        "evaluated_at": now_eff.isoformat(),
        "cutoff": cutoff.isoformat(),
    }


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.trusted_email_null.sweep_trusted_emails",
)
def sweep_trusted_emails() -> dict[str, Any]:
    """NULL ``project_trusted_users.email_at_invitation`` 90d after terminal status (FR-108).

    Returns:
        Summary dict with the number of rows scrubbed, e.g.
        ``{"status": "ok", "scrubbed": 4, ...}``.
    """
    return asyncio.run(_run_sweep())


__all__ = [
    "TRUSTED_EMAIL_NULL_AFTER",
    "sweep_trusted_emails",
]
