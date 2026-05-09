"""Dormancy detection worker (Phase 12 / T701, FR-060 / SC-008).

A daily Celery task scans the projects table for Owners that have not
exhibited *first-party* activity within the FR-060 window (``366d``,
``SystemSettings.dormant_threshold_seconds = 31_622_400``) and:

1. Flips ``Project.status`` from ``ACTIVE`` → ``DORMANT`` when the Owner
   first crosses the threshold and stamps ``Project.dormant_since``.
2. Enqueues a series of staged notification rows in ``outbox_events``:
   ``stage_initial`` (immediately on detection),
   ``stage_30d`` (30 days after ``dormant_since``),
   ``stage_final`` (37 days = 30 + 7 day reminder),
   ``stage_grace_expired`` (366 days; flagged for superuser archive
   review — auto-archive is intentionally deferred).
3. Leaves the actual email dispatch to a separate outbox dispatcher
   (Phase 13+) — this worker only writes the row so the FR-076a
   transactional outbox guarantees apply.

Activity calculation (FR-060)
-----------------------------
``dormant_threshold = max(users.last_login_at, users.last_first_party_activity_at)``.
The Owner is dormant when the most recent of the two timestamps falls
older than ``now - 366d`` (Phase 12 R1 Major M3). When both columns are
NULL we fall back to ``users.created_at`` so a freshly registered user
who never logs in does NOT escape dormancy on a technicality. This
keeps parity with the spec wording and makes the SQL filter robust
against API-only callers that update ``last_login_at`` but leave
``last_first_party_activity_at`` NULL forever.

Single-worker invariant
-----------------------
``pg_try_advisory_xact_lock`` guards against double-fires (Celery beat
+ a manual dispatch in the same minute). A failed acquire is logged and
returns a no-op success — the next beat tick handles it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import ProjectStatus
from echoroo.models.project import Project
from echoroo.models.user import User
from echoroo.services.outbox_service import enqueue
from echoroo.workers._dormancy_events import (
    build_notification_payload,
    compute_idempotency_key,
)

# Backward-compat re-exports: ``DormancyPayloadError`` was previously
# defined inline here; ``_sanitise_field`` was a module-private helper
# that some unit tests reach into. Phase 17 §D-1-bis lifted both into
# :mod:`echoroo.workers._dormancy_payload_sanitiser` (the helper module
# the new ``_dormancy_events`` builder consumes). Re-import them here
# so ``from echoroo.workers.dormancy_check import DormancyPayloadError``
# keeps working for callers and tests.
from echoroo.workers._dormancy_payload_sanitiser import (
    DormancyPayloadError as DormancyPayloadError,  # noqa: PLC0414 - public re-export
)
from echoroo.workers._dormancy_payload_sanitiser import (
    sanitise_field as _sanitise_field,  # noqa: F401 - public re-export
)
from echoroo.workers._dormancy_stage_schedule import (
    DORMANT_THRESHOLD_SECONDS as DORMANT_THRESHOLD_SECONDS,  # noqa: PLC0414
)
from echoroo.workers._dormancy_stage_schedule import (
    STAGE_OFFSETS as STAGE_OFFSETS,  # noqa: PLC0414
)
from echoroo.workers._dormancy_stage_schedule import compute_ready_stages
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables (mirrored from data-model.md §3.19 SystemSettings defaults)
# ---------------------------------------------------------------------------
#
# ``DORMANT_THRESHOLD_SECONDS`` and ``STAGE_OFFSETS`` are owned by
# :mod:`echoroo.workers._dormancy_stage_schedule` (Phase 17 §D-1-bis
# helper extraction) — re-exported here so existing callers do not have
# to update their import paths.

#: Outbox event_type discriminator. A single discriminator with a
#: ``stage`` payload field keeps the dispatcher table small (Phase 13+
#: implements the per-stage email template selection).
OUTBOX_EVENT_DORMANCY: Final[str] = "project.dormancy_notification"

#: Advisory-lock key (folded SHA-256 prefix → 63-bit non-negative int).
#: Mirrors the pattern used by :mod:`echoroo.workers.iucn_sync` so the
#: two single-shot daily workers cannot both starve the connection pool.
_DORMANCY_CHECK_LOCK_KEY: Final[int] = (
    int.from_bytes(hashlib.sha256(b"dormancy_check").digest()[:8], "big")
    & 0x7FFFFFFFFFFFFFFF
)

# ---------------------------------------------------------------------------
# Public API — async pipeline
# ---------------------------------------------------------------------------


async def _try_acquire_lock(session: AsyncSession) -> bool:
    """Attempt the daily-lock; return True iff acquired."""
    result = await session.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:k)"),
        {"k": _DORMANCY_CHECK_LOCK_KEY},
    )
    return bool(result.scalar_one())


async def _scan_active_projects(
    session: AsyncSession,
    *,
    cutoff: datetime,
) -> list[tuple[Project, User]]:
    """Return the ``(project, owner)`` pairs whose Owner has crossed the cutoff.

    The query is intentionally a single round-trip with eager-loaded
    Owner so the worker does not N+1 the user table. We only consider
    ``ProjectStatus.ACTIVE`` rows — already-dormant projects are
    re-evaluated by :func:`_emit_followup_stages`.
    """
    # FR-060 (Phase 12 R1 M3): the Owner is dormant when
    #   GREATEST(last_login_at, last_first_party_activity_at) < cutoff
    # We coalesce each column to ``users.created_at`` so a brand-new user
    # that has never logged in or hit a first-party endpoint still trips
    # the cutoff on schedule (the spec wording forbids "registered last
    # week, never came back" from escaping dormancy detection).
    cutoff_metric = sa.func.greatest(
        sa.func.coalesce(User.last_login_at, User.created_at),
        sa.func.coalesce(User.last_first_party_activity_at, User.created_at),
    )
    stmt = (
        sa.select(Project, User)
        .join(User, User.id == Project.owner_id)
        .where(
            Project.status == ProjectStatus.ACTIVE,
            cutoff_metric < cutoff,
        )
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def _flip_to_dormant(
    session: AsyncSession,
    *,
    project: Project,
    owner: User,
    now: datetime,
) -> bool:
    """Mark ``project`` dormant + enqueue ``stage_initial`` notification.

    Returns True iff a state change actually occurred (caller can use
    the bool to drive metrics). The function is idempotent: a row that
    is already dormant returns False and does not re-enqueue.
    """
    # ``lazyload`` on the ``owner`` relationship suppresses the LEFT
    # OUTER JOIN that SQLAlchemy would otherwise emit; PostgreSQL
    # rejects ``FOR UPDATE`` on the nullable side of an outer join.
    locked_stmt = (
        sa.select(Project)
        .options(lazyload(Project.owner))
        .where(Project.id == project.id)
        .with_for_update()
    )
    locked = (await session.execute(locked_stmt)).scalar_one()
    if locked.status != ProjectStatus.ACTIVE:
        return False

    locked.status = ProjectStatus.DORMANT
    locked.dormant_since = now
    locked.updated_at = now

    await _enqueue_stage(
        session,
        project=locked,
        owner=owner,
        stage="stage_initial",
        now=now,
    )
    return True


async def _enqueue_stage(
    session: AsyncSession,
    *,
    project: Project,
    owner: User,
    stage: str,
    now: datetime,
) -> None:
    """Insert a single dormancy-notification row into ``outbox_events``."""
    if stage not in STAGE_OFFSETS:
        raise ValueError(f"unknown dormancy stage {stage!r}")

    # FR-076a idempotency (Phase 12 R2 Major fix): per (project,
    # dormant_since, stage) — not just per (project, stage). The R1
    # design used a fixed key per project+stage so each stage fired at
    # most ONCE during a dormancy episode, but it also blocked
    # notifications when the same project re-entered DORMANT after a
    # restore (legacy outbox row would shadow every future episode).
    # Embedding the UNIX-second timestamp of ``dormant_since`` makes
    # each dormancy episode get a fresh key namespace while keeping
    # within-episode dedupe (every beat tick during the same episode
    # produces the same key → ON CONFLICT DO NOTHING is a no-op).
    if project.dormant_since is None:  # pragma: no cover — defensive
        # _emit_followup_stages already filters NULL dormant_since rows.
        # ``_enter_dormancy`` always sets dormant_since BEFORE calling
        # this helper, so this branch only triggers on explicit misuse.
        raise ValueError(
            f"_enqueue_stage requires dormant_since to be set "
            f"(project_id={project.id})"
        )

    payload = build_notification_payload(
        stage=stage,
        project=project,
        owner=owner,
        now=now,
    )
    idempotency_key = compute_idempotency_key(
        project_id=project.id,
        dormant_since=project.dormant_since,
        stage=stage,
    )
    await enqueue(
        session,
        event_type=OUTBOX_EVENT_DORMANCY,
        payload=payload,
        idempotency_key=idempotency_key,
    )


async def _emit_followup_stages(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    """Enqueue follow-up stages for already-dormant projects.

    Walks every ``ProjectStatus.DORMANT`` row and, for each stage offset
    in :data:`STAGE_OFFSETS` (excluding ``stage_initial``), checks
    whether ``dormant_since + offset`` has elapsed. The per-episode
    idempotency key in :func:`_enqueue_stage` (scoped to
    ``project_id`` + ``dormant_since`` UNIX-second + ``stage``) ensures
    each stage fires exactly once per dormancy episode: every beat
    tick during the same episode produces an identical key (ON CONFLICT
    DO NOTHING is a no-op), and a restored project re-entering DORMANT
    receives a fresh key namespace because ``dormant_since`` advances.

    Returns the count of newly-enqueued rows.
    """
    stmt = (
        sa.select(Project, User)
        .join(User, User.id == Project.owner_id)
        .where(Project.status == ProjectStatus.DORMANT)
    )
    rows = (await session.execute(stmt)).all()
    enqueued = 0
    for project, owner in rows:
        if project.dormant_since is None:
            # Defensive: an inconsistent row (DORMANT without timestamp)
            # cannot drive the stage schedule; skip and let an operator
            # repair it manually.
            logger.warning(
                "dormancy_check: project %s in DORMANT state without "
                "dormant_since — skipping",
                project.id,
            )
            continue
        # ``compute_ready_stages`` owns the elapsed-time comparison +
        # ``stage_initial`` skip; the per-episode idempotency key
        # produced by :func:`_enqueue_stage` makes this an UPSERT — every
        # subsequent beat tick during the same dormancy episode is a
        # no-op, while a restored project re-entering DORMANT lands in
        # a fresh key namespace.
        for stage in compute_ready_stages(now=now, dormant_since=project.dormant_since):
            await _enqueue_stage(
                session,
                project=project,
                owner=owner,
                stage=stage,
                now=now,
            )
            enqueued += 1
    return enqueued


async def run_dormancy_check(
    *,
    now: datetime | None = None,
    threshold_seconds: int = DORMANT_THRESHOLD_SECONDS,
) -> dict[str, Any]:
    """Run a single dormancy-evaluation pass.

    Splits the work across:

    1. Acquire the daily advisory lock (single-worker invariant).
    2. Scan ACTIVE projects whose Owner has crossed the threshold and
       flip them to DORMANT (writes ``stage_initial`` notification).
    3. Walk DORMANT projects and enqueue any matured follow-up stages.

    Returns a summary dict suitable for the Celery result backend.
    """
    now_eff = now or datetime.now(UTC)
    cutoff = now_eff - timedelta(seconds=threshold_seconds)

    flipped = 0
    followups = 0
    async with AsyncSessionLocal() as session:
        try:
            if not await _try_acquire_lock(session):
                logger.info(
                    "dormancy_check: another worker holds the daily lock — skipping",
                )
                return {
                    "status": "skipped",
                    "reason": "lock_contended",
                    "flipped": 0,
                    "followups": 0,
                }

            # Step 1: ACTIVE → DORMANT transitions.
            candidates = await _scan_active_projects(session, cutoff=cutoff)
            for project, owner in candidates:
                if await _flip_to_dormant(
                    session, project=project, owner=owner, now=now_eff
                ):
                    flipped += 1

            # Step 2: follow-up stages for already-DORMANT rows.
            followups = await _emit_followup_stages(session, now=now_eff)

            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return {
        "status": "ok",
        "flipped": flipped,
        "followups": followups,
        "evaluated_at": now_eff.isoformat(),
    }


# ---------------------------------------------------------------------------
# Celery task entry-point
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.dormancy_check.run_daily_dormancy_check",
    bind=True,
    max_retries=3,
)
def run_daily_dormancy_check(self: Any) -> dict[str, Any]:  # noqa: ARG001 - bound task
    """Daily Celery task wrapper around :func:`run_dormancy_check`.

    Beat schedules the task at 00:00 UTC (see ``celery_app.py``). The
    function runs the async pipeline via :func:`asyncio.run` so the
    Celery worker process does not need to manage an event loop.
    """
    return asyncio.run(run_dormancy_check())


__all__ = [
    "DORMANT_THRESHOLD_SECONDS",
    "DormancyPayloadError",
    "OUTBOX_EVENT_DORMANCY",
    "STAGE_OFFSETS",
    "run_daily_dormancy_check",
    "run_dormancy_check",
]
