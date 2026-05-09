"""Pure helpers for dormancy notification payload + idempotency key construction.

Extracted from :mod:`echoroo.workers.dormancy_check` to make payload
structure and idempotency-key format directly unit-testable, supporting
Phase 17 §D-1-bis mutation score uplift (74.6% → >=80%).

These helpers are deliberately free of session / I/O so the mutation
fuzzer can exercise every literal that drives an outbound side effect
without spinning up a Celery worker or a live PostgreSQL connection.

The functions are import-cycle safe: they receive the mutable
``Project`` / ``User`` ORM rows as opaque attribute carriers and do not
import from :mod:`echoroo.workers.dormancy_check`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from echoroo.models.project import Project
from echoroo.models.user import User
from echoroo.workers._dormancy_payload_sanitiser import sanitise_field


def build_notification_payload(
    stage: str,
    project: Project,
    owner: User,
    now: datetime,
) -> dict[str, Any]:
    """Construct the dormancy notification payload (pure function).

    Returns a dict with the seven canonical fields the dispatcher and
    the FR-076a outbox contract rely on. Each value is run through the
    shared :func:`sanitise_field` helper so the dispatcher side never
    sees control characters or unbounded strings.

    The ``dormant_since`` field is the ISO-8601 representation of
    ``project.dormant_since`` (empty string when None — the caller is
    expected to validate non-None before invoking, see
    :func:`compute_idempotency_key`).
    """
    dormant_since_iso = (
        project.dormant_since.isoformat() if project.dormant_since else ""
    )
    return {
        "stage": sanitise_field(stage, field_name="stage"),
        "project_id": sanitise_field(project.id, field_name="project_id"),
        "project_name": sanitise_field(project.name, field_name="project_name"),
        "owner_user_id": sanitise_field(owner.id, field_name="owner_user_id"),
        "owner_email": sanitise_field(owner.email, field_name="owner_email"),
        "dormant_since": sanitise_field(
            dormant_since_iso, field_name="dormant_since"
        ),
        "evaluated_at": sanitise_field(now.isoformat(), field_name="evaluated_at"),
    }


def compute_idempotency_key(
    project_id: UUID,
    dormant_since: datetime,
    stage: str,
) -> str:
    """Construct the dormancy outbox idempotency key (pure function).

    Format: ``dormancy:{project_id}:{dormant_since_unix}:{stage}``.

    The UNIX-second timestamp of ``dormant_since`` is embedded so each
    dormancy episode lives in a fresh key namespace — when a project
    re-enters DORMANT after a restore, ``dormant_since`` advances and
    every subsequent stage gets a brand-new key, while every beat tick
    inside the same episode lands on an identical key (ON CONFLICT DO
    NOTHING is a no-op).
    """
    dormant_since_unix = int(dormant_since.timestamp())
    return f"dormancy:{project_id}:{dormant_since_unix}:{stage}"


__all__ = [
    "build_notification_payload",
    "compute_idempotency_key",
]
