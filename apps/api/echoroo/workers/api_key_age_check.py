"""Daily API key age sweep (Phase 17 backlog A-4 / FR-083).

The sweep enforces the spec's age-based scope curve on the eager side:

* ``API_KEY_REVOKE_DAYS`` (default 270): rows with
  ``created_at <= now - 270d`` AND ``revoked_at IS NULL`` are flipped
  to ``revoked_at = NOW()``, ``revoked_reason`` is stamped, and
  ``granted_permissions`` is reset to ``[]`` so a row diff in the
  admin UI / DSR export shows the policy explicitly.
* ``API_KEY_SCOPE_DEGRADE_DAYS`` (default 180): rows with
  ``created_at <= now - 180d`` AND ``revoked_at IS NULL`` AND any
  ``granted_permissions`` entry in the canonical write catalogue
  (:data:`echoroo.services.api_key_lifecycle.API_KEY_WRITE_PERMISSIONS`)
  have those entries stripped.

Cadence
-------
01:15 UTC — chosen so the sweep does not collide with the existing
01:00 UTC PII hash backfill (see ``celery_app.py`` ``beat_schedule``).
The 24 h cadence matches FR-083's tolerance for one day's lag; the
verifier-side safety net (:func:`effective_permissions_for_age` invoked
inside :class:`echoroo.services.api_key_verification.DbApiKeyVerifier`)
covers the gap between this beat tick and request time.

Concurrency
-----------
Each branch (revoke / degrade) issues a single
``UPDATE ... RETURNING`` (revoke) or ``SELECT FOR UPDATE SKIP LOCKED``
+ targeted ``UPDATE`` (degrade) so multi-worker contention is wait-free.
The revoke-first ordering avoids a window where a row is degraded *and*
crosses the revoke threshold inside the same tick — by the time
``_degrade_due_keys`` runs, every revoke candidate is already off the
table.

Side effects
------------
Audit + email are emitted **after** the main transaction commits. Each
side-effect runs in its own AsyncSession (audit) or directly via the
Resend wrapper (email). Failures log and continue — the row mutation
already landed and re-running the sweep is a no-op (the WHERE filter
rejects already-revoked / already-degraded rows).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.settings import get_settings
from echoroo.services.api_key_lifecycle import (
    API_KEY_WRITE_PERMISSIONS,
    filter_to_read_only,
)
from echoroo.services.audit_service import AuditLogService
from echoroo.services.email import (
    send_api_key_revoke_email,
    send_api_key_scope_degrade_email,
)
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)


# --- types ------------------------------------------------------------------


class _SweepRow:
    """Lightweight container for post-commit side-effects.

    The beat task fetches each row's salient fields inside the main
    transaction (so the email lookup later does not need a fresh DB
    round-trip per row to read invariant columns) and stashes them in
    this dataclass-shaped object.
    """

    __slots__ = ("api_key_id", "user_id", "prefix", "created_at", "user_email")

    def __init__(
        self,
        *,
        api_key_id: UUID,
        user_id: UUID,
        prefix: str,
        created_at: datetime,
        user_email: str | None,
    ) -> None:
        self.api_key_id = api_key_id
        self.user_id = user_id
        self.prefix = prefix
        self.created_at = created_at
        self.user_email = user_email


# --- atomic UPDATEs ---------------------------------------------------------


async def _revoke_due_keys(
    session: AsyncSession, *, revoke_days: int, now: datetime
) -> list[_SweepRow]:
    """Atomically revoke every row with ``age >= revoke_days``.

    Uses ``UPDATE ... RETURNING`` so only rows that were actually
    flipped (i.e. the row beat the race against a concurrent worker)
    surface to the caller — avoids double-emitting the audit /
    notification side-effects.
    """
    cutoff = now - timedelta(days=revoke_days)
    stmt = sa.text(
        """
        UPDATE api_keys ak
           SET revoked_at = :now,
               revoked_reason = 'api_key_age_check: 270d policy (FR-083)',
               granted_permissions = '[]'::jsonb
          FROM users u
         WHERE u.id = ak.user_id
           AND ak.revoked_at IS NULL
           AND ak.created_at <= :cutoff
        RETURNING ak.id AS api_key_id,
                  ak.user_id AS user_id,
                  ak.prefix AS prefix,
                  ak.created_at AS created_at,
                  u.email AS user_email
        """
    )
    result = await session.execute(stmt, {"cutoff": cutoff, "now": now})
    rows = result.mappings().all()
    return [
        _SweepRow(
            api_key_id=r["api_key_id"],
            user_id=r["user_id"],
            prefix=r["prefix"],
            created_at=r["created_at"],
            user_email=r["user_email"],
        )
        for r in rows
    ]


async def _degrade_due_keys(
    session: AsyncSession, *, degrade_days: int, now: datetime
) -> list[_SweepRow]:
    """Strip write scopes from every row with ``degrade_days <= age``.

    Two-step pattern:
      1. ``SELECT ... FOR UPDATE SKIP LOCKED`` to grab a stable snapshot
         of degrade candidates that another worker is not already
         touching.
      2. Per-row Python filter (cleaner than wrestling JSONB array
         ops in pure SQL) followed by a targeted UPDATE that *also*
         re-asserts ``revoked_at IS NULL`` so a concurrent revoke from
         the prior branch wins the race.

    Rows whose ``granted_permissions`` already lack any write scope are
    skipped — the ``EXISTS`` clause keeps the candidate set tight.
    """
    cutoff = now - timedelta(days=degrade_days)
    write_perms = list(API_KEY_WRITE_PERMISSIONS)

    select_stmt = sa.text(
        """
        SELECT ak.id AS api_key_id,
               ak.user_id AS user_id,
               ak.prefix AS prefix,
               ak.created_at AS created_at,
               ak.granted_permissions AS granted_permissions,
               u.email AS user_email
          FROM api_keys ak
          JOIN users u ON u.id = ak.user_id
         WHERE ak.revoked_at IS NULL
           AND ak.created_at <= :cutoff
           AND EXISTS (
             SELECT 1
               FROM jsonb_array_elements_text(ak.granted_permissions) p(value)
              WHERE p.value = ANY(:write_perms)
           )
         ORDER BY ak.created_at
         FOR UPDATE OF ak SKIP LOCKED
        """
    )
    candidates = await session.execute(
        select_stmt,
        {"cutoff": cutoff, "write_perms": write_perms},
    )
    rows = candidates.mappings().all()

    # Apply the per-row UPDATE with a JSON-encoded payload. The
    # ``revoked_at IS NULL`` re-assertion guards against a concurrent
    # worker that just flipped this row to revoked between our SELECT
    # and our UPDATE.
    sweep_rows: list[_SweepRow] = []
    for r in rows:
        new_perms = list(filter_to_read_only(r["granted_permissions"] or ()))
        await session.execute(
            sa.text(
                """
                UPDATE api_keys
                   SET granted_permissions = CAST(:new_perms AS jsonb)
                 WHERE id = :id
                   AND revoked_at IS NULL
                """
            ),
            {"new_perms": json.dumps(new_perms), "id": r["api_key_id"]},
        )
        sweep_rows.append(
            _SweepRow(
                api_key_id=r["api_key_id"],
                user_id=r["user_id"],
                prefix=r["prefix"],
                created_at=r["created_at"],
                user_email=r["user_email"],
            )
        )
    return sweep_rows


# --- post-commit side effects ----------------------------------------------


async def _emit_revoke_event(row: _SweepRow, *, revoked_at: datetime) -> None:
    """Audit + email after the revoke commit lands."""
    async with AsyncSessionLocal() as audit_session:
        try:
            audit = AuditLogService(audit_session)
            await audit.write_platform_event(
                actor_user_id=None,
                action="api_key.revoke",
                request_id="celery-api-key-age-check",
                ip="0.0.0.0",
                user_agent="celery/api_key_age_check",
                detail={
                    "api_key_id": str(row.api_key_id),
                    "user_id": str(row.user_id),
                    "prefix": row.prefix,
                    "reason": "api_key_age_check: 270d policy (FR-083)",
                    "created_at": row.created_at.isoformat(),
                    "revoked_at": revoked_at.isoformat(),
                },
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            logger.exception(
                "api_key.revoke audit write failed (api_key_id=%s)",
                row.api_key_id,
            )

    if not row.user_email:
        logger.warning(
            "api_key.revoke email skipped — owner has no email "
            "(api_key_id=%s, user_id=%s)",
            row.api_key_id,
            row.user_id,
        )
        return
    try:
        await send_api_key_revoke_email(
            to=row.user_email,
            api_key_prefix=row.prefix,
            created_at_iso=row.created_at.isoformat(),
            revoked_at_iso=revoked_at.isoformat(),
        )
    except Exception:
        logger.exception(
            "api_key.revoke email send failed (api_key_id=%s)",
            row.api_key_id,
        )


async def _emit_degrade_event(
    row: _SweepRow, *, degraded_at: datetime, grace_days: int
) -> None:
    """Audit + email after the degrade commit lands."""
    async with AsyncSessionLocal() as audit_session:
        try:
            audit = AuditLogService(audit_session)
            await audit.write_platform_event(
                actor_user_id=None,
                action="api_key.scope_degrade",
                request_id="celery-api-key-age-check",
                ip="0.0.0.0",
                user_agent="celery/api_key_age_check",
                detail={
                    "api_key_id": str(row.api_key_id),
                    "user_id": str(row.user_id),
                    "prefix": row.prefix,
                    "reason": "api_key_age_check: 180d policy (FR-083)",
                    "created_at": row.created_at.isoformat(),
                    "degraded_at": degraded_at.isoformat(),
                    "grace_days_until_revoke": grace_days,
                },
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            logger.exception(
                "api_key.scope_degrade audit write failed (api_key_id=%s)",
                row.api_key_id,
            )

    if not row.user_email:
        logger.warning(
            "api_key.scope_degrade email skipped — owner has no email "
            "(api_key_id=%s, user_id=%s)",
            row.api_key_id,
            row.user_id,
        )
        return
    try:
        await send_api_key_scope_degrade_email(
            to=row.user_email,
            api_key_prefix=row.prefix,
            created_at_iso=row.created_at.isoformat(),
            degraded_at_iso=degraded_at.isoformat(),
            grace_days_until_revoke=grace_days,
        )
    except Exception:
        logger.exception(
            "api_key.scope_degrade email send failed (api_key_id=%s)",
            row.api_key_id,
        )


# --- async pipeline + Celery entry point ------------------------------------


async def _run() -> dict[str, Any]:
    """Async pipeline backing :func:`api_key_age_check`."""
    settings = get_settings()
    degrade_days = settings.API_KEY_SCOPE_DEGRADE_DAYS
    revoke_days = settings.API_KEY_REVOKE_DAYS
    now = datetime.now(UTC)
    grace_days = max(revoke_days - degrade_days, 0)

    revoked_rows: list[_SweepRow]
    degraded_rows: list[_SweepRow]
    async with AsyncSessionLocal() as session:
        try:
            # Revoke first so a row that crosses both thresholds in
            # one tick is not also reported as a degrade.
            revoked_rows = await _revoke_due_keys(
                session, revoke_days=revoke_days, now=now
            )
            degraded_rows = await _degrade_due_keys(
                session, degrade_days=degrade_days, now=now
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    for row in revoked_rows:
        await _emit_revoke_event(row, revoked_at=now)
    for row in degraded_rows:
        await _emit_degrade_event(row, degraded_at=now, grace_days=grace_days)

    summary: dict[str, Any] = {
        "revoked": len(revoked_rows),
        "degraded": len(degraded_rows),
        "ran_at": now.isoformat(),
    }
    if revoked_rows or degraded_rows:
        logger.info(
            "api_key_age_check tick: revoked=%d degraded=%d",
            summary["revoked"],
            summary["degraded"],
        )
    return summary


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.api_key_age_check.api_key_age_check",
    bind=True,
    max_retries=3,
)
def api_key_age_check(self: Any) -> dict[str, Any]:  # noqa: ARG001
    """Beat-driven entry point for the daily API key age sweep (FR-083)."""
    return asyncio.run(_run())


__all__ = ["api_key_age_check"]
