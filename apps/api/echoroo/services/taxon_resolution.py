"""Resolve external scientific names onto local ``taxa.id`` UUIDs.

Both writers of the sensitive-species masking tables receive *scientific
names* from an upstream authority and must land them on the platform's
immutable species identity (``taxa.id``):

* :mod:`echoroo.workers.iucn_sync` — IUCN Red List snapshot rows.
* :mod:`echoroo.scripts.seed_moe_rdb` — Japanese MoE Red Data Book CSV.

Before migration 0034 both wrote a ``VARCHAR(64)`` "GBIF species key", except
the IUCN worker actually wrote the IUCN SIS ``taxonid`` and the reader
compared against ``str(tag.gbif_taxon_key)`` — three key-spaces, so
IUCN-sourced masking never matched anything. This module is the single place
that turns an upstream name into a ``taxa.id``.

Matching strategy (deliberately conservative — a wrong match would mask the
wrong species, or fail to mask a sensitive one):

1. Exact match against ``taxa.scientific_name``.
2. Bundled BirdNET -> AviList crosswalk, **forward**: the local ``taxa`` rows
   are seeded from BirdNET V2.4 labels (eBird/Clements), so an upstream name
   that happens to be a BirdNET name is mapped to its AviList counterpart and
   looked up again.
3. The same crosswalk, **reverse**: upstream authorities (IUCN, IOC-aligned
   national lists) usually publish the AviList/IOC concept, so an AviList name
   is mapped back to the BirdNET name that ``taxa`` actually stores.

   The reverse direction is **not** injective. AviList lumps species that
   BirdNET/eBird splits, so several BirdNET labels can share one AviList
   name. Inverting the dict blindly would keep whichever BirdNET label
   iterated last and mask (or fail to mask) an arbitrary one of the split
   taxa. :func:`build_reverse_crosswalk` therefore keeps only the AviList
   names that map from **exactly one** BirdNET name; ambiguous targets are
   dropped and reported once per call.

Names that survive all three steps are simply absent from the returned dict;
callers count and skip them rather than aborting, because a partial Red List
sync is strictly better than none.

Exactly ONE ``SELECT id, scientific_name FROM taxa`` is issued per call — the
table is ~6.5k rows, and the alternative (a lookup per snapshot row) would
issue tens of thousands of round-trips inside the sync transaction.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.services.vernacular_bundle import read_bundled_birdnet_crosswalk

logger = logging.getLogger(__name__)

#: How many unresolved names a caller should log before truncating. Shared so
#: the IUCN worker and the MoE seeder report at the same verbosity.
UNRESOLVED_LOG_SAMPLE = 10


def _normalise(name: str | None) -> str:
    """Trim surrounding whitespace; return ``""`` for missing names."""
    return (name or "").strip()


def build_reverse_crosswalk(forward: Mapping[str, str]) -> dict[str, str]:
    """Invert a BirdNET -> AviList crosswalk, dropping ambiguous targets.

    AviList lumps a number of species that BirdNET/eBird splits, so ``forward``
    is many-to-one and a naive ``{v: k for k, v in ...}`` inversion silently
    keeps whichever BirdNET label iterated last. For masking that is worse
    than no match at all: an IUCN row for the lumped species would be applied
    to one arbitrary member of the split and leave its siblings unmasked.

    Only AviList names reachable from **exactly one** BirdNET name survive.
    Ambiguous ones are omitted so the caller falls through to "unresolved",
    which is counted, logged and skipped.

    Args:
        forward: ``{birdnet_scientific_name: avilist_scientific_name}``.

    Returns:
        ``{avilist_scientific_name: birdnet_scientific_name}`` restricted to
        unambiguous pairs.
    """
    counts: dict[str, int] = {}
    for avilist in forward.values():
        counts[avilist] = counts.get(avilist, 0) + 1

    reverse = {
        avilist: birdnet
        for birdnet, avilist in forward.items()
        if counts[avilist] == 1
    }

    ambiguous = len(counts) - len(reverse)
    if ambiguous:
        logger.info(
            "birdnet crosswalk: %d AviList name(s) map from more than one "
            "BirdNET name (lumped species); excluded from reverse lookup to "
            "avoid masking an arbitrary member of the split",
            ambiguous,
        )
    return reverse


def collapse_strictest(
    rows: Iterable[tuple[UUID, int, str | None, str | None]],
) -> dict[UUID, tuple[int, str | None, str | None]]:
    """Collapse per-taxon duplicates to the STRICTEST recommendation.

    Several upstream rows can land on the same local taxon within a single
    run: the bundled crosswalk maps a BirdNET split onto one AviList concept,
    an RDB CSV may list subspecies separately, and the IUCN snapshot can carry
    both an accepted name and a synonym. Upserting them one by one would make
    the *last* row win — which is a coin flip that can silently relax masking.

    We instead pick the minimum ``sensitivity_h3_res`` (lowest number = most
    masking), matching the "most conservative wins" rule that
    :func:`echoroo.services.taxon_sensitivity_service.bulk_load_sensitivity_map`
    already applies when collapsing across *sources*. The category / notes of
    the winning (strictest) row travel with it so the metadata stays coherent
    with the resolution actually stored.

    Ties keep the first-seen row, so the result is independent of input order
    for the value that matters (``sensitivity_h3_res``).

    Args:
        rows: ``(taxon_id, sensitivity_h3_res, category, notes)`` tuples.

    Returns:
        ``{taxon_id: (sensitivity_h3_res, category, notes)}`` with one entry
        per unique taxon.
    """
    collapsed: dict[UUID, tuple[int, str | None, str | None]] = {}
    for taxon_id, h3_res, category, notes in rows:
        current = collapsed.get(taxon_id)
        if current is None or h3_res < current[0]:
            collapsed[taxon_id] = (h3_res, category, notes)
    return collapsed


async def resolve_taxon_ids_by_scientific_name(
    session: AsyncSession,
    names: Iterable[str],
) -> dict[str, UUID]:
    """Map upstream scientific names onto local ``taxa.id`` values.

    Args:
        session: Active async session. Read-only; the caller owns the
            transaction.
        names: Upstream scientific names. Duplicates and blanks are tolerated.

    Returns:
        ``{input_name: taxa.id}`` containing only the names that resolved.
        The key is the caller's *original* (whitespace-trimmed) string so the
        caller can zip the result back onto its own rows.
    """
    wanted = {n for n in (_normalise(name) for name in names) if n}
    if not wanted:
        return {}

    result = await session.execute(sa.select(Taxon.id, Taxon.scientific_name))
    by_name: dict[str, UUID] = {
        scientific_name: taxon_id
        for taxon_id, scientific_name in result.all()
        if scientific_name
    }

    try:
        forward = read_bundled_birdnet_crosswalk()
    except Exception as exc:  # noqa: BLE001 — bundle is optional at runtime
        logger.warning(
            "birdnet crosswalk unavailable; falling back to exact-name "
            "matching only: %r",
            exc,
        )
        forward = {}
    # AviList -> BirdNET, unambiguous pairs only. Built once per call; the
    # bundle is ~6.5k rows.
    reverse = build_reverse_crosswalk(forward)

    resolved: dict[str, UUID] = {}
    for name in wanted:
        taxon_id = by_name.get(name)
        if taxon_id is None:
            crosswalked = forward.get(name)
            if crosswalked is not None:
                taxon_id = by_name.get(crosswalked)
        if taxon_id is None:
            crosswalked = reverse.get(name)
            if crosswalked is not None:
                taxon_id = by_name.get(crosswalked)
        if taxon_id is not None:
            resolved[name] = taxon_id

    return resolved


def log_unresolved_sample(
    logger_: logging.Logger,
    prefix: str,
    unresolved: Iterable[str],
) -> None:
    """Log up to :data:`UNRESOLVED_LOG_SAMPLE` unresolved names at INFO.

    Kept here so the IUCN worker and the MoE seeder emit the same shape and
    an operator grepping for "unresolved" finds both.
    """
    sample = sorted(set(unresolved))
    if not sample:
        return
    logger_.info(
        "%s: %d scientific name(s) did not resolve to a local taxon; "
        "sample=%s",
        prefix,
        len(sample),
        sample[:UNRESOLVED_LOG_SAMPLE],
    )


__all__ = [
    "UNRESOLVED_LOG_SAMPLE",
    "build_reverse_crosswalk",
    "collapse_strictest",
    "log_unresolved_sample",
    "resolve_taxon_ids_by_scientific_name",
]
