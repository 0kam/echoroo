"""Weekly audit log archive worker (FR-095).

Each run considers the most recent closed ISO weeks in
``project_audit_log`` and ``platform_audit_log``. Every archive contains
exactly one closed week and is written once: an existing key is never
overwritten. After writing, and again on every later run while the week is
inside the catch-up window, the stored bytes are compared with the verified
live rows, so a late row or a replaced archive fails the task visibly. The
catch-up window also lets a later run export a missed week. Immutability of
stored files is operational (read-only mount plus snapshots; see
``docs/runbook/audit_log_archive.md``), while tamper evidence comes from the
KMS MAC chain in every row.
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from celery import shared_task

from echoroo.core.kms import compute_audit_chain_hash
from echoroo.core.s3 import get_object_stream, object_exists, put_object

logger = logging.getLogger(__name__)


# How many closed ISO weeks each run looks back over, so a missed or failed
# run is caught up by a later one.
_CATCH_UP_WEEKS = 8

# Serialises concurrent runs (beat double-fire, a manual run next to the
# scheduled one) so "check, then write" on an archive key cannot race.
# Arbitrary constant; only has to differ from the other advisory-lock users.
_EXPORT_LOCK_KEY = 0x6175646974_01  # "audit" + 01

_ZERO_HASH = "0" * 64
# Rows inserted by the baseline migration and by scripts/wipe_database.py before
# the keyed hashers exist. They carry all-zero hashes by design and are the only
# rows accepted without a MAC.
_BOOTSTRAP_ACTIONS = frozenset({"genesis", "platform.wipe_executed"})

_ARCHIVE_KEY_RE = re.compile(r"/(\d{4})/(\d{2})\.ndjson$")


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


def _is_bootstrap_row(row: dict[str, Any]) -> bool:
    return (
        row["action"] in _BOOTSTRAP_ACTIONS
        and row["row_hash"] == _ZERO_HASH
        and row["prev_hash"] == _ZERO_HASH
    )


def _verify_chain(
    rows: list[dict[str, Any]],
    *,
    include_project_id: bool,
    expected_prev_hash: str | None = None,
) -> None:
    """Assert every row's MAC and that consecutive rows are linked.

    Rows must be in ``(created_at, id)`` order. The link check
    (``prev_hash == previous row_hash``) is what detects a removed or reordered
    row; the MAC alone only authenticates each row in isolation.

    ``expected_prev_hash`` is the ``row_hash`` of the row that precedes
    ``rows[0]`` in the table (all zeros when nothing precedes it). Checking it
    ties the batch to the rest of the chain, and it is what confines the
    unauthenticated bootstrap rows to the very start of the chain: a zero-hash
    row further along can only link to another zero-hash row.
    """
    if rows and expected_prev_hash is not None and rows[0]["prev_hash"] != expected_prev_hash:
        raise AuditChainMismatchError(
            f"chain link broken before id={rows[0].get('id')!r}: "
            f"prev_hash={rows[0]['prev_hash']!r} but the preceding row_hash is "
            f"{expected_prev_hash!r}"
        )
    previous: dict[str, Any] | None = None
    for row in rows:
        if previous is not None and row["prev_hash"] != previous["row_hash"]:
            raise AuditChainMismatchError(
                f"chain link broken before id={row.get('id')!r}: "
                f"prev_hash={row['prev_hash']!r} but the preceding row "
                f"id={previous.get('id')!r} has row_hash={previous['row_hash']!r}"
            )
        previous = row
        if _is_bootstrap_row(row):
            continue
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


def _read_archive(key: str) -> bytes | None:
    """Return the stored bytes of an archive, or None if the key does not exist."""
    if not object_exists(key):
        return None
    body: bytes = get_object_stream(key).read()
    return body


def verify_archive(
    key: str,
    *,
    include_project_id: bool,
    expected_prev_hash: str | None = None,
) -> int:
    """Read an archive back from storage and verify it on its own.

    Proves that every row is authentic (MAC), belongs to the ISO week named by
    the key, and that no row *inside* the archive was removed or reordered
    (chain links). On its own it cannot prove that rows were not cut off either
    end, nor that a zero-hash bootstrap row is genuine: pass
    ``expected_prev_hash`` (the last ``row_hash`` of the preceding archive) to
    anchor the start, and check the next archive the same way to anchor the
    end (see docs/runbook/audit_log_archive.md).

    Returns:
        Number of rows verified.

    Raises:
        AuditArchiveMismatchError: If the archive is missing, empty, malformed,
            or fails verification.
    """
    body = _read_archive(key)
    if body is None:
        raise AuditArchiveMismatchError(f"archive {key}: not found")
    try:
        rows: list[dict[str, Any]] = []
        for line in body.decode("utf-8").splitlines():
            if not line:
                continue
            row = json.loads(line)
            row["created_at"] = datetime.fromisoformat(row["created_at"])
            rows.append(row)
        if not rows:
            # The export never writes an empty archive.
            raise ValueError("contains no rows")
        match = _ARCHIVE_KEY_RE.search(key)
        if match:
            start, end = _week_bounds(int(match.group(1)), int(match.group(2)))
            for row in rows:
                if not start <= row["created_at"] < end:
                    raise ValueError(
                        f"row id={row.get('id')!r} at {row['created_at'].isoformat()} "
                        "is outside the ISO week named by the key"
                    )
        _verify_chain(
            rows,
            include_project_id=include_project_id,
            expected_prev_hash=expected_prev_hash,
        )
    except AuditChainMismatchError as exc:
        raise AuditArchiveMismatchError(f"archive {key}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any malformed shape is a failed verification
        raise AuditArchiveMismatchError(f"archive {key}: malformed: {exc}") from exc
    return len(rows)


async def _try_export_lock(session: Any) -> bool:
    """Take the transaction-scoped export lock; False if another run holds it."""
    import sqlalchemy as sa

    result = await session.execute(
        sa.text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _EXPORT_LOCK_KEY}
    )
    return bool(result.scalar())


def _export_week(
    key: str,
    rows: list[dict[str, Any]],
    *,
    include_project_id: bool,
    prev_hash: str,
) -> bool:
    """Archive or re-audit one closed week. Returns True if an archive was written.

    Raises on anything that makes the week untrustworthy; the caller records it
    and moves on. Never overwrites an existing archive.
    """
    stored = _read_archive(key)
    if not rows:
        if stored is not None:
            raise AuditArchiveMismatchError(
                "archive exists but the live table has no rows for that week"
            )
        return False
    _verify_chain(rows, include_project_id=include_project_id, expected_prev_hash=prev_hash)
    expected = _serialize_ndjson(rows)
    written = stored is None
    if written:
        _write_archive(key, expected)
        stored = _read_archive(key)
    if stored != expected:
        raise AuditArchiveMismatchError(
            "archive differs from the live table "
            f"(stored {len(stored or b'')} bytes, live {len(expected)} bytes, {len(rows)} live rows)"
        )
    return written


@shared_task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.audit_log_export.export_weekly",
)
def export_weekly(now_iso: str | None = None) -> dict[str, Any]:
    """Archive the closed ISO weeks of the last ``_CATCH_UP_WEEKS`` and audit the existing ones (FR-095).

    For every closed week in the window the live rows are verified and
    serialised. A week without an archive is written; a week that already has
    one is compared byte for byte with the live table, so a row that landed in
    a week after it was archived, or an archive replaced in storage, fails the
    task instead of passing unnoticed. Archives are never overwritten.

    Args:
        now_iso: ISO-8601 timestamp to use as the current time (a value
            without an offset is taken as UTC). Defaults to the current time.

    Returns:
        Summary dict: ``archives`` written in this run, ``failed`` weeks.

    Raises:
        AuditChainMismatchError: After processing every week, if any failed.
    """
    now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    # Local import: the worker may not have the app engine available at
    # module load time, and the session factory carries its own lifetime
    # management that we must enter/exit cleanly.
    from echoroo.workers.db_utils import get_worker_engine_and_session_factory

    _, session_factory = get_worker_engine_and_session_factory()

    summary: dict[str, Any] = {"exported_at": now.isoformat(), "archives": [], "failed": []}

    def _fail(table: str, key: str, error: str) -> None:
        # A failed week is never written or replaced, and never blocks the others.
        logger.error("audit export failed key=%s: %s", key, error)
        summary["failed"].append({"table": table, "key": key, "error": error})

    # Celery's ``shared_task`` is synchronous and the app ships an async DB
    # driver, so the body runs inside ``asyncio.run``.
    import asyncio

    async def _run() -> None:
        async with session_factory() as session:
            # Held until the session's transaction ends (we never commit).
            if not await _try_export_lock(session):
                summary["skipped"] = "another export run holds the lock"
                return
            for table in ("project_audit_log", "platform_audit_log"):
                include_project_id = table == "project_audit_log"
                for iso_year, iso_week in _closed_weeks(now, _CATCH_UP_WEEKS):
                    key = _week_object_key(table, iso_year, iso_week)
                    start, end = _week_bounds(iso_year, iso_week)
                    rows = await _afetch_rows(session, table, start=start, end=end)
                    prev_hash = await _afetch_prev_hash(session, table, before=start)
                    try:
                        written = _export_week(
                            key, rows, include_project_id=include_project_id, prev_hash=prev_hash
                        )
                    except Exception as exc:  # noqa: BLE001 - one week never blocks the others
                        _fail(table, key, f"{exc.__class__.__name__}: {exc}")
                        continue
                    if written:
                        summary["archives"].append(
                            {"table": table, "key": key, "row_count": len(rows)}
                        )

    asyncio.run(_run())
    if summary["failed"]:
        # Fail the task so the weeks reach an operator. Clean weeks are already
        # archived and are only re-checked, never rewritten, on the next run.
        failed_keys = ", ".join(item["key"] for item in summary["failed"])
        raise AuditChainMismatchError(
            f"{len(summary['failed'])} week(s) failed the audit export: {failed_keys}"
        )
    return summary


async def _afetch_prev_hash(session: Any, table: str, *, before: datetime) -> str:
    """Return the ``row_hash`` of the last row before ``before`` (zeros if none)."""
    import sqlalchemy as sa

    result = await session.execute(
        sa.text(
            f"SELECT row_hash FROM {table} WHERE created_at < :before "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ),
        {"before": before},
    )
    value = result.scalar()
    return str(value) if value is not None else _ZERO_HASH


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
