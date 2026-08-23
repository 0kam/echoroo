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

    scientific_name,category,sensitivity_h3_res,notes
    "Nipponia nippon","CR",5,"Endemic to Sado"
    "Ketupa blakistoni","EN",5,
    "Tringa guttifer","VU",7,"BirdLife Japan list 2025"

Columns:

* ``scientific_name``: Scientific name of the taxon. Required. Resolved to
  the local ``taxa.id`` UUID via
  :func:`echoroo.services.taxon_resolution.resolve_taxon_ids_by_scientific_name`
  (exact match, then the bundled BirdNET<->AviList crosswalk in both
  directions). Migration 0034 re-keyed ``taxon_sensitivities.taxon_id`` from
  a "GBIF species key" string onto ``taxa.id``, because the previous
  key-space was written differently by every producer and never matched the
  reader. Rows whose name has no local counterpart are **skipped with a
  warning and counted**, not aborted — a partial RDB seed is better than
  none, and the operator gets an explicit list to reconcile.
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

Exit codes::

    0  rows imported
    1  unexpected error (stack trace logged)
    2  --confirm not supplied
    3  CSV file not found
    4  rows were processed but NONE were imported (usually: the ``taxa``
       table has not been seeded yet, so nothing resolves)
    5  CSV header does not match the contract above
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from echoroo.core.database import AsyncSessionLocal
from echoroo.models.enums import TaxonSensitivitySource
from echoroo.services.taxon_resolution import (
    collapse_strictest,
    log_unresolved_sample,
    resolve_taxon_ids_by_scientific_name,
)
from echoroo.services.taxon_sensitivity_service import upsert_taxon_sensitivity

logger = logging.getLogger("echoroo.scripts.seed_moe_rdb")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


# Mirrors the CHECK constraint ``ck_taxon_sensitivities_h3_discrete``
# (FR-027). Surfaced here so the script raises a friendly error before
# the database does.
_VALID_H3_RES: frozenset[int] = frozenset({2, 5, 7, 9, 15})

#: Columns the CSV MUST provide. ``category`` / ``notes`` stay optional.
#: Checked up front so an old ``taxon_id``-shaped CSV (the pre-0034 contract)
#: fails immediately with a readable message instead of reporting every row
#: as "missing scientific_name".
_REQUIRED_COLUMNS: tuple[str, ...] = ("scientific_name", "sensitivity_h3_res")


class CsvContractError(ValueError):
    """Raised when the CSV header does not match the documented contract."""


