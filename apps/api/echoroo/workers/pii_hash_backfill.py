"""Daily PII hash dual-write backfill (Phase 17 backlog A-2 / FR-091b).

Background
----------
When operators flip on the v2 PII hash CMK by setting
``AWS_KMS_CMK_PII_HASH_ALIAS_V2`` (see :mod:`echoroo.core.kms`),
new audit and invitation rows immediately persist both the v1 and
v2 hashes. Existing rows still carry only ``email_hash`` (legacy
Python HMAC) and ``actor_user_id_hash`` / ``ip_hash`` /
``user_agent_hash`` (KMS v1) — without backfill they would only be
discoverable via the v1 fallback path in
:func:`echoroo.core.kms.verify_pii_hash`, which is fine for
correctness but defeats the purpose of the rotation.

This worker fills ``email_hash_v2`` for invitation rows that still
have ``email`` plaintext (i.e. have NOT yet been swept by the
GDPR null-out job in
:mod:`echoroo.workers.invitation_email_null`). Audit rows are
intentionally NOT backfilled: their actor / ip / user-agent
plaintext is never persisted, so the v2 hash is unrecoverable —
historical chain validation continues to use the v1 column, and
search falls back to the v1 path.

Schedule
--------
Wired into :data:`echoroo.workers.celery_app.app.conf.beat_schedule`
under ``pii-hash-backfill-daily`` — fires daily at 01:00 UTC,
ahead of the GBIF (02:00), invitation-email-null (02:30) and
trusted-email-null (02:45) sweeps so the rotation pass always sees
plaintext rows before GDPR scrubs them.

Idempotency
-----------
The UPDATE filters on ``email_hash_v2 IS NULL`` so re-running the
task is a no-op once a row has been processed. Batches of 1000
keep one transaction's lock footprint bounded; subsequent ticks
fan out across additional batches without coordination.

Single-key mode (``AWS_KMS_CMK_PII_HASH_ALIAS_V2`` unset) is a
no-op fast-path: ``compute_pii_hash_dual`` would return only ``v1``
and the writer below skips the UPDATE. We log the skip at DEBUG.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.kms import compute_pii_hash_dual, get_pii_hash_version
from echoroo.services.invitation_service import _canonical_email
from echoroo.workers.celery_app import app

logger = logging.getLogger(__name__)

#: Per-batch row cap. Tuned to keep the implicit row-level lock
#: window inside one transaction comfortably under 1 second under
#: production-typical KMS p99 latency (≈5 ms / row).
_BATCH_SIZE: Final[int] = 1000


async def _backfill_invitation_batch(session: AsyncSession) -> int:
    """Backfill ``email_hash_v2`` for up to ``_BATCH_SIZE`` invitation rows.

    Returns the count of rows updated this batch. Returns 0 when no
    candidates remain (the daily sweep stops at that point until the
    next tick).
    """
    # Skip rows whose ``email`` plaintext has been GDPR-nulled — we
    # cannot reconstruct the v2 hash without the original input.
    stmt = sa.text(
        """
        SELECT id, email
          FROM project_invitations
         WHERE email_hash_v2 IS NULL
           AND email IS NOT NULL
         ORDER BY created_at
         LIMIT :limit
         FOR UPDATE SKIP LOCKED
        """
    )
    result = await session.execute(stmt, {"limit": _BATCH_SIZE})
    rows = result.fetchall()
    if not rows:
        return 0

    updated = 0
    for row in rows:
        invitation_id: UUID = row[0]
        email_plaintext: str = row[1]
        try:
            dual = compute_pii_hash_dual(_canonical_email(email_plaintext))
        except Exception:  # noqa: BLE001 — KMS transient → skip row, retry tomorrow
            logger.warning(
                "pii_hash_backfill: KMS error for invitation_id=%s",
                invitation_id,
                exc_info=True,
            )
            continue

        new_v2 = dual.get("v2") or dual["v1"]
        version = 2 if "v2" in dual else 1

        await session.execute(
            sa.text(
                """
                UPDATE project_invitations
                   SET email_hash_v2 = :v2,
                       pii_hash_version = :ver
                 WHERE id = :id
                   AND email_hash_v2 IS NULL
                """
            ),
            {"v2": new_v2, "ver": version, "id": invitation_id},
        )
        updated += 1

    return updated


async def _run_backfill() -> dict[str, Any]:
    """Async pipeline backing :func:`pii_hash_backfill_invitations`.

    Single-key mode short-circuits immediately. Otherwise we drain a
    single batch per task invocation; subsequent batches happen on
    the next beat tick (24 h cadence). Operators that need to
    accelerate the rotation can dispatch the task manually via
    ``celery -A echoroo.workers.celery_app call ...``.
    """
    if get_pii_hash_version() == 1:
        logger.debug(
            "pii_hash_backfill: single-key mode (AWS_KMS_CMK_PII_HASH_ALIAS_V2 "
            "unset); skipping"
        )
        return {"status": "skipped", "reason": "single_key_mode", "updated": 0}

    async with AsyncSessionLocal() as session:
        try:
            updated = await _backfill_invitation_batch(session)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    if updated:
        logger.info(
            "pii_hash_backfill: filled email_hash_v2 for %d invitation row(s)",
            updated,
        )
    else:
        logger.debug("pii_hash_backfill: no candidate rows")

    return {"status": "ok", "updated": updated}


@app.task(  # type: ignore[untyped-decorator]
    name=(
        "echoroo.workers.pii_hash_backfill.pii_hash_backfill_invitations"
    ),
)
def pii_hash_backfill_invitations() -> dict[str, Any]:
    """Backfill ``email_hash_v2`` on invitation rows (FR-091b).

    Returns a summary dict with the row count. ``status='skipped'``
    is emitted in single-key mode (no v2 alias configured) so the
    operator dashboard can distinguish "rotation not started" from
    "rotation complete (no candidates left)".
    """
    return asyncio.run(_run_backfill())


__all__ = [
    "pii_hash_backfill_invitations",
]
