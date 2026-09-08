"""Operator bulk-import of taxa (WS-A v2 slice 6).

The catalogue seeded from the BirdNET V2.4 label list only covers the species
BirdNET models. Two groups of desired taxa are therefore missing:

* **non-birds** an operator annotates by ear anyway — *Cervus nippon*
  (ニホンジカ), Anura (frogs), Orthoptera (crickets);
* the ~84 Japanese endemics and rarities absent from BirdNET (メグロ,
  ノグチゲラ, ヤンバルクイナ, …) whose 和名 already sit unused in the loaded
  national checklist (``source="authority"``) waiting for a taxon to attach to.

This module materialises such a list. It is deliberately **network-free and
transactional**: the caller owns the transaction (mirroring
:func:`echoroo.services.vernacular_bundle.load_vernacular_rows` and
:func:`echoroo.services.taxon_seeder.seed_birdnet_taxa`), so an operator gets
immediate per-row feedback instead of a fire-and-forget task id.

External identity is NOT resolved here. Newly created rows leave
``col_xr_resolved_at`` NULL, which is exactly the selection predicate of
:func:`echoroo.services.taxon.resolve_col_xr_batch`; the caller dispatches that
resolver afterwards and identity columns, the identity-history journal and the
concept relations all follow asynchronously. Creating a taxon is not an
identity *change*, so nothing is journalled at import time — the first
resolution pass writes the initial identity.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.repositories.taxon import normalize_locale
from echoroo.services.vernacular_bundle import load_vernacular_rows

logger = logging.getLogger(__name__)

#: Provenance written for the supplied vernacular names. Operator-curated names
#: outrank the bundled IOC list ("ioc") but stay below a loaded national
#: checklist ("authority") — see ``services.vernacular._SOURCE_RANK``.
IMPORT_VERNACULAR_SOURCE = "user"

#: Rank stamped on a created taxon when the entry does not specify one. The
#: overwhelming majority of imports are species-level.
DEFAULT_RANK = "SPECIES"

#: Mirrors ``Taxon.scientific_name`` (String(300)) / ``Taxon.rank`` (String(50)).
_SCIENTIFIC_NAME_MAX = 300
_RANK_MAX = 50

#: Rejection reasons. Stable strings — they are surfaced to the operator and
#: asserted on by tests.
REASON_EMPTY = "empty scientific name"
REASON_DUPLICATE = "duplicate in payload"
REASON_NAME_TOO_LONG = "scientific name exceeds 300 characters"
REASON_RANK_TOO_LONG = "rank exceeds 50 characters"


@dataclass(frozen=True)
class BulkImportEntry:
    """One requested taxon.

    Attributes:
        scientific_name: Canonical scientific name; whitespace is normalized.
        vernacular_name: Optional display name to attach (``source="user"``).
        locale: Locale of ``vernacular_name``; defaults to the call's
            ``default_locale``. Normalized (``ja-JP``/``jpn`` → ``ja``).
        rank: Taxonomic rank for a newly created row; defaults to
            :data:`DEFAULT_RANK`. Ignored for a taxon that already exists.
    """

    scientific_name: str
    vernacular_name: str | None = None
    locale: str | None = None
    rank: str | None = None


@dataclass(frozen=True)
class BulkImportRejection:
    """An entry that was not imported, with the reason why."""

    scientific_name: str
    reason: str


@dataclass(frozen=True)
class BulkImportResult:
    """Outcome of a :func:`bulk_import_taxa` call.

    Attributes:
        created: Taxa inserted by this call.
        existing: Requested taxa that already had a row (never duplicated; a
            supplied vernacular name is still applied to them).
        vernacular_upserts: Vernacular rows written (inserted or rewritten).
        vernacular_unchanged: Vernacular rows that already held the same name.
        rejected: Entries that were skipped, with their reason.
    """

    created: int = 0
    existing: int = 0
    vernacular_upserts: int = 0
    vernacular_unchanged: int = 0
    rejected: tuple[BulkImportRejection, ...] = field(default_factory=tuple)


def normalize_scientific_name(raw: str) -> str:
    """Trim and collapse internal whitespace in a scientific name.

    Operators paste names out of spreadsheets and PDFs, so ``"  Cervus
    nippon "`` and ``"Cervus  nippon"`` must reach the same business key as
    ``"Cervus nippon"`` — otherwise the unique ``scientific_name`` constraint
    would happily accept a near-duplicate row.

    No truncation happens here: a name longer than the column allows is a
    garbage input and is REJECTED by the caller rather than silently keyed on
    its first 300 characters (which could alias two different inputs).
    """
    return " ".join(raw.split())


async def bulk_import_taxa(
    db: AsyncSession,
    entries: list[BulkImportEntry],
    *,
    default_locale: str = "ja",
    actor_user_id: UUID | None = None,
) -> BulkImportResult:
    """Create the requested taxa and attach their operator-supplied names.

    Semantics per entry:

    * the scientific name is normalized; an empty one is rejected;
    * a name repeated within the payload keeps the FIRST occurrence and rejects
      the later ones (a payload cannot express two different intents for one
      business key);
    * an already-known taxon is counted as ``existing`` and is NOT duplicated,
      but a supplied vernacular name is still upserted onto it — importing
      "*Apalopteron familiare* / メグロ" must fix a missing 和名 even when the
      taxon itself arrived by an earlier route;
    * new taxa are created with one ``INSERT ... ON CONFLICT (scientific_name)
      DO NOTHING RETURNING`` statement, so ``created`` counts exactly the rows
      THIS call inserted — an entry that loses a concurrent race is counted as
      ``existing`` and the winner's row (rank included) is left untouched;
    * a name longer than the column (300) or a rank longer than 50 characters
      is rejected, never silently truncated.

    Vernacular names are batched **per locale**, so the number of loader calls
    is O(locales) rather than O(entries) — each call scans the taxa table once.

    The caller owns the transaction and must commit. Nothing here touches the
    network.

    Args:
        db: Active async session.
        entries: Requested taxa.
        default_locale: Locale used for entries that do not state one.
        actor_user_id: Operator behind the import; recorded in the log line
            (the platform audit row is written by the endpoint).

    Returns:
        A :class:`BulkImportResult` with the per-outcome counts.
    """
    fallback_locale = normalize_locale(default_locale) or "ja"

    rejected: list[BulkImportRejection] = []
    accepted: list[tuple[str, BulkImportEntry]] = []
    seen: set[str] = set()

    for entry in entries:
        name = normalize_scientific_name(entry.scientific_name)
        if not name:
            rejected.append(BulkImportRejection(entry.scientific_name, REASON_EMPTY))
            continue
        if len(name) > _SCIENTIFIC_NAME_MAX:
            rejected.append(
                BulkImportRejection(entry.scientific_name, REASON_NAME_TOO_LONG)
            )
            continue
        if entry.rank is not None and len(entry.rank.strip()) > _RANK_MAX:
            rejected.append(BulkImportRejection(name, REASON_RANK_TOO_LONG))
            continue
        if name in seen:
            rejected.append(BulkImportRejection(name, REASON_DUPLICATE))
            continue
        seen.add(name)
        accepted.append((name, entry))

    if not accepted:
        return BulkImportResult(rejected=tuple(rejected))

    # The pre-read splits the payload into known/unknown for the write below;
    # the write itself is race-safe regardless: INSERT ... ON CONFLICT
    # (scientific_name) DO NOTHING RETURNING tells us exactly which rows THIS
    # call created, so a concurrent import that wins the race turns our entry
    # into "existing" instead of an IntegrityError or a miscount.
    known = await _known_names(db, [name for name, _ in accepted])

    now = datetime.now(UTC)
    pending_rows = [
        {
            "id": uuid4(),
            "scientific_name": name,
            "rank": _normalize_rank(entry.rank),
            "is_non_biological": False,
            "created_at": now,
            "updated_at": now,
        }
        for name, entry in accepted
        if name not in known
    ]
    actually_created: set[str] = set()
    if pending_rows:
        insert_stmt = (
            pg_insert(Taxon)
            .values(pending_rows)
            .on_conflict_do_nothing(index_elements=["scientific_name"])
            .returning(Taxon.scientific_name)
        )
        actually_created = set((await db.execute(insert_stmt)).scalars().all())

    created = len(actually_created)
    existing = len(accepted) - created

    # Vernacular names grouped by locale so the loader runs once per locale.
    by_locale: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for name, entry in accepted:
        vernacular = (entry.vernacular_name or "").strip()
        if vernacular:
            locale = normalize_locale(entry.locale) if entry.locale else ""
            by_locale[locale or fallback_locale].append((name, vernacular))

    # Must run AFTER the insert above: the loader resolves rows by scientific
    # name, and the core INSERT made them visible within this transaction.
    upserts = 0
    unchanged = 0
    for locale, rows in by_locale.items():
        outcome = await load_vernacular_rows(
            db, rows, source=IMPORT_VERNACULAR_SOURCE, locale=locale
        )
        upserts += outcome.inserted + outcome.updated
        unchanged += outcome.unchanged

    result = BulkImportResult(
        created=created,
        existing=existing,
        vernacular_upserts=upserts,
        vernacular_unchanged=unchanged,
        rejected=tuple(rejected),
    )
    logger.info(
        "Taxon bulk import by actor=%s: %d created, %d existing, %d rejected; "
        "vernacular %d written / %d unchanged across %d locale(s)",
        actor_user_id,
        result.created,
        result.existing,
        len(result.rejected),
        result.vernacular_upserts,
        result.vernacular_unchanged,
        len(by_locale),
    )
    return result


async def _known_names(db: AsyncSession, names: list[str]) -> set[str]:
    """Snapshot which of ``names`` already exist (monkeypatch seam for tests).

    Only drives the created/existing pre-split; the ON CONFLICT write is what
    actually guarantees correctness under concurrency.
    """
    result = await db.execute(
        select(Taxon.scientific_name).where(Taxon.scientific_name.in_(names))
    )
    return set(result.scalars().all())


def _normalize_rank(raw: str | None) -> str:
    """Upper-case a supplied rank, falling back to :data:`DEFAULT_RANK`.

    GBIF/COL ranks are upper-case tokens (``SPECIES``, ``GENUS``, ``ORDER``);
    normalizing here keeps a hand-typed ``species`` from creating a second
    spelling in the column.
    """
    rank = (raw or "").strip().upper()
    return rank or DEFAULT_RANK


__all__ = [
    "DEFAULT_RANK",
    "IMPORT_VERNACULAR_SOURCE",
    "REASON_DUPLICATE",
    "REASON_EMPTY",
    "REASON_NAME_TOO_LONG",
    "REASON_RANK_TOO_LONG",
    "BulkImportEntry",
    "BulkImportRejection",
    "BulkImportResult",
    "bulk_import_taxa",
    "normalize_scientific_name",
]