def _validate_header(fieldnames: Sequence[str] | None) -> None:
    """Fail fast when the CSV header is missing a required column.

    Migration 0034 replaced the old ``taxon_id`` (GBIF key) column with
    ``scientific_name``. An operator re-running last year's export would
    otherwise see "0 upserted, N skipped" and have to guess why.
    """
    present = {(name or "").strip() for name in (fieldnames or [])}
    missing = [column for column in _REQUIRED_COLUMNS if column not in present]
    if not missing:
        return
    hint = ""
    if "taxon_id" in present and "scientific_name" in missing:
        hint = (
            " This CSV looks like the pre-0034 format (it has a 'taxon_id' "
            "column). The masking tables are now keyed on taxa.id and the "
            "seeder resolves rows by scientific name; replace the 'taxon_id' "
            "column with 'scientific_name'."
        )
    raise CsvContractError(
        f"CSV header is missing required column(s): {', '.join(missing)}. "
        f"Expected at least {', '.join(_REQUIRED_COLUMNS)}; "
        f"found {', '.join(sorted(present)) or '(no header)'}.{hint}"
    )


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

    Returns a summary dict:
    ``{"upserted": N, "skipped": M, "unresolved": K}``.

    The whole import runs inside one transaction so a CSV with a bad
    row in the middle leaves the table untouched. For very large CSVs
    (>>10k rows) this could be split into batches; the MoE RDB is
    well under that scale (a few thousand entries) so the simpler
    one-transaction approach is safer.

    Two kinds of "not imported" are tracked separately:

    * ``skipped``   — the row itself is unusable (blank ``scientific_name``).
    * ``unresolved`` — the row is well-formed but its scientific name has no
      counterpart in the local ``taxa`` table. Warned and counted rather than
      raised, so one stale name cannot discard an otherwise good edition.

    A malformed / out-of-range ``sensitivity_h3_res`` still aborts: that is an
    operator typo with safety consequences (FR-027), not upstream drift. So
    does a header that does not match the documented contract.

    Duplicate collapse: two CSV rows can land on the same local taxon (e.g.
    subspecies listed separately, or a BirdNET split lumped by the bundled
    crosswalk). They are collapsed to the STRICTEST ``sensitivity_h3_res``
    via :func:`echoroo.services.taxon_resolution.collapse_strictest` before
    any upsert, so row order can never decide how strongly a species is
    masked. ``upserted`` therefore counts unique taxa, not CSV lines.
    """
    upserted = 0
    skipped = 0
    unresolved = 0

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        _validate_header(reader.fieldnames)
        rows = list(reader)

    async with AsyncSessionLocal() as session:
        try:
            # ONE lookup for the whole file (migration 0034 re-keyed the
            # table onto ``taxa.id``).
            name_to_taxon = await resolve_taxon_ids_by_scientific_name(
                session,
                ((row.get("scientific_name") or "") for row in rows),
            )

            unresolved_names: list[str] = []
            candidates: list[tuple[UUID, int, str | None, str | None]] = []
            for row_number, row in enumerate(rows, start=2):
                # row_number starts at 2 because line 1 is the header
                scientific_name = (row.get("scientific_name") or "").strip()
                if not scientific_name:
                    logger.warning(
                        "row %d: missing scientific_name — skipping", row_number
                    )
                    skipped += 1
                    continue

                h3_raw = (row.get("sensitivity_h3_res") or "").strip()
                try:
                    h3_res = int(h3_raw)
                except ValueError:
                    logger.error(
                        "row %d (scientific_name=%s): sensitivity_h3_res=%r "
                        "is not an integer — aborting",
                        row_number,
                        scientific_name,
                        h3_raw,
                    )
                    raise

                if h3_res not in _VALID_H3_RES:
                    logger.error(
                        "row %d (scientific_name=%s): sensitivity_h3_res=%d "
                        "is not in %s — aborting (FR-027)",
                        row_number,
                        scientific_name,
                        h3_res,
                        sorted(_VALID_H3_RES),
                    )
                    raise ValueError(
                        f"sensitivity_h3_res={h3_res} is not one of "
                        f"{sorted(_VALID_H3_RES)} (FR-027)"
                    )

                taxon_uuid = name_to_taxon.get(scientific_name)
                if taxon_uuid is None:
                    logger.warning(
                        "row %d: scientific_name=%r has no matching local "
                        "taxon — skipping",
                        row_number,
                        scientific_name,
                    )
                    unresolved += 1
                    unresolved_names.append(scientific_name)
                    continue

                category = (row.get("category") or "").strip() or None
                notes = (row.get("notes") or "").strip() or None

                candidates.append((taxon_uuid, h3_res, category, notes))

            collapsed = collapse_strictest(candidates)
            if len(collapsed) != len(candidates):
                logger.info(
                    "seed_moe_rdb: %d CSV row(s) collapsed to %d unique "
                    "taxa (strictest sensitivity_h3_res wins)",
                    len(candidates),
                    len(collapsed),
                )
            for taxon_uuid, (h3_res, category, notes) in collapsed.items():
                await upsert_taxon_sensitivity(
                    session,
                    taxon_id=taxon_uuid,
                    source=TaxonSensitivitySource.MOE_RDB,
                    sensitivity_h3_res=h3_res,
                    category=category,
                    notes=notes,
                )
                upserted += 1

            log_unresolved_sample(logger, "seed_moe_rdb", unresolved_names)
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return {"upserted": upserted, "skipped": skipped, "unresolved": unresolved}


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
    except CsvContractError as exc:
        # Operator-facing contract problem — a stack trace would only bury
        # the one line that tells them how to fix the file.
        logger.error("seed_moe_rdb: %s", exc)
        return 5
    except Exception as exc:  # noqa: BLE001 — top-level CLI guard
        logger.exception("seed_moe_rdb failed: %s", exc)
        return 1

    logger.info(
        "seed_moe_rdb finished: upserted=%d skipped=%d unresolved=%d",
        summary["upserted"],
        summary["skipped"],
        summary["unresolved"],
    )
    sys.stdout.write(
        f"upserted={summary['upserted']} skipped={summary['skipped']} "
        f"unresolved={summary['unresolved']}\n"
    )
    sys.stdout.flush()

    # A run that processed rows but wrote nothing is a misconfiguration, not a
    # success: either the taxa table has not been seeded yet or the CSV uses
    # names this deployment cannot resolve. Exiting non-zero stops a bootstrap
    # script from marching on as if masking data were in place.
    processed = summary["upserted"] + summary["skipped"] + summary["unresolved"]
    if processed and summary["upserted"] == 0:
        logger.error(
            "seed_moe_rdb processed %d row(s) but upserted none. Seed the "
            "taxa table first (Admin -> Settings -> 'Seed BirdNET taxa'); "
            "every row is resolved by scientific name against taxa.",
            processed,
        )
        return 4
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI invocation
    raise SystemExit(main())
