"""Celery worker that drains the ``outbox_events`` table (FR-076d, NFR-005).

This module owns the *processing* side of the transactional outbox
implemented by :mod:`echoroo.services.outbox_service`. It is intended to
be run on the ``worker-cpu`` Celery queue with ``-c 4`` (four worker
processes) so that the documented SLO of p95 ≤ 10s and p99 ≤ 60s is met
under expected load (data-model.md §3.18, research.md §6).

Wiring strategy
---------------
The Celery task is declared via :func:`celery.shared_task` so that this
module does not import the application's ``celery_app`` at module-load
time. Phase 3 owns adding the import to
``echoroo.workers.celery_app.app.conf.include`` and the
``app.conf.beat_schedule`` entry that fires this task at 1Hz; this file
only declares the task body and the handler registry.

Handler registry
----------------
Each ``event_type`` (e.g. ``"api_key_revoke_on_member_removal"``) maps
to an async handler ``Callable[[AsyncSession, dict], Awaitable[None]]``
registered via :func:`register_outbox_handler`. The handler receives the
session and the row's ``payload`` dict and is responsible for executing
the side-effect *idempotently* (FR-076a, SC-021). Re-running a handler
with the same ``idempotency_key`` MUST be a no-op — the at-most-once log
guarantee depends on this.

Retry semantics
---------------
The Celery task itself uses ``self.retry`` up to
:data:`echoroo.services.outbox_service.CELERY_TASK_MAX_RETRIES` times
with exponential backoff for transient infrastructure failures (broker
down, DB connection lost). Independently, each row tracks its own
``retry_count`` against
:data:`echoroo.services.outbox_service.MAX_RETRY`; once the row exceeds
that budget the row is moved to ``status='dead_letter'`` and a
PagerDuty alert fires.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.services.outbox_service import (
    CELERY_TASK_MAX_RETRIES,
    DEFAULT_CLAIM_BATCH_SIZE,
    claim_batch,
    mark_done,
    mark_failed,
)

logger = logging.getLogger(__name__)


# -- Handler registry ---------------------------------------------------------

#: Type alias for an outbox event handler. Handlers receive the worker's
#: async session (joined transaction) and the row's payload dict, and are
#: responsible for executing the side-effect idempotently.
OutboxHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]


#: Registry of event_type → handler. Modules that need to react to a
#: specific event type call :func:`register_outbox_handler` at import
#: time. The processor task looks up the handler at row-claim time.
OUTBOX_HANDLERS: dict[str, OutboxHandler] = {}


def register_outbox_handler(event_type: str) -> Callable[[OutboxHandler], OutboxHandler]:
    """Decorator to register a handler for a given event type.

    Example
    -------
    >>> @register_outbox_handler("api_key_revoke_on_member_removal")
    ... async def revoke_keys(session, payload):
    ...     ...
    """

    def _decorator(handler: OutboxHandler) -> OutboxHandler:
        if event_type in OUTBOX_HANDLERS:
            raise ValueError(
                f"outbox handler already registered for event_type={event_type!r}"
            )
        OUTBOX_HANDLERS[event_type] = handler
        return handler

    return _decorator


async def _default_handler(_session: AsyncSession, payload: dict[str, Any]) -> None:
    """Fallback handler that logs and raises ``NotImplementedError``.

    Phase 2.7 intentionally lands the registry without any concrete
    handlers — they are added by the per-feature phases (e.g. API key
    auto-revoke in Phase 7). Until then the default handler raises so a
    misconfigured event_type cannot silently succeed.
    """
    logger.error(
        "outbox event reached default handler — no registered handler for payload keys=%s",
        sorted(payload.keys()),
    )
    raise NotImplementedError(
        "no outbox handler registered for this event_type"
    )


def _resolve_handler(event_type: str) -> OutboxHandler:
    """Look up the handler for ``event_type`` (or the default)."""
    return OUTBOX_HANDLERS.get(event_type, _default_handler)


def _worker_id() -> str:
    """Return an opaque ``host:pid`` identifier for the running worker.

    Recorded in ``outbox_events.last_error`` while a row is in-flight so
    operations can correlate stuck rows with a specific worker process.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


# -- Core async processing loop ----------------------------------------------


