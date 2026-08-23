"""Load an operator-supplied national checklist as ``source="authority"`` names.

The bundled IOC names (see :mod:`echoroo.services.vernacular_bundle`) cover
the global BirdNET species set. A national checklist — for Japan the
日本鳥類目録改訂第8版 (Ornithological Society of Japan) — is the higher
authority for display names but is not redistributable with the
application, so the operator obtains it themselves, converts it with
``apps/api/scripts/convert_osj_checklist.py`` and loads the resulting CSV
with this script::

    docker exec echoroo-backend uv run python -m echoroo.scripts.load_authority_checklist \\
        /path/to/osj8_ja.csv --confirm

CSV format (UTF-8, header row required)::

    scientific_name,name
    Passer montanus,スズメ

Rows are upserted into ``taxon_vernacular_names`` under
``(locale, source="authority")`` via the same race-safe loader the bundle
uses; the display resolver ranks ``authority`` above every other source, so
the checklist name wins wherever it differs from the IOC one. The bundled
BirdNET→AviList crosswalk is applied as well so a taxon whose BirdNET name
differs from the checklist's still resolves. Re-running with a newer CSV is
idempotent. ``--confirm`` is mandatory (mirrors ``seed_moe_rdb``).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from echoroo.core.database import AsyncSessionLocal
from echoroo.services.vernacular_bundle import (
    VernacularLoadResult,
    load_vernacular_rows,
    read_bundled_birdnet_crosswalk,
)

logger = logging.getLogger(__name__)

AUTHORITY_SOURCE = "authority"


def read_checklist_csv(csv_path: Path) -> list[tuple[str, str]]:
    """Read ``scientific_name,name`` rows; blank cells are skipped."""
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"scientific_name", "name"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required column(s): {sorted(missing)}")
        rows: list[tuple[str, str]] = []
        for record in reader:
            sci = (record.get("scientific_name") or "").strip()
            name = (record.get("name") or "").strip()
            if sci and name:
                rows.append((sci, name))
    return rows


async def load_checklist(csv_path: Path, *, locale: str) -> VernacularLoadResult:
    """Load the CSV into the database in one transaction."""
    rows = read_checklist_csv(csv_path)
    if not rows:
        raise ValueError(f"{csv_path} contains no usable rows")
    crosswalk = read_bundled_birdnet_crosswalk()
    async with AsyncSessionLocal() as session:
        try:
            result = await load_vernacular_rows(
                session,
                rows,
                source=AUTHORITY_SOURCE,
                locale=locale,
                crosswalk=crosswalk,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="echoroo.scripts.load_authority_checklist",
        description=(
            "UPSERT an operator-supplied national checklist CSV into "
            "taxon_vernacular_names under source='authority'."
        ),
    )
    parser.add_argument("csv_path", type=Path, help="CSV with scientific_name,name columns")
    parser.add_argument("--locale", default="ja", help="Locale of the names (default: ja)")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required acknowledgement that this script mutates taxon_vernacular_names.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    if not args.confirm:
        print("Refusing to run without --confirm (this mutates taxon_vernacular_names).")
        return 2
    if not args.csv_path.is_file():
        print(f"CSV not found: {args.csv_path}", file=sys.stderr)
        return 2

    result = asyncio.run(load_checklist(args.csv_path, locale=args.locale))
    print(
        f"authority load ({args.locale}): {result.matched_taxa} taxa matched "
        f"({result.inserted} inserted, {result.updated} updated, "
        f"{result.unchanged} unchanged); {result.unmatched_names} checklist rows unused"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
