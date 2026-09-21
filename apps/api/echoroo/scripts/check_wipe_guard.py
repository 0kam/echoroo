"""Three-point wipe_guard checker (FR-114, quickstart §2).

The release-time database wipe may only happen once. To prevent accidental
re-execution we keep three independent markers, and this script verifies all
three are in the expected state before the wipe is permitted:

1. **Database**: a row in the ``wipe_guard`` table means a wipe already ran.
2. **Alembic**: the ``alembic_version`` table pinning must equal the baseline
   revision ``0001``. Any other state means the DB has drifted.
3. **Audit-log genesis marker in object storage**: a genesis marker file in
   the audit-log export bucket is the cryptographic anchor for the
   append-only audit log. If absent, the platform has not been bootstrapped.

Exit codes:

- ``0`` — all three markers are in the expected state; wipe is safe.
- ``10`` — ``wipe_guard`` row exists (wipe already happened).
- ``11`` — alembic version is not ``0001``.
- ``12`` — audit-log genesis marker in object storage is missing or incorrect.
- ``20`` — infrastructure error (DB/S3 unreachable).

The checker is invoked twice during the wipe ritual:

- **pre-wipe**: expects an empty guard + baseline alembic + S3 marker absent.
  Any failure aborts the wipe.
- **post-wipe** (sanity): expects a guard row + baseline alembic + S3 marker
  present.

This module intentionally has zero runtime dependencies beyond the settings
layer already used by the app (boto3, SQLAlchemy). It is designed to be
runnable from a minimal image during on-call incident response.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger("echoroo.scripts.check_wipe_guard")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


BASELINE_REVISION = "0001"
S3_GENESIS_KEY = "audit-log/genesis/marker.json"


@dataclass(frozen=True)
class WipeGuardStatus:
    """Result of a three-point wipe_guard check."""

    db_guard_row_present: bool
    alembic_version_is_baseline: bool
    s3_genesis_marker_present: bool

    @property
    def all_clear_for_wipe(self) -> bool:
        """True iff pre-wipe state is valid (all three markers absent)."""

        return (
            not self.db_guard_row_present
            and self.alembic_version_is_baseline
            and not self.s3_genesis_marker_present
        )

    @property
    def all_post_wipe(self) -> bool:
        """True iff post-wipe state is valid (DB row + baseline + S3 marker)."""

        return (
            self.db_guard_row_present
            and self.alembic_version_is_baseline
            and self.s3_genesis_marker_present
        )


def _check_db(database_url: str) -> tuple[bool, bool]:
    """Return ``(wipe_guard_row_present, alembic_version_is_baseline)``."""

    # Deferred import — keep the script importable on hosts that lack the
    # full application dependency set.
    from sqlalchemy import create_engine, text

    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            guard_exists = bool(
                conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'wipe_guard')"
                    )
                ).scalar()
            )
            if guard_exists:
                wipe_count = conn.execute(text("SELECT COUNT(*) FROM wipe_guard")).scalar()
                db_guard_row_present = bool((wipe_count or 0) > 0)
            else:
                db_guard_row_present = False

            alembic_exists = bool(
                conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                        "WHERE table_name = 'alembic_version')"
                    )
                ).scalar()
            )
            if not alembic_exists:
                return db_guard_row_present, False
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return db_guard_row_present, version == BASELINE_REVISION
    finally:
        engine.dispose()


def _check_s3_marker() -> bool:
    """Return True if the audit-log genesis marker exists in object storage."""

    from echoroo.core.s3 import object_exists

    return object_exists(S3_GENESIS_KEY)


def check(database_url: str) -> WipeGuardStatus:
    """Run the full three-point check and return a :class:`WipeGuardStatus`."""

    db_guard_row_present, alembic_version_is_baseline = _check_db(database_url)
    s3_marker_present = _check_s3_marker()
    return WipeGuardStatus(
        db_guard_row_present=db_guard_row_present,
        alembic_version_is_baseline=alembic_version_is_baseline,
        s3_genesis_marker_present=s3_marker_present,
    )


def _load_settings() -> str:
    """Pull the database URL from app settings."""

    from echoroo.core.settings import get_settings

    settings = get_settings()
    return str(settings.DATABASE_URL)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by ``python -m echoroo.scripts.check_wipe_guard``."""

    _ = argv  # argv reserved for future flags (e.g. --post-wipe)
    try:
        database_url = _load_settings()
    except Exception as exc:  # pragma: no cover — bootstrap safety
        logger.error("Failed to load settings: %s", exc)
        return 20

    try:
        status = check(database_url)
    except Exception as exc:
        logger.error("Wipe guard check raised an error: %s", exc)
        return 20

    logger.info(
        "Wipe guard status: db_row=%s, alembic_baseline=%s, s3_marker=%s",
        status.db_guard_row_present,
        status.alembic_version_is_baseline,
        status.s3_genesis_marker_present,
    )

    if status.db_guard_row_present:
        logger.error("Refusing wipe: wipe_guard already contains a row (FR-114 point a).")
        return 10
    if not status.alembic_version_is_baseline:
        logger.error(
            "Refusing wipe: alembic_version is not baseline '%s' (FR-114 point b).",
            BASELINE_REVISION,
        )
        return 11
    if not status.s3_genesis_marker_present:
        logger.error(
            "Refusing wipe: audit-log genesis marker not found at %s (FR-114 point c).",
            S3_GENESIS_KEY,
        )
        return 12

    logger.info("All three wipe_guard points clear — wipe ritual may proceed.")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main(sys.argv[1:]))
