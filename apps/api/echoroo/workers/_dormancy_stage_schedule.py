"""Pure helpers for dormancy follow-up stage scheduling.

Extracted from :mod:`echoroo.workers.dormancy_check._emit_followup_stages`
to make the elapsed-time comparisons directly unit-testable, supporting
Phase 17 §D-1-bis mutation score uplift (74.6% → >=80%).

The scheduler is deliberately session-free: it consumes only two
``datetime`` values and the static ``STAGE_OFFSETS`` mapping (which
also lives here as the single source of truth — :mod:`dormancy_check`
re-exports it).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

#: FR-060: 366 days (1 year + 1 day grace) before the dormancy episode
#: hands off to the superuser archive review queue. The Celery worker
#: surface re-exports this as ``DORMANT_THRESHOLD_SECONDS`` so existing
#: callers do not need to update their import paths.
DORMANT_THRESHOLD_SECONDS: Final[int] = 31_622_400

#: Notification stage offsets relative to ``Project.dormant_since``.
#: Spec FR-060: 3 + 30 + 7 = 40-day grace window before the final
#: superuser-review handoff. ``stage_initial`` fires on detection day
#: (handled by :func:`_flip_to_dormant`); the rest fire on later beat
#: ticks via :func:`compute_ready_stages`.
STAGE_OFFSETS: Final[dict[str, timedelta]] = {
    "stage_initial": timedelta(days=0),
    "stage_3d": timedelta(days=3),
    "stage_30d": timedelta(days=30),
    "stage_final": timedelta(days=37),  # 30 + 7
    "stage_grace_expired": timedelta(seconds=DORMANT_THRESHOLD_SECONDS),
}


def compute_ready_stages(
    now: datetime,
    dormant_since: datetime,
) -> list[str]:
    """Return follow-up stages that should fire given elapsed dormancy.

    Iterates :data:`STAGE_OFFSETS` in declaration order, skipping
    ``stage_initial`` (handled at flip time, not by this scheduler), and
    yields each stage whose offset has elapsed (``elapsed >= offset``).

    The comparison is intentionally inclusive of the boundary: a stage
    with offset ``timedelta(days=3)`` fires the moment
    ``now - dormant_since`` crosses 3 d (matches the historic
    ``elapsed < offset → continue`` filter).
    """
    elapsed = now - dormant_since
    ready: list[str] = []
    for stage, offset in STAGE_OFFSETS.items():
        if stage == "stage_initial":
            continue
        if elapsed < offset:
            continue
        ready.append(stage)
    return ready


__all__ = [
    "DORMANT_THRESHOLD_SECONDS",
    "STAGE_OFFSETS",
    "compute_ready_stages",
]