async def _process_one(
    session: AsyncSession,
    row: dict[str, Any],
) -> None:
    """Run the registered handler for a single claimed row.

    The function does **not** commit — the caller controls the
    transaction so that handler effects + ``mark_done`` either both
    commit or both roll back. On handler failure, the function calls
    :func:`mark_failed` with the current ``retry_count`` so the row is
    rescheduled or dead-lettered as appropriate, and re-raises so the
    Celery task can retry transient errors.
    """
    event_id: UUID = row["id"]
    event_type: str = row["event_type"]
    payload: dict[str, Any] = row["payload"] or {}
    retry_count: int = int(row.get("retry_count", 0))

    handler = _resolve_handler(event_type)
    try:
        await handler(session, payload)
    except Exception as exc:
        await mark_failed(
            session,
            event_id,
            error=f"{type(exc).__name__}: {exc}",
            current_retry_count=retry_count,
        )
        raise
    await mark_done(session, event_id)


async def _drain_batch(
    session_factory: Callable[[], AsyncSession],
    *,
    batch_size: int,
    worker_id: str,
) -> int:
    """Claim a batch and process each row in its own transaction.

    Returns the number of rows successfully processed (i.e. ``mark_done``
    committed). A row whose handler raises does NOT count toward the
    return value — the failure is logged and the row is rescheduled.
    """
    # Step 1: claim a batch in its own short transaction so other workers
    # can immediately see the rows as ``processing`` and skip them.
    async with session_factory() as claim_session, claim_session.begin():
        claimed = await claim_batch(
            claim_session, batch_size=batch_size, worker_id=worker_id
        )

    if not claimed:
        return 0

    # Step 2: process each row in its own transaction. We deliberately do
    # NOT batch the handler effects together — a single bad row should
    # not poison the rest of the batch.
    successful = 0
    for row in claimed:
        async with session_factory() as work_session:
            try:
                async with work_session.begin():
                    await _process_one(work_session, row)
                successful += 1
            except Exception as exc:  # noqa: BLE001 -- logged + counted, loop continues
                logger.warning(
                    "outbox row %s (event_type=%s) failed: %s",
                    row.get("id"),
                    row.get("event_type"),
                    exc,
                )
    return successful


# -- Celery task entry point -------------------------------------------------


@shared_task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.outbox_processor.process_outbox_batch",
    queue="worker-cpu",
    bind=True,
    max_retries=CELERY_TASK_MAX_RETRIES,
    default_retry_delay=2,
    acks_late=True,
)
def process_outbox_batch(self: Any, batch_size: int = DEFAULT_CLAIM_BATCH_SIZE) -> dict[str, Any]:
    """Drain up to ``batch_size`` outbox rows once.

    Concurrency
    -----------
    Deploy with ``celery -A echoroo.workers.celery_app worker -Q worker-cpu -c 4``
    so that 4 worker processes poll concurrently. The
    ``SELECT ... FOR UPDATE SKIP LOCKED`` semantics in
    :func:`echoroo.services.outbox_service.claim_batch` ensure no two
    workers ever lease the same row.

    SLO
    ---
    p95 ≤ 10s, p99 ≤ 60s end-to-end (data-model.md §3.18, FR-076d). At
    1Hz polling and 4 concurrent workers the system handles ~200
    events/sec at the documented batch size.

    Returns
    -------
    Summary dict with ``processed`` (rows that completed cleanly) and
    ``worker_id`` (host:pid). Used by tests + dashboards.
    """
    # Local imports so the module is importable even when the worker DB
    # engine is not yet initialised (mirrors workers/audit_log_export.py).
    from echoroo.workers.db_utils import get_worker_engine_and_session_factory

    _, session_factory = get_worker_engine_and_session_factory()

    worker_id = _worker_id()

    try:
        processed = asyncio.run(
            _drain_batch(
                session_factory,
                batch_size=batch_size,
                worker_id=worker_id,
            )
        )
    except Exception as exc:  # noqa: BLE001 -- routed through Celery retry below
        # Transient infrastructure failure (broker down, DB connection
        # lost). Use Celery's retry path with exponential backoff
        # 2**retries seconds; the per-row retry_count is independent and
        # tracked by the outbox itself.
        countdown = 2**self.request.retries
        logger.warning(
            "outbox processor transient failure, retrying in %ds: %s",
            countdown,
            exc,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc

    return {"processed": processed, "worker_id": worker_id}


__all__ = [
    "OUTBOX_HANDLERS",
    "OutboxHandler",
    "process_outbox_batch",
    "register_outbox_handler",
]
