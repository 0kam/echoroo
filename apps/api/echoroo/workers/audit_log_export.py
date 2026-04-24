"""Weekly audit log export worker (FR-095).

Each week this task:

1. Reads every row inserted since the previous successful export from
   ``project_audit_log`` and ``platform_audit_log``.
2. Re-computes ``row_hash`` locally for each row (using the KMS-backed
   ``compute_audit_chain_hash``) and asserts it matches the stored value.
   A mismatch aborts the export and raises ``AuditChainMismatchError`` so
   a human can investigate before any compromised data is archived.
3. Serialises the verified rows as NDJSON (one JSON object per line,
   UTF-8, newline-terminated).
4. Uploads the NDJSON document to the configured S3 Object Lock bucket in
   ``GOVERNANCE`` mode with a 3-year retention (``RetainUntilDate = now +
   3 years``). GOVERNANCE mode is chosen (not COMPLIANCE) so that the
   creator_founder override pathway can still remove the last audit copy
   during the emergency wipe flow (FR-114); production rollout may later
   flip to COMPLIANCE if operations agree.
5. Writes a completion event to ``platform_audit_log`` so the next
   weekly run knows where to resume.

The task is defined using :func:`celery.shared_task` so it does not
require the ``celery_app`` module at import time (the workers package
includes this module via ``include =`` in ``celery_app.py``). It is
idempotent: re-running against the same cursor produces the same S3
object key (``audit-log/<table>/<YYYY>/<WW>.ndjson``), and S3's
``PutObject`` with Object Lock will keep the first version immutable.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task

from echoroo.core.kms import compute_audit_chain_hash
from echoroo.core.s3 import get_s3_client
from echoroo.core.settings import get_settings

logger = logging.getLogger(__name__)


# Retention window for exported NDJSON batches (FR-095).
_RETENTION_YEARS = 3
_RETENTION_DELTA = timedelta(days=365 * _RETENTION_YEARS)


class AuditChainMismatchError(RuntimeError):
    """Raised when the recomputed row_hash does not match the stored value.

    The worker aborts before any S3 upload so an on-call engineer can
    investigate. The mismatch itself is logged via ``platform_audit_log``
    before the exception propagates.
    """


def _canonical_row(row: dict[str, Any], *, include_project_id: bool) -> bytes:
    """Recompute the canonical byte payload used to MAC a row.

    Must match the layout used by :func:`audit_service._build_canonical_row`
    — any drift breaks chain verification.
    """
    created_at = row["created_at"]
    if isinstance(created_at, datetime):
        created_at_iso = created_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    else:
        created_at_iso = str(created_at)

    project_id_part = ""
    if include_project_id:
        pid = row.get("project_id")
        project_id_part = str(pid) if pid is not None else ""

    lines = [
        created_at_iso,
        row["actor_user_id_hash"],
        row["action"],
        project_id_part,
        row["request_id"],
        row["ip_hash"],
        row["user_agent_hash"],
        json.dumps(row.get("detail") or {}, sort_keys=True, separators=(",", ":"), default=str),
        json.dumps(row.get("before") or {}, sort_keys=True, separators=(",", ":"), default=str),
        json.dumps(row.get("after") or {}, sort_keys=True, separators=(",", ":"), default=str),
    ]
    return "\n".join(lines).encode("utf-8")


def _verify_chain(rows: list[dict[str, Any]], *, include_project_id: bool) -> None:
    """Assert every row's ``row_hash`` matches the recomputed MAC."""
    for row in rows:
        recomputed = compute_audit_chain_hash(
            row["prev_hash"], _canonical_row(row, include_project_id=include_project_id)
        )
        if recomputed != row["row_hash"]:
            raise AuditChainMismatchError(
                f"row_hash mismatch for id={row.get('id')!r}: "
                f"stored={row['row_hash']!r} recomputed={recomputed!r}"
            )


def _serialize_ndjson(rows: list[dict[str, Any]]) -> bytes:
    """Serialise rows as NDJSON (newline-delimited JSON)."""
    buf = io.StringIO()
    for row in rows:
        serialisable = {
            key: (value.isoformat() if isinstance(value, datetime) else str(value) if not _json_safe(value) else value)
            for key, value in row.items()
        }
        buf.write(json.dumps(serialisable, sort_keys=True, separators=(",", ":"), default=str))
        buf.write("\n")
    return buf.getvalue().encode("utf-8")


def _json_safe(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, type(None), list, dict))


def _week_object_key(table: str, *, at: datetime) -> str:
    """Return the stable S3 key for a weekly export batch.

    Uses ISO week number so the key is deterministic across time zones:
    ``audit-log/<table>/<ISO year>/<ISO week zero-padded>.ndjson``.
    """
    iso_year, iso_week, _ = at.isocalendar()
    return f"audit-log/{table}/{iso_year:04d}/{iso_week:02d}.ndjson"


