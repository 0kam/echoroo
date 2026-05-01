"""Interactive release-time database wipe (FR-113, FR-114, quickstart §2).

This script drops every table in the public schema and re-runs the baseline
Alembic migration, marking the event in the ``wipe_guard`` table so it can
never happen again without an explicit, auditable emergency override.

Guard rails (defence-in-depth):

1. ``check_wipe_guard.check`` must report all three markers "clear for wipe"
   (FR-114). If any of the three says the wipe already happened the script
   aborts immediately.
2. Two **superuser IDs** must be supplied interactively (M-of-N = 2 signers,
   spec FR-113, §5 of quickstart). The IDs are recorded in the guard row and
   emitted to ``platform_audit_log`` as ``action='platform.wipe_executed'``.
3. An explicit safety phrase must be typed verbatim. This stops tab-complete
   or sleep-deprived on-call engineers from nuking the cluster.
4. ``TEST_MODE=true`` bypasses the interactive prompts but still requires the
   guard to be clear and still writes the audit trail.

After the teardown the script calls ``alembic upgrade head`` so the operator
ends up with a fresh schema ready for ``scripts.init_superuser``.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

logger = logging.getLogger("echoroo.scripts.wipe_database")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


SAFETY_PHRASE = "YES I UNDERSTAND THIS DESTROYS ALL DATA"
API_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = API_ROOT / "alembic.ini"


def _require_two_superuser_ids(test_mode: bool) -> tuple[str, str]:
    """Return two distinct superuser UUIDs (M-of-N signers)."""

    if test_mode:
        test_signers = os.environ.get("WIPE_TEST_SIGNERS", "")
        parts = [p.strip() for p in test_signers.split(",") if p.strip()]
        if len(parts) != 2:
            raise SystemExit(
                "TEST_MODE=true requires WIPE_TEST_SIGNERS='uuid1,uuid2' "
                "(two distinct superuser UUIDs)."
            )
        signer_a, signer_b = parts
    else:  # pragma: no cover — interactive path
        print(
            "\nThis operation requires two superuser signers (M-of-N = 2).",
            file=sys.stderr,
        )
        signer_a = input("Superuser A UUID: ").strip()
        signer_b = input("Superuser B UUID: ").strip()

    # Validate
    try:
        uuid_a = UUID(signer_a)
        uuid_b = UUID(signer_b)
    except ValueError as exc:
        raise SystemExit(f"Invalid UUID input: {exc}") from exc
    if uuid_a == uuid_b:
        raise SystemExit("Two DISTINCT superusers are required (same UUID given twice).")
    return str(uuid_a), str(uuid_b)


def _confirm_interactive(test_mode: bool) -> None:
    """Force the operator to type the safety phrase verbatim."""

    if test_mode:
        return
    print(
        "\n"
        "================================================================\n"
        "  ECHOROO DATABASE WIPE RITUAL  (FR-113, FR-114)\n"
        "  This will DROP every table in the public schema and\n"
        "  re-run alembic upgrade head. It can only run ONCE.\n"
        "================================================================\n",
        file=sys.stderr,
    )
    phrase = input(f"Type the safety phrase exactly:\n  {SAFETY_PHRASE}\n> ")
    if phrase.strip() != SAFETY_PHRASE:
        raise SystemExit("Safety phrase mismatch — aborting.")


def _verify_precondition() -> None:
    """Run check_wipe_guard and refuse to proceed unless all three points clear."""

    from echoroo.scripts import check_wipe_guard as cwg

    database_url, audit_bucket, s3_endpoint_url = cwg._load_settings()
    status = cwg.check(database_url, audit_bucket, s3_endpoint_url)
    if not status.all_clear_for_wipe:
        logger.error(
            "Wipe precondition failed: db_row=%s, alembic_baseline=%s, s3_marker=%s",
            status.db_guard_row_present,
            status.alembic_version_is_baseline,
            status.s3_genesis_marker_present,
        )
        raise SystemExit(
            "Wipe aborted — the three-point guard is not in the expected pre-wipe state. "
            "See check_wipe_guard output above."
        )


def _drop_public_schema(database_url: str) -> None:
    """Drop and recreate the public schema (raw SQL — bypasses ORM)."""

    from sqlalchemy import create_engine, text

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO public"))
    finally:
        engine.dispose()


def _run_alembic_upgrade() -> None:
    """Invoke ``alembic upgrade head`` as a subprocess."""

    result = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(API_ROOT),
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(
            "alembic upgrade head failed after wipe.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _record_wipe_guard(
    database_url: str, signer_a: str, signer_b: str
) -> None:
    """Insert the single wipe_guard row + a platform_audit_log entry."""

    from sqlalchemy import create_engine, text

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url)
    now_iso = datetime.now(UTC)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO wipe_guard (id, wiped_at, wiped_by_superuser_ids) "
                    "VALUES (1, :wiped_at, :signers)"
                ),
                {"wiped_at": now_iso, "signers": [signer_a, signer_b]},
            )
            # Platform audit trail — hash fields intentionally set to repeat('0',64)
            # here because the application keyed hashers are not bootstrapped yet.
            conn.execute(
                text(
                    """
                    INSERT INTO platform_audit_log (
                        id, created_at, actor_user_id_hash, action, detail,
                        request_id, ip_hash, user_agent_hash,
                        before, after, prev_hash, row_hash
                    ) VALUES (
                        gen_random_uuid(), :ts, repeat('0', 64),
                        'platform.wipe_executed',
                        jsonb_build_object(
                            'signer_a', :signer_a,
                            'signer_b', :signer_b
                        ),
                        'wipe-database-script',
                        repeat('0', 64), repeat('0', 64),
                        NULL, NULL,
                        repeat('0', 64), repeat('0', 64)
                    )
                    """
                ),
                {
                    "ts": now_iso,
                    "signer_a": signer_a,
                    "signer_b": signer_b,
                },
            )
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""

    _ = argv
    test_mode = os.environ.get("TEST_MODE", "").lower() == "true"

    _verify_precondition()
    signer_a, signer_b = _require_two_superuser_ids(test_mode)
    _confirm_interactive(test_mode)

    from echoroo.core.settings import get_settings

    settings = get_settings()
    database_url: str = str(settings.DATABASE_URL)

    logger.info("Dropping public schema…")
    _drop_public_schema(database_url)
    logger.info("Running alembic upgrade head…")
    _run_alembic_upgrade()
    logger.info("Recording wipe_guard row and platform_audit_log entry…")
    _record_wipe_guard(database_url, signer_a, signer_b)
    logger.info("Wipe complete. Run `scripts.init_superuser` next.")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main(sys.argv[1:]))
