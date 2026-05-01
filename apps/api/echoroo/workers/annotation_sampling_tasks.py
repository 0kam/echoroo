"""Celery task for materializing :class:`AnnotationSegment` rows.

Given an :class:`AnnotationSet` whose filters and geometry are already
persisted (``segment_length_sec``, ``num_segments``, optional date and
time-of-day filters), this task:

1. Fetches candidate recordings from the owning dataset, filtered by
   ``datetime`` (date filter) and local time-of-day (if present).
2. Enumerates the set of contiguous, non-overlapping ``(recording_id,
   start_time_sec)`` slots that can fit a ``segment_length_sec`` window.
3. Uniformly samples ``num_segments`` slots without replacement.
4. Bulk-inserts the resulting segments and marks the set as ``ready``.

Queue routing
-------------
The task is intentionally dispatched to the default Celery queue which in
the development ``compose.dev.yaml`` is served by the ``worker-cpu``
container (see ``memory/celery-workers.md``). There is no GPU work here;
everything is pure Python + SQL.

Idempotency
-----------
The task refuses to run when the target set already has segments; the
service layer is expected to guard against re-dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# Slot candidates use a step equal to the segment length (i.e. non-overlapping
# contiguous buckets starting at t=0). This keeps the candidate pool small and
# guarantees no two sampled segments overlap inside a single recording.
_SLOT_STEP_MULTIPLIER = 1.0


# ---------------------------------------------------------------------------
# Celery task definition
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.annotation_sampling_tasks.sample_annotation_segments",
    time_limit=600,
    soft_time_limit=540,
)
def sample_annotation_segments(_self: Any, annotation_set_id: str) -> dict[str, Any]:
    """Materialize ground-truth segments for an AnnotationSet.

    Args:
        annotation_set_id: UUID string of the target
            :class:`AnnotationSet` (status MUST be ``sampling``).

    Returns:
        Dict summarising the result: ``{"annotation_set_id", "created",
        "target", "warning"}``.
    """
    return asyncio.run(_sample_annotation_segments(annotation_set_id))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _sample_annotation_segments(annotation_set_id: str) -> dict[str, Any]:
    """Async implementation of the sampling task."""
    from echoroo.models.annotation_set import AnnotationSegment, AnnotationSet
    from echoroo.models.enums import AnnotationSetStatus
    from echoroo.models.recording import Recording

    set_uuid = UUID(annotation_set_id)
    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            # --------------------------------------------------------------
            # 1. Load and validate the AnnotationSet
            # --------------------------------------------------------------
            result = await db.execute(
                select(AnnotationSet).where(AnnotationSet.id == set_uuid)
            )
            anno_set = result.scalar_one_or_none()
            if anno_set is None:
                raise ValueError(f"AnnotationSet not found: {annotation_set_id}")

            # Refuse to overwrite existing segments — the service layer is
            # expected to have cleared them or to 409-reject retries.
            existing_count_stmt = (
                select(func.count())
                .select_from(AnnotationSegment)
                .where(AnnotationSegment.annotation_set_id == set_uuid)
            )
            existing_count = int(
                (await db.execute(existing_count_stmt)).scalar_one()
            )
            if existing_count > 0:
                logger.warning(
                    "Sampling task aborted: set %s already has %d segments",
                    annotation_set_id,
                    existing_count,
                )
                raise ValueError(
                    f"AnnotationSet {annotation_set_id} already has segments; "
                    "delete them before re-sampling.",
                )

            dataset_id = anno_set.dataset_id
            segment_length = float(anno_set.segment_length_sec)
            target_count = int(anno_set.num_segments)
            date_filter = anno_set.filter_date_range
            tod_filter = anno_set.filter_time_of_day_range

            # --------------------------------------------------------------
            # 2. Fetch candidate recordings (dataset + date filter applied in SQL)
            # --------------------------------------------------------------
            rec_stmt = select(
                Recording.id,
                Recording.duration,
                Recording.time_expansion,
                Recording.datetime,
            ).where(Recording.dataset_id == dataset_id)

            if date_filter is not None:
                start_str = date_filter.get("start")
                end_str = date_filter.get("end")
                if start_str:
                    start_dt = datetime.fromisoformat(start_str).replace(tzinfo=UTC)
                    rec_stmt = rec_stmt.where(Recording.datetime >= start_dt)
                if end_str:
                    # Inclusive end-of-day: use <= end + 1 day exclusive
                    end_dt = datetime.fromisoformat(end_str).replace(tzinfo=UTC)
                    rec_stmt = rec_stmt.where(Recording.datetime <= end_dt.replace(
                        hour=23, minute=59, second=59, microsecond=999999,
                    ))

            rec_rows = (await db.execute(rec_stmt)).all()

            # Apply time-of-day filter in Python (handles wrap-around cleanly).
            tod_start: dt_time | None = None
            tod_end: dt_time | None = None
            if tod_filter is not None:
                tod_start = _parse_hhmm(tod_filter.get("start"))
                tod_end = _parse_hhmm(tod_filter.get("end"))

            # --------------------------------------------------------------
            # 3. Enumerate candidate (recording_id, slot_start) tuples
            # --------------------------------------------------------------
            slots: list[tuple[UUID, float, float]] = []
            for rec_id, duration, time_expansion, rec_dt in rec_rows:
                if duration is None or duration <= 0:
                    continue
                if (
                    rec_dt is not None
                    and tod_start is not None
                    and tod_end is not None
                    and not _time_in_range(rec_dt.time(), tod_start, tod_end)
                ):
                    continue
                effective = float(duration) * float(time_expansion or 1.0)
                if effective < segment_length:
                    continue
                step = segment_length * _SLOT_STEP_MULTIPLIER
                t = 0.0
                while t + segment_length <= effective + 1e-6:
                    slots.append((rec_id, t, t + segment_length))
                    t += step

            if not slots:
                anno_set.status = AnnotationSetStatus.READY
                anno_set.sampling_warning = (
                    "No recordings matched the configured filters; the set was "
                    "created with zero segments."
                )
                await db.commit()
                return {
                    "annotation_set_id": annotation_set_id,
                    "created": 0,
                    "target": target_count,
                    "warning": anno_set.sampling_warning,
                }

            # --------------------------------------------------------------
            # 4. Uniformly sample without replacement
            # --------------------------------------------------------------
            rng = random.Random()
            sample_size = min(target_count, len(slots))
            chosen = rng.sample(slots, sample_size)

            # --------------------------------------------------------------
            # 5. Bulk insert and flip status to READY
            # --------------------------------------------------------------
            rows = [
                AnnotationSegment(
                    annotation_set_id=set_uuid,
                    recording_id=rec_id,
                    start_time_sec=float(start_t),
                    end_time_sec=float(end_t),
                )
                for rec_id, start_t, end_t in chosen
            ]
            db.add_all(rows)

            warning: str | None = None
            if sample_size < target_count:
                warning = (
                    f"Only {sample_size} of {target_count} segments were "
                    "available after filters."
                )

            anno_set.status = AnnotationSetStatus.READY
            anno_set.sampling_warning = warning
            await db.commit()

            logger.info(
                "Sampling completed: set=%s created=%d target=%d warning=%s",
                annotation_set_id,
                sample_size,
                target_count,
                warning,
            )

            return {
                "annotation_set_id": annotation_set_id,
                "created": sample_size,
                "target": target_count,
                "warning": warning,
            }
    except Exception:
        # Best-effort rollback of status. A fresh session is used because the
        # exception may have poisoned the primary transaction.
        logger.exception(
            "Sampling task failed for set %s; attempting status rollback",
            annotation_set_id,
        )
        try:
            async with session_factory() as db2:
                from echoroo.models.annotation_set import AnnotationSet as _Set
                from echoroo.models.enums import AnnotationSetStatus as _Status

                rollback_result = await db2.execute(
                    select(_Set).where(_Set.id == set_uuid)
                )
                rollback_row = rollback_result.scalar_one_or_none()
                if rollback_row is not None and rollback_row.status == _Status.SAMPLING:
                    rollback_row.sampling_warning = (
                        "Sampling failed; see worker logs for details."
                    )
                    await db2.commit()
        except Exception:  # pragma: no cover - rollback best effort
            logger.exception(
                "Failed to persist sampling failure state for set %s",
                annotation_set_id,
            )
        raise
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_hhmm(value: str | None) -> dt_time | None:
    """Parse a ``HH:MM`` string into a :class:`datetime.time`.

    Returns ``None`` for ``None`` or empty input so callers can treat the
    filter as inactive on that side.
    """
    if not value:
        return None
    try:
        hh, mm = value.split(":", 1)
        return dt_time(hour=int(hh), minute=int(mm))
    except (ValueError, AttributeError):
        logger.warning("Invalid HH:MM time-of-day value: %r", value)
        return None


def _time_in_range(
    t: dt_time, start: dt_time, end: dt_time,
) -> bool:
    """Return True if ``t`` falls within ``[start, end]``, handling wrap-around.

    When ``start <= end`` the range is the usual closed interval. When
    ``start > end`` (e.g. ``22:00`` - ``02:00``) the range wraps past midnight
    and matches ``t >= start OR t <= end``.
    """
    if start <= end:
        return start <= t <= end
    return t >= start or t <= end
