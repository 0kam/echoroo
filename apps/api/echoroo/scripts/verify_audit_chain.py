"""Verify the complete project and platform audit-log chains."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Literal, cast

from echoroo.workers.audit_log_export import (
    ChainVerification,
    _afetch_rows,
    _is_bootstrap_row,
    verify_chain,
)
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

_ZERO_HASH = "0" * 64
_TABLES: dict[str, tuple[str, bool]] = {
    "project": ("project_audit_log", True),
    "platform": ("platform_audit_log", False),
}
TableName = Literal["project", "platform"]


def _display_verdict(table: str, rows: list[dict[str, Any]], result: ChainVerification) -> bool:
    """Print a public chain verdict without exposing row contents."""
    if result.is_valid:
        print(f"{table}: valid ({len(rows)} rows)")
        return True
    print(f"{table}: invalid at {result.first_bad_row_id} ({result.reason})")
    return False


async def _verify_table(
    session: Any,
    table: TableName,
) -> tuple[list[dict[str, Any]], ChainVerification]:
    """Fetch and verify one complete audit-log table."""
    table_name, include_project_id = _TABLES[table]
    rows = await _afetch_rows(session, table_name)
    result = verify_chain(
        rows,
        include_project_id=include_project_id,
        expected_prev_hash=_ZERO_HASH,
    )
    return rows, result


def _deletion_probe(
    table: str,
    rows: list[dict[str, Any]],
    *,
    include_project_id: bool,
) -> bool:
    """Confirm that removing an interior signed row breaks a chain link."""
    if len(rows) < 3:
        print(f"{table}: deletion check skipped (fewer than 3 rows)")
        return True

    interior_indices = range(1, len(rows) - 1)
    index = next(
        (candidate for candidate in interior_indices if not _is_bootstrap_row(rows[candidate])),
        None,
    )
    if index is None:
        print(f"{table}: deletion check failed (no interior signed row)")
        return False

    probe_rows = rows[:index] + rows[index + 1 :]
    result = verify_chain(
        probe_rows,
        include_project_id=include_project_id,
        expected_prev_hash=_ZERO_HASH,
    )
    if not result.is_valid and result.reason == "link":
        print(f"{table}: deletion check detected (link)")
        return True

    reason = result.reason if not result.is_valid else "valid"
    print(f"{table}: deletion check failed ({reason})")
    return False


def _build_parser() -> argparse.ArgumentParser:
    """Build the audit-chain verifier argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table",
        choices=("project", "platform", "both"),
        default="both",
        help="Audit-log table to verify (default: both).",
    )
    parser.add_argument(
        "--check-detects-deleted-row",
        action="store_true",
        help="Verify that removing an interior row is detected as a broken link.",
    )
    return parser


async def _run(table_choice: str, check_deleted: bool) -> bool:
    """Fetch and verify the selected tables using a fresh database engine."""
    tables: tuple[TableName, ...] = (
        ("project", "platform") if table_choice == "both" else (cast(TableName, table_choice),)
    )

    engine, session_factory = get_worker_engine_and_session_factory()
    all_valid = True
    try:
        async with session_factory() as session:
            for table in tables:
                rows, result = await _verify_table(session, table)
                table_valid = _display_verdict(table, rows, result)
                all_valid = table_valid and all_valid
                if check_deleted:
                    all_valid = (
                        _deletion_probe(
                            table,
                            rows,
                            include_project_id=_TABLES[table][1],
                        )
                        and all_valid
                    )
    finally:
        await engine.dispose()
    return all_valid


def main(argv: list[str] | None = None) -> int:
    """Run the audit-chain verifier and return its process exit code."""
    args = _build_parser().parse_args(argv)
    try:
        valid = asyncio.run(_run(args.table, args.check_detects_deleted_row))
    except Exception:  # noqa: BLE001 — do not expose database or key details
        print("audit chain verification failed", file=sys.stderr)
        return 1
    return 0 if valid else 1


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
