"""Celery beat task for the admin 2FA reset dispatch poller (Phase 17 A-11).

The poller runs every 5 minutes (see ``celery_app.py`` ``beat_schedule``)
and walks ``two_factor_reset_requests`` for rows that have crossed
``dispatch_at``. Each due row is processed inside its own transaction
with ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple worker-cpu
processes can co-exist without dispatching the same row twice.

The bulk of the logic lives in
:func:`echoroo.services.two_factor_reset_service.run_dispatch_due_requests`;
this module is a thin Celery wrapper that opens an ``AsyncSession`` and
runs the coroutine via :func:`asyncio.run` (matching the dormancy /
trusted-expiry workers' pattern).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from echoroo.core.database import AsyncSessionLocal
from echoroo.services.two_factor_reset_service import run_dispatch_due_requests
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


async def _run() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        summary = await run_dispatch_due_requests(session)
        return {
            "inspected": summary.inspected,
            "applied": summary.applied,
            "cancelled": summary.cancelled,
            "expired": summary.expired,
            "failed": summary.failed,
        }


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.two_factor_tasks.dispatch_due_two_factor_resets",
    bind=True,
    max_retries=3,
)
def dispatch_due_two_factor_resets(self: Any) -> dict[str, Any]:  # noqa: ARG001
    """Beat-driven entry point for the 2FA reset dispatch poller."""
    summary = asyncio.run(_run())
    if summary["inspected"]:
        logger.info(
            "two_factor_reset dispatch tick: inspected=%d applied=%d "
            "cancelled=%d expired=%d failed=%d",
            summary["inspected"],
            summary["applied"],
            summary["cancelled"],
            summary["expired"],
            summary["failed"],
        )
    return summary


__all__ = ["dispatch_due_two_factor_resets"]
