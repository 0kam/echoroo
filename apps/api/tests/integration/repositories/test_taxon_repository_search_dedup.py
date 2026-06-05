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
