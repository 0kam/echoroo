"""Daily GC of stale ``user_banner_dismissals`` rows (spec/011 US7 T625, FR-011-309).

Background
----------
:mod:`echoroo.services.user_banner` records a dismissal in
``user_banner_dismissals`` so a banner stops surfacing once the user has
acknowledged it (FR-011-302). The banner-list query
(:func:`echoroo.services.user_banner.list_banners`) is age-capped at
:data:`~echoroo.services.user_banner.DEFAULT_BANNER_MAX_AGE_DAYS` days:
an audit row older than the cap falls out of the banner stack entirely.

Once an audit row has aged past the cap its dismissal row can never
again suppress a *visible* banner — the audit row is no longer eligible
for the banner list regardless of dismissal state. The dismissal row is
therefore dead weight past the boundary, so this daily sweep deletes
dismissals whose ``dismissed_at`` is older than the SAME window.

Window alignment invariant
---------------------------
The GC cutoff is computed from
:data:`echoroo.services.user_banner.DEFAULT_BANNER_MAX_AGE_DAYS` — the
exact constant the banner-list query uses — so the two windows can never
drift. Deleting a dismissal at this boundary cannot resurrect a
still-visible banner because the underlying audit row has, by
construction, already aged out of the banner list.

Schedule
--------
Wired into :data:`echoroo.workers.celery_app.app.conf.beat_schedule`
under ``banner-dismissal-gc-daily`` — fires daily at 03:30 UTC, after
the 03:00 trusted-expiry-notifier so the sequential daily jobs do not
overlap.

Idempotency
-----------
The DELETE filters on ``dismissed_at < cutoff`` so re-running the task on
the same dataset is a no-op once the eligible rows are gone. No audit row
is written: GC of acknowledged-and-expired banner state is automated
bookkeeping, not a human-driven operator action.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from echoroo.core.database import AsyncSessionLocal
from echoroo.services.user_banner import DEFAULT_BANNER_MAX_AGE_DAYS
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


async def _impl(*, now: datetime | None = None) -> dict[str, Any]:
    """Delete dismissals older than the banner age cap and report the count.

    1. Compute the cutoff (``now - DEFAULT_BANNER_MAX_AGE_DAYS``).
    2. Issue a single ``DELETE ... RETURNING user_id``.
    3. Commit so the GC is durable.

    Returns a summary dict suitable for the Celery result backend.
    """
    now_eff = now or datetime.now(UTC)
    cutoff = now_eff - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS)

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                sa.text(
                    "DELETE FROM user_banner_dismissals "
                    "WHERE dismissed_at < :cutoff "
                    "RETURNING user_id"
                ),
                {"cutoff": cutoff},
            )
            deleted = len(result.fetchall())
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    if deleted:
        logger.info(
            "banner_gc: deleted %d stale dismissal(s) (cutoff=%s)",
            deleted,
            cutoff.isoformat(),
        )
    else:
        logger.debug(
            "banner_gc: no dismissals past cutoff (cutoff=%s)",
            cutoff.isoformat(),
        )
    return {
        "status": "ok",
        "deleted": deleted,
        "evaluated_at": now_eff.isoformat(),
        "cutoff": cutoff.isoformat(),
    }


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.banner_gc.gc_user_banner_dismissals",
)
def gc_user_banner_dismissals() -> dict[str, Any]:
    """Delete ``user_banner_dismissals`` older than the banner age cap (T625).

    Returns:
        Summary dict with the number of rows deleted, e.g.
        ``{"status": "ok", "deleted": 4, ...}``.
    """
    return asyncio.run(_impl())


__all__ = ["gc_user_banner_dismissals"]
