"""Loader for the bundled, versioned vernacular-name datasets.

Japanese display names ship *inside* the package (``echoroo.data.vernacular``)
rather than being scraped from GBIF/iNaturalist at runtime: the bundled list is
versioned, reproducible, offline-installable and taxonomically consistent,
whereas the API-sourced names flap between kanji and katakana and are only as
complete as a taxon's GBIF key coverage.

The primary bundled source is the IOC World Bird List (Multilingual), stored
with ``source="ioc"``. Because the BirdNET V2.4 labels that seed ``taxa``
follow eBird/Clements, a crosswalk maps BirdNET scientific names onto the
AviList concept the IOC list uses (``Accipiter gularis`` → ``Tachyspiza
gularis`` → ツミ).

The same loader is reused for an operator-supplied national checklist: call
:func:`load_vernacular_rows` with ``source="authority"`` and the rows parsed
from that CSV, and the display resolver in ``services/vernacular.py`` will rank
it above the bundled IOC names.
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName

logger = logging.getLogger(__name__)

# Package holding the generated bundle (see scripts/build_vernacular_bundle.py).
_DATA_PACKAGE = "echoroo.data.vernacular"
_IOC_JA_CSV = "ioc_ja.csv"
_IOC_JA_META = "ioc_ja.meta.json"
_BIRDNET_CROSSWALK_CSV = "birdnet_crosswalk.csv"
_BIRDNET_CROSSWALK_META = "birdnet_crosswalk.meta.json"

# Rows per INSERT ... ON CONFLICT statement. Keeps each statement's parameter
# list comfortably inside asyncpg limits for the ~6.5k-row bundled load.
_UPSERT_CHUNK = 1000

# Mirrors ``TaxonVernacularName.name`` (String(300)); longer names are clipped
# rather than raising a DataError mid-load.
_NAME_MAX = 300

# Provenance value written for the bundled IOC names. Must be a member of
# ``repositories.taxon._VERNACULAR_SOURCE_ALLOWED`` and rank in
# ``services.vernacular._SOURCE_RANK``.
BUNDLED_JA_SOURCE = "ioc"
BUNDLED_JA_LOCALE = "ja"


@dataclass(frozen=True)
class VernacularLoadResult:
    """Outcome of a bundled vernacular-name load.

    Attributes:
        matched_taxa: Taxa that found a name in the supplied map.
        inserted: New ``taxon_vernacular_names`` rows created.
        updated: Existing rows whose ``name`` changed.
        unchanged: Existing rows that already held the desired name.
        unmatched_names: Entries in the supplied map that no taxon consumed
            (the bundled lists are global, so most of these are simply species
            BirdNET does not model).
    """

    matched_taxa: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    unmatched_names: int = 0


async def load_vernacular_rows(
    db: AsyncSession,
    rows: Iterable[tuple[str, str]],
    *,
    source: str,
    locale: str,
    crosswalk: Mapping[str, str] | None = None,
) -> VernacularLoadResult:
    """Upsert ``(scientific_name, name)`` pairs onto matching taxa.

    Every taxon is looked up by its scientific name, optionally translated
    through ``crosswalk`` first. When the crosswalk target is absent from the
    name map we retry with the taxon's own scientific name, so a mapping hop
    can never *lose* a name that a direct lookup would have found.

    Exactly two read queries are issued regardless of dataset size (all taxa,
    then all existing rows for ``(locale, source)``); those only drive the
    counters. The write itself is ``INSERT ... ON CONFLICT (taxon_id, locale,
    source) DO UPDATE`` in chunks, so two loads racing each other (e.g. a
    double-dispatched admin action, or the seed hook overlapping a manual
    reload) converge on the same rows instead of one of them failing with an
    ``IntegrityError``. The caller owns the transaction — mirroring
    ``services.taxon_seeder.seed_birdnet_taxa``.

    Rows are written with ``is_primary=False``: primacy is a per-taxon curation
    decision, and the display resolver already ranks sources deterministically.

    Args:
        db: Active async session (caller commits).
        rows: ``(scientific_name, vernacular_name)`` pairs.
        source: Provenance value, e.g. ``"ioc"`` or ``"authority"``.
        locale: Locale code the names belong to, e.g. ``"ja"``.
        crosswalk: Optional ``taxon_scientific_name -> lookup_key`` map used
            when the taxa table and the name list follow different taxonomies.

    Returns:
        A :class:`VernacularLoadResult` summarising the load.
    """
    name_map: dict[str, str] = {}
    for scientific_name, name in rows:
        key = scientific_name.strip()
        value = name.strip()
        if key and value:
            name_map[key] = value[:_NAME_MAX]

    if not name_map:
        logger.warning(
            "Vernacular load skipped: empty name map (source=%s locale=%s)",
            source,
            locale,
        )
        return VernacularLoadResult()

    taxa_result = await db.execute(select(Taxon.id, Taxon.scientific_name))
    taxa = list(taxa_result.all())

    existing_by_taxon = await _existing_names(db, locale=locale, source=source)

    matched_taxa = 0
    inserted = 0
    updated = 0
    unchanged = 0
    consumed_keys: set[str] = set()
    now = datetime.now(UTC)
    pending: list[dict[str, object]] = []

    for taxon_id, scientific_name in taxa:
        if not scientific_name:
            continue
        # Try the crosswalk hop first, then the taxon's own scientific name:
        # a hop whose target is missing from the list must never *lose* a name
        # that a direct lookup would have found.
        mapped = crosswalk.get(scientific_name) if crosswalk else None
        candidate_keys = [mapped, scientific_name] if mapped is not None else [scientific_name]
        resolved: str | None = None
        for candidate in candidate_keys:
            resolved = name_map.get(candidate)
            if resolved is not None:
                consumed_keys.add(candidate)
                break
        if resolved is None:
            continue

        matched_taxa += 1
        current_name = existing_by_taxon.get(taxon_id)
        if current_name is None:
            inserted += 1
        elif current_name != resolved:
            updated += 1
        else:
            unchanged += 1
            continue
        pending.append(
            {
                "id": uuid4(),
                "taxon_id": taxon_id,
                "locale": locale,
                "name": resolved,
                "source": source,
                "is_primary": False,
                "created_at": now,
                "updated_at": now,
            }
        )

    # Race-safe write. The counters above come from a snapshot read; if another
    # loader inserted the same (taxon_id, locale, source) row in between, the
    # ON CONFLICT clause turns our insert into an update (or a no-op when the
    # name already matches) instead of raising. ``is_primary`` is deliberately
    # not in the update set: primacy is a curation flag owned by operators.
    for start in range(0, len(pending), _UPSERT_CHUNK):
        chunk = pending[start : start + _UPSERT_CHUNK]
        stmt = pg_insert(TaxonVernacularName).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_taxon_vernacular_locale_source",
            set_={
                "name": stmt.excluded.name,
                "updated_at": stmt.excluded.updated_at,
            },
            where=TaxonVernacularName.name.is_distinct_from(stmt.excluded.name),
        )
        await db.execute(stmt)
    await db.flush()

    result = VernacularLoadResult(
        matched_taxa=matched_taxa,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        unmatched_names=len(name_map) - len(consumed_keys),
    )
    logger.info(
        "Vernacular load (source=%s locale=%s): %d taxa matched "
        "(%d inserted, %d updated, %d unchanged); %d list entries unused",
        source,
        locale,
        result.matched_taxa,
        result.inserted,
        result.updated,
        result.unchanged,
        result.unmatched_names,
    )
    return result


async def _existing_names(db: AsyncSession, *, locale: str, source: str) -> dict[UUID, str]:
    """Snapshot ``{taxon_id: name}`` for every row of ``(locale, source)``.

    Column tuples rather than ORM instances on purpose: the write path below
    bypasses the ORM (``INSERT ... ON CONFLICT``), so loading entities here
    would leave stale objects in the session's identity map.
    """
    result = await db.execute(
        select(TaxonVernacularName.taxon_id, TaxonVernacularName.name)
        .where(TaxonVernacularName.locale == locale)
        .where(TaxonVernacularName.source == source)
    )
    return dict(result.tuples().all())


def _read_text(name: str) -> str:
    """Read a file from the bundled data package (indirection for tests)."""
    return files(_DATA_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def _read_meta(name: str) -> dict[str, object]:
    data = json.loads(_read_text(name))
    if not isinstance(data, dict):
        raise ValueError(f"Bundle metadata {name} is not a JSON object")
    return data


def _check_row_count(label: str, actual: int, meta: Mapping[str, object], key: str) -> None:
    """Fail loudly when a bundled CSV does not match its sidecar metadata.

    The bundle is release-critical static data: a truncated CSV with an intact
    header would otherwise load partial names without any signal. The sidecar
    is written by the same build script run, so a mismatch always means the
    package is corrupt or was hand-edited.
    """
    expected = meta.get(key)
    if not isinstance(expected, int) or expected <= 0:
        raise ValueError(f"Bundle metadata for {label} lacks a positive '{key}' count")
    if actual != expected:
        raise ValueError(
            f"Bundled {label} has {actual} rows but its metadata declares {expected}; "
            "regenerate the bundle with scripts/build_vernacular_bundle.py"
        )


def read_bundled_ja_names() -> list[tuple[str, str]]:
    """Read the packaged IOC Japanese-name list, validated against its metadata."""
    rows = [
        (record["scientific_name"], record["name"])
        for record in csv.DictReader(_read_text(_IOC_JA_CSV).splitlines())
    ]
    _check_row_count(_IOC_JA_CSV, len(rows), _read_meta(_IOC_JA_META), "rows")
    return rows


def read_bundled_birdnet_crosswalk() -> dict[str, str]:
    """Read the packaged BirdNET → AviList crosswalk, validated against its metadata."""
    crosswalk = {
        record["birdnet_scientific_name"]: record["avilist_scientific_name"]
        for record in csv.DictReader(_read_text(_BIRDNET_CROSSWALK_CSV).splitlines())
    }
    _check_row_count(
        _BIRDNET_CROSSWALK_CSV,
        len(crosswalk),
        _read_meta(_BIRDNET_CROSSWALK_META),
        "resolved",
    )
    return crosswalk


async def load_bundled_ja_names(db: AsyncSession) -> VernacularLoadResult:
    """Load the bundled IOC Japanese names onto the local taxa.

    Idempotent: re-running only rewrites rows whose name actually changed
    (e.g. after the bundle is regenerated from a newer IOC release).

    Args:
        db: Active async session. The caller commits.

    Returns:
        A :class:`VernacularLoadResult` summarising the load.
    """
    return await load_vernacular_rows(
        db,
        read_bundled_ja_names(),
        source=BUNDLED_JA_SOURCE,
        locale=BUNDLED_JA_LOCALE,
        crosswalk=read_bundled_birdnet_crosswalk(),
    )
