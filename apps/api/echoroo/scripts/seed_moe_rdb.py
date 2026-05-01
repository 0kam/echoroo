"""Manual seed of the Japanese MoE Red Data Book (Phase 11 / T622, FR-032).

The Ministry of the Environment's Red Data Book is published as a
periodic CSV, not a live API. This script lets an operator ingest a
freshly-published edition into :class:`~echoroo.models.taxon_sensitivity.TaxonSensitivity`
under ``source = 'moe_rdb'`` so the auto-obscure pipeline picks up
domestic conservation status alongside IUCN.

The script is paired with :mod:`echoroo.scripts.initial_iucn_sync` in
the quickstart §3 bootstrap sequence:

    docker exec echoroo-backend uv run python -m echoroo.scripts.seed_moe_rdb \
        path/to/rdb.csv --confirm

CSV format::

    taxon_id,category,sensitivity_h3_res,notes
    "1234567","CR",5,"Endemic to Yakushima"
    "2345678","EN",5,
    "3456789","VU",7,"BirdLife Japan list 2025"

Columns:

* ``taxon_id``: GBIF species key (matches detections.taxon_id /
  tags.taxon_id). Required.
* ``category``: Optional MoE RDB category code (e.g. ``CR``, ``EN``,
  ``VU``, ``NT``, ``LC``). Stored verbatim for operator reference; the
  masking decision uses ``sensitivity_h3_res``.
* ``sensitivity_h3_res``: Required integer in {2, 5, 7, 9, 15} per
  FR-027. The CHECK constraint ``ck_taxon_sensitivities_h3_discrete``
  rejects any other value.
* ``notes``: Optional free-form note — typically the citation for the
  RDB edition the row was sourced from.

Each row is UPSERTed via :func:`echoroo.services.taxon_sensitivity_service.upsert_taxon_sensitivity`
so re-running the script with an updated CSV is idempotent. The
``--confirm`` flag is mandatory (security checklist §M-2) so a
mistyped path cannot accidentally seed nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import TaxonSensitivitySource
from echoroo.services.taxon_sensitivity_service import upsert_taxon_sensitivity

logger = logging.getLogger("echoroo.scripts.seed_moe_rdb")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


# Mirrors the CHECK constraint ``ck_taxon_sensitivities_h3_discrete``
# (FR-027). Surfaced here so the script raises a friendly error before
# the database does.
_VALID_H3_RES: frozenset[int] = frozenset({2, 5, 7, 9, 15})


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser.

    See module docstring for the CSV column contract.
    """
    parser = argparse.ArgumentParser(
        prog="echoroo.scripts.seed_moe_rdb",
        description=(
            "UPSERT a Japanese MoE Red Data Book CSV into the "
            "taxon_sensitivities table under source='moe_rdb'."
        ),
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to the MoE RDB CSV file (UTF-8, header row required).",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Required acknowledgement that this script will mutate "
            "taxon_sensitivities. Without --confirm the script exits "
            "non-zero without opening the CSV."
        ),
    )
    return parser


async def _seed_csv(csv_path: Path) -> dict[str, int]:
    """Stream the CSV into ``upsert_taxon_sensitivity`` row by row.

    Returns a summary dict: ``{"upserted": N, "skipped": M}``.

    The whole import runs inside one transaction so a CSV with a bad
    row in the middle leaves the table untouched. For very large CSVs
    (>>10k rows) this could be split into batches; the MoE RDB is
    well under that scale (a few thousand entries) so the simpler
    one-transaction approach is safer.
    """
    upserted = 0
    skipped = 0

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        async with AsyncSessionLocal() as session:
            try:
                for row_number, row in enumerate(reader, start=2):
                    # row_number starts at 2 because line 1 is the header
                    taxon_id = (row.get("taxon_id") or "").strip()
                    if not taxon_id:
                        logger.warning(
                            "row %d: missing taxon_id — skipping", row_number
                        )
                        skipped += 1
                        continue

                    h3_raw = (row.get("sensitivity_h3_res") or "").strip()
                    try:
                        h3_res = int(h3_raw)
                    except ValueError:
                        logger.error(
                            "row %d (taxon_id=%s): sensitivity_h3_res=%r "
                            "is not an integer — aborting",
                            row_number,
                            taxon_id,
                            h3_raw,
                        )
                        raise

                    if h3_res not in _VALID_H3_RES:
                        logger.error(
                            "row %d (taxon_id=%s): sensitivity_h3_res=%d "
                            "is not in %s — aborting (FR-027)",
                            row_number,
                            taxon_id,
                            h3_res,
                            sorted(_VALID_H3_RES),
                        )
                        raise ValueError(
                            f"sensitivity_h3_res={h3_res} is not one of "
                            f"{sorted(_VALID_H3_RES)} (FR-027)"
                        )

                    category = (row.get("category") or "").strip() or None
                    notes = (row.get("notes") or "").strip() or None

                    await upsert_taxon_sensitivity(
                        session,
                        taxon_id=taxon_id,
                        source=TaxonSensitivitySource.MOE_RDB,
                        sensitivity_h3_res=h3_res,
                        category=category,
                        notes=notes,
                    )
                    upserted += 1

                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return {"upserted": upserted, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)

    if not args.confirm:
        logger.error(
            "Refusing to run without --confirm. This script UPSERTs "
            "into taxon_sensitivities and may overwrite existing "
            "moe_rdb rows."
        )
        return 2

    csv_path: Path = args.csv_path
    if not csv_path.is_file():
        logger.error("CSV file not found: %s", csv_path)
        return 3

    try:
        summary = asyncio.run(_seed_csv(csv_path))
    except Exception as exc:  # noqa: BLE001 — top-level CLI guard
        logger.exception("seed_moe_rdb failed: %s", exc)
        return 1

    logger.info(
        "seed_moe_rdb finished: upserted=%d skipped=%d",
        summary["upserted"],
        summary["skipped"],
    )
    sys.stdout.write(
        f"upserted={summary['upserted']} skipped={summary['skipped']}\n"
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI invocation
    raise SystemExit(main())
