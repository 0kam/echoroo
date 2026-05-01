"""Manual initial IUCN Red List sync (Phase 11 / T621, FR-036).

Quickstart §3 instructs the operator to run this script once after the
release-time wipe + initial superuser bootstrap so the platform has a
populated :class:`~echoroo.models.taxon_sensitivity.TaxonSensitivity`
table before any project starts ingesting detections. Without this
step, every taxon would be unknown and the auto-obscure pipeline would
fall through to the spec's open default (:data:`H3_RES_9`) for all
species — including IUCN Critically Endangered ones.

The script is a thin wrapper around the Celery task body
:func:`echoroo.workers.iucn_sync._run_sync_async`. We deliberately
share the implementation so the CLI cannot drift from the production
worker — any sanity / fail-safe behaviour added to the worker is
automatically picked up here.

Usage::

    docker exec echoroo-backend uv run python -m echoroo.scripts.initial_iucn_sync --confirm

The ``--confirm`` flag is mandatory (security checklist §M-2: no
typo-triggered platform-wide UPSERT). Without it the script prints a
warning and exits non-zero. ``IUCN_API_TOKEN`` must be set in the
environment per :mod:`echoroo.workers.iucn_sync` rules; missing /
empty values cause an immediate, loud failure rather than a silent
no-op.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from echoroo.workers.iucn_sync import _run_sync_async

logger = logging.getLogger("echoroo.scripts.initial_iucn_sync")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser.

    The ``--confirm`` flag mirrors :mod:`echoroo.scripts.wipe_database`
    + :mod:`echoroo.scripts.seed_moe_rdb` so operator muscle memory is
    consistent across the family of dangerous one-shot scripts.
    """
    parser = argparse.ArgumentParser(
        prog="echoroo.scripts.initial_iucn_sync",
        description=(
            "Pull the current IUCN Red List snapshot and UPSERT it into "
            "taxon_sensitivities. Intended to be run ONCE during initial "
            "platform bootstrap (quickstart §3). Subsequent syncs are "
            "handled by the weekly Celery beat schedule."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required acknowledgement that this script will mutate the "
            "global taxon_sensitivities table. Without --confirm the "
            "script exits non-zero without contacting the IUCN API."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if not args.confirm:
        logger.error(
            "Refusing to run without --confirm. This script issues a "
            "platform-wide UPSERT against taxon_sensitivities and "
            "should only be run during the initial bootstrap (see "
            "quickstart §3)."
        )
        return 2

    if not os.environ.get("IUCN_API_TOKEN", "").strip():
        logger.error(
            "IUCN_API_TOKEN env var is empty. Provision the IUCN Red "
            "List API v3 credential before running the initial sync."
        )
        return 3

    try:
        result = asyncio.run(_run_sync_async(force=True))
    except Exception as exc:  # noqa: BLE001 — this is the top-level entry point
        logger.exception("initial_iucn_sync failed: %s", exc)
        return 1

    # Print the structured result so the operator can pipe it into
    # log aggregation / a runbook checklist.
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    sys.stdout.flush()

    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":  # pragma: no cover — CLI invocation
    raise SystemExit(main())
