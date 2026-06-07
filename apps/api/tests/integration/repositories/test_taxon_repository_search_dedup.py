"""Integration tests for ``TaxonRepository.search`` deduplication (WS-A / A3).

Regression coverage for the locale-agnostic search rewrite in
``echoroo.repositories.taxon``. The earlier implementation matched vernacular
names via a non-deduplicated subquery JOIN, so a taxon with several vernacular
rows matching the same query (e.g. both a ``ja`` and an ``en`` row) produced
duplicate ``Taxon`` rows. Those duplicates consumed the ``LIMIT``, returning
fewer distinct taxa than intended and leaking duplicates to the caller.

These tests use a live PostgreSQL session (the shared ``echoroo_test`` DB via
``TEST_DATABASE_URL``) so the SQL-level dedup behaviour is exercised, not a
mocked stand-in.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.repositories.taxon import TaxonRepository

pytestmark = pytest.mark.asyncio


async def _add_taxon(
    db: AsyncSession,
    scientific_name: str,
    vernaculars: list[tuple[str, str, str]],
) -> Taxon:
    """Create a taxon with the given vernacular rows.

    ``vernaculars`` is a list of ``(locale, name, source)`` tuples. The unique
    constraint on ``(taxon_id, locale, source)`` permits several rows per taxon
    as long as that triple differs.
    """
    taxon = Taxon(scientific_name=scientific_name, is_non_biological=False)
    db.add(taxon)
    await db.flush()
    for locale, name, source in vernaculars:
        db.add(
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale=locale,
                name=name,
                source=source,
                is_primary=(locale == "en"),
            )
        )
    await db.flush()
    return taxon


async def test_search_returns_taxon_once_when_multiple_vernaculars_match(
    db_session: AsyncSession,
) -> None:
    """A taxon with multiple matching vernacular rows is returned exactly once.

    Both a ``ja`` and an ``en`` vernacular row ILIKE the query; the taxon must
    appear a single time in the result (no JOIN row-multiplication).
    """
    suffix = uuid.uuid4().hex[:8]
    sci = f"Robinus testus {suffix}"
    # The shared token "robin" appears in two distinct vernacular rows.
    await _add_taxon(
        db_session,
        sci,
        [
            ("en", f"American Robin {suffix}", "gbif"),
            ("ja", f"ロビン robin {suffix}", "gbif"),
            ("en", f"Robin (birdnet) {suffix}", "birdnet"),
        ],
    )
    await db_session.flush()

    repo = TaxonRepository(db_session)
    results = await repo.search("robin", limit=20)

    matching = [t for t in results if t.scientific_name == sci]
    assert len(matching) == 1, (
        "taxon with multiple matching vernacular rows must appear exactly once, "
        f"got {len(matching)} rows"
    )
    # The result list itself must contain no duplicate taxon ids overall.
    ids = [t.id for t in results]
    assert len(ids) == len(set(ids)), "search() returned duplicate Taxon rows"


async def test_search_limit_counts_distinct_taxa(
    db_session: AsyncSession,
) -> None:
    """``limit=N`` yields N distinct taxa, not N rows inflated by duplicates.

    Three distinct taxa each carry multiple matching vernacular rows. With a
    JOIN-based match the duplicates would consume the LIMIT and return fewer
    than 3 distinct taxa; the EXISTS-based dedup must return all 3 distinct.
    """
    suffix = uuid.uuid4().hex[:8]
    token = f"finchy{suffix}"
    sci_names = [
        f"Fringilla alpha {suffix}",
        f"Fringilla beta {suffix}",
        f"Fringilla gamma {suffix}",
    ]
    for sci in sci_names:
        await _add_taxon(
            db_session,
            sci,
            [
                ("en", f"{token} english", "gbif"),
                ("ja", f"{token} 和名", "gbif"),
                ("en", f"{token} birdnet", "birdnet"),
            ],
        )
    await db_session.flush()

    repo = TaxonRepository(db_session)
    results = await repo.search(token, limit=3)

    assert len(results) == 3, (
        f"limit=3 must return 3 distinct taxa, got {len(results)} rows"
    )
    ids = {t.id for t in results}
    assert len(ids) == 3, "limit budget was consumed by duplicate rows"
    assert {t.scientific_name for t in results} == set(sci_names)


async def test_search_matches_scientific_name_only(
    db_session: AsyncSession,
) -> None:
    """Scientific-name matches still surface taxa with no matching vernacular."""
    suffix = uuid.uuid4().hex[:8]
    sci = f"Zysciname {suffix}"
    await _add_taxon(
        db_session,
        sci,
        [("en", f"Unrelated common name {suffix}", "gbif")],
    )
    await db_session.flush()

    repo = TaxonRepository(db_session)
    results = await repo.search("Zysciname", limit=20)

    matching = [t for t in results if t.scientific_name == sci]
    assert len(matching) == 1


async def test_get_or_create_race_loss_returns_existing_row(
    db_session: AsyncSession,
) -> None:
    """A concurrent first-create race returns the winning row, not a 500.

    Simulates the read-then-insert race: ``get_by_scientific_name`` misses
    (the other transaction has not been observed yet), so this call proceeds
    to insert and trips the ``unique(scientific_name)`` constraint on flush.
    The SAVEPOINT-scoped insert must roll back only the savepoint, then
    re-query and return the row the winning transaction created — preserving
    get-OR-create semantics and never duplicating the en vernacular.
    """
    suffix = uuid.uuid4().hex[:8]
    sci = f"Raceus testus {suffix}"

    # The "winning" transaction's row already exists (and already owns its en
    # vernacular). This stands in for the row another concurrent create wrote.
    winner = Taxon(scientific_name=sci, is_non_biological=False)
    db_session.add(winner)
    await db_session.flush()
    db_session.add(
        TaxonVernacularName(
            taxon_id=winner.id,
            locale="en",
            name=f"Winner Name {suffix}",
            source="birdnet",
            is_primary=True,
        )
    )
    await db_session.flush()

    repo = TaxonRepository(db_session)

    # Force the read-miss so the insert path runs and trips the unique index,
    # exactly as a racing transaction that committed after our SELECT would.
    original = repo.get_by_scientific_name
    calls = {"n": 0}

    async def _first_miss_then_real(scientific_name: str) -> Taxon | None:
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # pre-insert read misses (race window)
        return await original(scientific_name)  # post-conflict re-query hits

    repo.get_by_scientific_name = _first_miss_then_real  # type: ignore[method-assign]

    result = await repo.get_or_create_by_scientific_name(
        scientific_name=sci,
        common_name=f"Loser Name {suffix}",
    )

    # Returned the existing (winning) row rather than raising IntegrityError.
    assert result.id == winner.id
    # The race-lost path must NOT have seeded a duplicate en vernacular.
    from sqlalchemy import func

    vn_count = await db_session.execute(
        select(func.count())
        .select_from(TaxonVernacularName)
        .where(TaxonVernacularName.taxon_id == winner.id)
    )
    assert int(vn_count.scalar_one()) == 1


async def _ja_rows(
    db: AsyncSession, taxon_id: uuid.UUID, source: str
) -> list[TaxonVernacularName]:
    result = await db.execute(
        select(TaxonVernacularName)
        .where(TaxonVernacularName.taxon_id == taxon_id)
        .where(TaxonVernacularName.locale == "ja")
        .where(TaxonVernacularName.source == source)
    )
    return list(result.scalars().all())


async def test_persist_does_not_overwrite_existing_name(
    db_session: AsyncSession,
) -> None:
    """A second persist with a different name for the SAME (locale, source)
    must NOT overwrite the original non-empty name (F6 no-overwrite)."""
    suffix = uuid.uuid4().hex[:8]
    taxon = Taxon(scientific_name=f"Persistus testus {suffix}")
    db_session.add(taxon)
    await db_session.flush()

    repo = TaxonRepository(db_session)
    inserted = await repo.persist_vernacular_names(
        taxon.id, [{"name": "オリジナル名", "language": "ja", "source": "inaturalist"}]
    )
    assert inserted == 1

    # Second materialize with a DIFFERENT name for the same (ja, inaturalist).
    inserted2 = await repo.persist_vernacular_names(
        taxon.id, [{"name": "上書き名", "language": "jpn", "source": "inaturalist"}]
    )
    assert inserted2 == 0  # not a new row

    rows = await _ja_rows(db_session, taxon.id, "inaturalist")
    assert len(rows) == 1
    # Original preserved — payload did NOT overwrite it.
    assert rows[0].name == "オリジナル名"


async def test_persist_fills_empty_existing_name(
    db_session: AsyncSession,
) -> None:
    """An empty placeholder name IS filled from the payload (F6 fill-only)."""
    suffix = uuid.uuid4().hex[:8]
    taxon = Taxon(scientific_name=f"Fillus testus {suffix}")
    db_session.add(taxon)
    await db_session.flush()
    db_session.add(
        TaxonVernacularName(
            taxon_id=taxon.id, locale="ja", name="", source="gbif", is_primary=False
        )
    )
    await db_session.flush()

    repo = TaxonRepository(db_session)
    await repo.persist_vernacular_names(
        taxon.id, [{"name": "充填名", "language": "ja", "source": "gbif"}]
    )

    rows = await _ja_rows(db_session, taxon.id, "gbif")
    assert len(rows) == 1
    assert rows[0].name == "充填名"


async def test_persist_unknown_source_coerced_to_default(
    db_session: AsyncSession,
) -> None:
    """An unknown/empty source is coerced to the safe default (F6 allow-set)."""
    suffix = uuid.uuid4().hex[:8]
    taxon = Taxon(scientific_name=f"Sourceus testus {suffix}")
    db_session.add(taxon)
    await db_session.flush()

    repo = TaxonRepository(db_session)
    await repo.persist_vernacular_names(
        taxon.id,
        [{"name": "ソース名", "language": "ja", "source": "evil-injection"}],
    )

    rows = await db_session.execute(
        select(TaxonVernacularName)
        .where(TaxonVernacularName.taxon_id == taxon.id)
        .where(TaxonVernacularName.locale == "ja")
    )
    persisted = list(rows.scalars().all())
    assert len(persisted) == 1
    assert persisted[0].source == "gbif"  # unknown → default


async def test_persist_truncates_overlength_name(
    db_session: AsyncSession,
) -> None:
    """An over-length name is truncated to the column ceiling (F6 lengths)."""
    suffix = uuid.uuid4().hex[:8]
    taxon = Taxon(scientific_name=f"Longus testus {suffix}")
    db_session.add(taxon)
    await db_session.flush()

    long_name = "あ" * 500  # exceeds String(300)
    repo = TaxonRepository(db_session)
    inserted = await repo.persist_vernacular_names(
        taxon.id, [{"name": long_name, "language": "ja", "source": "gbif"}]
    )
    assert inserted == 1

    rows = await _ja_rows(db_session, taxon.id, "gbif")
    assert len(rows) == 1
    assert len(rows[0].name) == 300


async def test_has_vernacular_in_locale_no_fallback(
    db_session: AsyncSession,
) -> None:
    """has_vernacular_in_locale is exact (no en fallback) (F4 support)."""
    suffix = uuid.uuid4().hex[:8]
    taxon = Taxon(scientific_name=f"Exactus testus {suffix}")
    db_session.add(taxon)
    await db_session.flush()
    db_session.add(
        TaxonVernacularName(
            taxon_id=taxon.id, locale="en", name="English Only", source="gbif"
        )
    )
    await db_session.flush()

    repo = TaxonRepository(db_session)
    # An en row exists but NO ja row — exact check must report absence.
    assert await repo.has_vernacular_in_locale(taxon.id, "ja") is False
    assert await repo.has_vernacular_in_locale(taxon.id, "en") is True
    # ja-JP normalizes to ja → still absent.
    assert await repo.has_vernacular_in_locale(taxon.id, "ja-JP") is False