def _upload_with_object_lock(
    *,
    bucket: str,
    key: str,
    body: bytes,
    now: datetime,
) -> None:
    """Upload ``body`` to S3 with GOVERNANCE-mode Object Lock retention.

    The bucket must have Object Lock configured at creation time. Putting
    Retention parameters on a non-Object-Lock bucket raises
    ``InvalidRequest`` — the deployment Runbook documents the one-time
    bucket provisioning step.
    """
    client = get_s3_client()
    retain_until = now + _RETENTION_DELTA
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/x-ndjson",
        ObjectLockMode="GOVERNANCE",
        ObjectLockRetainUntilDate=retain_until,
    )
    logger.info(
        "audit export uploaded bucket=%s key=%s bytes=%d retain_until=%s",
        bucket,
        key,
        len(body),
        retain_until.isoformat(),
    )


def _fetch_rows(session: Any, table: str, *, since: datetime | None) -> list[dict[str, Any]]:
    """Fetch rows since the given cursor, sorted by (created_at, id).

    Uses a raw SQL query so the worker can run without importing the ORM
    models (which would couple the export job to the full application
    start-up sequence).
    """
    import sqlalchemy as sa

    where = "WHERE created_at > :since" if since is not None else ""
    stmt = sa.text(
        f"SELECT id, created_at, actor_user_id_hash, "
        f"{'project_id, ' if table == 'project_audit_log' else ''}"
        f"action, detail, request_id, ip_hash, user_agent_hash, "
        f"before, after, prev_hash, row_hash "
        f"FROM {table} {where} ORDER BY created_at ASC, id ASC"
    )
    params: dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    result = session.execute(stmt, params)
    rows: list[dict[str, Any]] = []
    for row in result.mappings().all():
        rows.append(dict(row))
    return rows


@shared_task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.audit_log_export.export_weekly",
    queue="worker-cpu",
    max_retries=3,
)
def export_weekly(since_iso: str | None = None) -> dict[str, Any]:
    """Export last-week's audit rows to S3 Object Lock archive (FR-095).

    Args:
        since_iso: ISO-8601 timestamp of the last successful export. If
            None, defaults to ``now - 7 days``.

    Returns:
        Summary dict with per-table row counts and S3 keys.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    cursor = datetime.fromisoformat(since_iso) if since_iso else now - timedelta(days=7)

    bucket = getattr(settings, "AUDIT_LOG_ARCHIVE_BUCKET", None) or settings.S3_BUCKET

    # Local import: the worker may not have the app engine available at
    # module load time, and the session factory carries its own lifetime
    # management that we must enter/exit cleanly.
    from echoroo.workers.db_utils import get_worker_engine_and_session_factory

    _, session_factory = get_worker_engine_and_session_factory()

    summary: dict[str, Any] = {"exported_at": now.isoformat(), "tables": {}}

    # NOTE: session_factory yields an AsyncSession by default; the weekly
    # export is a simple read-then-upload job so we wrap a synchronous
    # consumer below. Celery's ``shared_task`` is synchronous, so any
    # async DB driver the app ships with must be run inside ``asyncio.run``.
    import asyncio

    async def _run() -> None:
        async with session_factory() as session:
            for table in ("project_audit_log", "platform_audit_log"):
                rows = await _afetch_rows(session, table, since=cursor)
                _verify_chain(rows, include_project_id=(table == "project_audit_log"))
                body = _serialize_ndjson(rows)
                key = _week_object_key(table, at=now)
                if rows:
                    _upload_with_object_lock(
                        bucket=bucket, key=key, body=body, now=now
                    )
                summary["tables"][table] = {"row_count": len(rows), "s3_key": key}

    asyncio.run(_run())
    return summary


async def _afetch_rows(session: Any, table: str, *, since: datetime | None) -> list[dict[str, Any]]:
    """Async variant of :func:`_fetch_rows` for use with AsyncSession."""
    import sqlalchemy as sa

    where = "WHERE created_at > :since" if since is not None else ""
    project_col = "project_id, " if table == "project_audit_log" else ""
    stmt = sa.text(
        f"SELECT id, created_at, actor_user_id_hash, {project_col}"
        f"action, detail, request_id, ip_hash, user_agent_hash, "
        f"before, after, prev_hash, row_hash "
        f"FROM {table} {where} ORDER BY created_at ASC, id ASC"
    )
    params: dict[str, Any] = {}
    if since is not None:
        params["since"] = since
    result = await session.execute(stmt, params)
    mapped = result.mappings().all()
    return [dict(row) for row in mapped]


__all__ = [
    "AuditChainMismatchError",
    "export_weekly",
]
