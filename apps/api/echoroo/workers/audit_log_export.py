"""Weekly audit log archive worker (FR-095).

Each run considers the most recent closed ISO weeks in
``project_audit_log`` and ``platform_audit_log``. Every archive contains
exactly one closed week, is written once by skipping an existing key, and is
read back from storage so the stored bytes' KMS-MAC chain is re-verified.
The catch-up window lets a later run export a missed week. Immutability of
stored files is operational (read-only mount plus snapshots; see
``docs/runbook/audit_log_archive.md``), while tamper evidence comes from the
KMS MAC chain in every row.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task

from echoroo.core.kms import compute_audit_chain_hash
from echoroo.core.s3 import get_object_stream, object_exists, put_object

logger = logging.getLogger(__name__)


# How many closed ISO weeks each run looks back over, so a missed or failed
# run is caught up by a later one.
_CATCH_UP_WEEKS = 8


class AuditChainMismatchError(RuntimeError):
    """Raised when the recomputed row_hash does not match the stored value.

    The worker aborts before any S3 upload so an on-call engineer can
    investigate. The mismatch itself is logged via ``platform_audit_log``
    before the exception propagates.
    """


class AuditArchiveMismatchError(RuntimeError):
    """Raised when an archive read back from storage fails chain verification."""


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


def _week_object_key(table: str, iso_year: int, iso_week: int) -> str:
    """Return the archive key for one ISO week of one table."""
    return f"audit-log/{table}/{iso_year:04d}/{iso_week:02d}.ndjson"


def _week_bounds(iso_year: int, iso_week: int) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` of an ISO week as tz-aware UTC datetimes."""
    start = datetime.fromisocalendar(iso_year, iso_week, 1).replace(tzinfo=UTC)
    return start, start + timedelta(days=7)


def _closed_weeks(now: datetime, count: int) -> list[tuple[int, int]]:
    """Return the ``count`` most recent ISO weeks that ended before ``now``, oldest first."""
    this_week_start, _ = _week_bounds(*now.astimezone(UTC).isocalendar()[:2])
    weeks: list[tuple[int, int]] = []
    for back in range(count, 0, -1):
        iso = (this_week_start - timedelta(days=7 * back)).isocalendar()
        weeks.append((iso[0], iso[1]))
    return weeks


def _write_archive(key: str, body: bytes) -> None:
    """Write one archive. Callers check :func:`object_exists` first (write-once)."""
    # FR-028e: put_object routes the PutObject kwargs through the GPS-metadata
    # sanitizer centrally.
    put_object(key, body, content_type="application/x-ndjson")
    logger.info("audit export archived key=%s bytes=%d", key, len(body))


def verify_archive(key: str, *, include_project_id: bool) -> int:
    """Read an archive back from storage and re-verify every row's MAC.

    Returns:
        Number of rows verified.

    Raises:
        AuditArchiveMismatchError: If any stored row fails verification.
    """
    body: bytes = get_object_stream(key).read()
    rows: list[dict[str, Any]] = []
    for line in body.decode("utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        row["created_at"] = datetime.fromisoformat(row["created_at"])
        rows.append(row)
    try:
        _verify_chain(rows, include_project_id=include_project_id)
    except AuditChainMismatchError as exc:
        raise AuditArchiveMismatchError(f"archive {key}: {exc}") from exc
    return len(rows)


@shared_task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.audit_log_export.export_weekly",
    queue="worker-cpu",
    max_retries=3,
)
def export_weekly(now_iso: str | None = None) -> dict[str, Any]:
    """Archive every closed ISO week of the last `_CATCH_UP_WEEKS` that has rows and no archive yet (FR-095).

    Args:
        now_iso: ISO-8601 timestamp to use as the current time. If None,
            defaults to the current UTC time.

    Returns:
        Summary dict with the export timestamp and newly written archives.
    """
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)

    # Local import: the worker may not have the app engine available at
    # module load time, and the session factory carries its own lifetime
    # management that we must enter/exit cleanly.
    from echoroo.workers.db_utils import get_worker_engine_and_session_factory

    _, session_factory = get_worker_engine_and_session_factory()

    summary: dict[str, Any] = {"exported_at": now.isoformat(), "archives": [], "failed": []}

    # NOTE: session_factory yields an AsyncSession by default; the weekly
    # export is a simple read-then-upload job so we wrap a synchronous
    # consumer below. Celery's ``shared_task`` is synchronous, so any
    # async DB driver the app ships with must be run inside ``asyncio.run``.
    import asyncio

    async def _run() -> None:
        async with session_factory() as session:
            for table in ("project_audit_log", "platform_audit_log"):
                include_project_id = table == "project_audit_log"
                for iso_year, iso_week in _closed_weeks(now, _CATCH_UP_WEEKS):
                    key = _week_object_key(table, iso_year, iso_week)
                    if object_exists(key):
                        continue
                    start, end = _week_bounds(iso_year, iso_week)
                    rows = await _afetch_rows(session, table, start=start, end=end)
                    if not rows:
                        continue
                    try:
                        _verify_chain(rows, include_project_id=include_project_id)
                    except AuditChainMismatchError as exc:
                        # Never archive a week that fails verification, but do
                        # not let it block the clean weeks either.
                        logger.error("audit export refused key=%s: %s", key, exc)
                        summary["failed"].append({"table": table, "key": key, "error": str(exc)})
                        continue
                    _write_archive(key, _serialize_ndjson(rows))
                    verified = verify_archive(key, include_project_id=include_project_id)
                    summary["archives"].append(
                        {"table": table, "key": key, "row_count": verified}
                    )

    asyncio.run(_run())
    if summary["failed"]:
        # Fail the task so the broken weeks reach an operator; the clean weeks
        # above are already archived and will be skipped on the retry.
        failed_keys = ", ".join(item["key"] for item in summary["failed"])
        raise AuditChainMismatchError(
            f"refused to archive {len(summary['failed'])} week(s) with a broken chain: {failed_keys}"
        )
    return summary


async def _afetch_rows(
    session: Any,
    table: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Fetch rows with ``start <= created_at < end``, sorted by (created_at, id)."""
    import sqlalchemy as sa

    where_parts: list[str] = []
    if start is not None:
        where_parts.append("created_at >= :start")
    if end is not None:
        where_parts.append("created_at < :end")
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    project_col = "project_id, " if table == "project_audit_log" else ""
    stmt = sa.text(
        f"SELECT id, created_at, actor_user_id_hash, {project_col}"
        f"action, detail, request_id, ip_hash, user_agent_hash, "
        f"before, after, prev_hash, row_hash "
        f"FROM {table} {where} ORDER BY created_at ASC, id ASC"
    )
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if end is not None:
        params["end"] = end
    result = await session.execute(stmt, params)
    mapped = result.mappings().all()
    return [dict(row) for row in mapped]


__all__ = [
    "AuditArchiveMismatchError",
    "AuditChainMismatchError",
    "export_weekly",
    "verify_archive",
]
