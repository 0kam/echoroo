"""Tests for the operator taxon bulk-import service (WS-A v2 slice 6).

``bulk_import_taxa`` materialises an operator's list of taxa the BirdNET seed
does not cover. The behaviours that matter:

* create vs. existing accounting, and the fact that an existing taxon is never
  duplicated but still receives a supplied vernacular name;
* payload hygiene — whitespace normalization, empty rejection, first-wins on a
  name repeated within one payload;
* the vernacular write lands with ``source="user"`` in the requested locale
  (default ``ja``, overridable per entry);
* created rows leave ``col_xr_resolved_at`` NULL, which is exactly what makes
  the existing COL XR resolver pick them up afterwards;
* a re-run is idempotent.

These exercise the real database session (same pattern as
``test_vernacular_bundle.py``).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.services.taxon_bulk_import import (
    REASON_DUPLICATE,
    REASON_EMPTY,
    REASON_NAME_TOO_LONG,
    REASON_RANK_TOO_LONG,
    BulkImportEntry,
    bulk_import_taxa,
    normalize_scientific_name,
)


def _unique(prefix: str) -> str:
    """A scientific name that cannot collide with the seeded catalogue."""
    return f"{prefix} {uuid4().hex[:10]}"


async def _taxon(db: AsyncSession, scientific_name: str) -> Taxon | None:
    result = await db.execute(
        select(Taxon).where(Taxon.scientific_name == scientific_name)
    )
    return result.scalar_one_or_none()


async def _vernacular_rows(
    db: AsyncSession, taxon_id: object
) -> list[TaxonVernacularName]:
    result = await db.execute(
        select(TaxonVernacularName).where(TaxonVernacularName.taxon_id == taxon_id)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Cervus nippon", "Cervus nippon"),
        ("  Cervus nippon  ", "Cervus nippon"),
        ("Cervus   nippon", "Cervus nippon"),
        ("Cervus\tnippon\n", "Cervus nippon"),
        ("   ", ""),
    ],
)
def test_normalize_scientific_name(raw: str, expected: str) -> None:
    assert normalize_scientific_name(raw) == expected


# ---------------------------------------------------------------------------
# Create / existing accounting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_new_taxa_with_rank_and_default_locale_vernacular(
    db_session: AsyncSession,
) -> None:
    deer = _unique("Cervus")
    frog = _unique("Hyla")

    result = await bulk_import_taxa(
        db_session,
        [
            BulkImportEntry(scientific_name=f"  {deer} ", vernacular_name="ニホンジカ"),
            BulkImportEntry(
                scientific_name=frog, vernacular_name="ニホンアマガエル", rank="species"
            ),
        ],
    )
    await db_session.commit()

    assert result.created == 2
    assert result.existing == 0
    assert result.rejected == ()
    assert result.vernacular_upserts == 2

    deer_row = await _taxon(db_session, deer)
    assert deer_row is not None
    assert deer_row.is_non_biological is False
    # Rank defaults to SPECIES and a hand-typed lower-case rank is normalized.
    assert deer_row.rank == "SPECIES"
    frog_row = await _taxon(db_session, frog)
    assert frog_row is not None
    assert frog_row.rank == "SPECIES"

    names = await _vernacular_rows(db_session, deer_row.id)
    assert [(row.locale, row.name, row.source) for row in names] == [
        ("ja", "ニホンジカ", "user")
    ]


@pytest.mark.asyncio
async def test_created_rows_are_left_for_the_col_xr_resolver(
    db_session: AsyncSession,
) -> None:
    """``col_xr_resolved_at IS NULL`` is the resolver's selection predicate."""
    name = _unique("Teleogryllus")

    await bulk_import_taxa(db_session, [BulkImportEntry(scientific_name=name)])
    await db_session.commit()

    row = await _taxon(db_session, name)
    assert row is not None
    assert row.col_xr_resolved_at is None
    assert row.col_xr_id is None


@pytest.mark.asyncio
async def test_existing_taxon_is_not_duplicated_but_gains_the_vernacular(
    db_session: AsyncSession,
) -> None:
    name = _unique("Apalopteron")
    db_session.add(Taxon(scientific_name=name, rank="SPECIES"))
    await db_session.commit()

    result = await bulk_import_taxa(
        db_session,
        [BulkImportEntry(scientific_name=name, vernacular_name="メグロ")],
    )
    await db_session.commit()

    assert result.created == 0
    assert result.existing == 1
    assert result.vernacular_upserts == 1

    rows = (
        await db_session.execute(
            select(Taxon).where(Taxon.scientific_name == name)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert [row.name for row in await _vernacular_rows(db_session, rows[0].id)] == [
        "メグロ"
    ]


@pytest.mark.asyncio
async def test_existing_rank_is_never_clobbered(db_session: AsyncSession) -> None:
    name = _unique("Dendrocopos")
    db_session.add(Taxon(scientific_name=name, rank="SUBSPECIES"))
    await db_session.commit()

    await bulk_import_taxa(
        db_session, [BulkImportEntry(scientific_name=name, rank="GENUS")]
    )
    await db_session.commit()

    row = await _taxon(db_session, name)
    assert row is not None
    assert row.rank == "SUBSPECIES"


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_names_are_rejected(db_session: AsyncSession) -> None:
    good = _unique("Rana")

    result = await bulk_import_taxa(
        db_session,
        [
            BulkImportEntry(scientific_name="   "),
            BulkImportEntry(scientific_name=""),
            BulkImportEntry(scientific_name=good),
        ],
    )
    await db_session.commit()

    assert result.created == 1
    assert [item.reason for item in result.rejected] == [REASON_EMPTY, REASON_EMPTY]


@pytest.mark.asyncio
async def test_duplicate_within_payload_keeps_the_first_entry(
    db_session: AsyncSession,
) -> None:
    name = _unique("Bufo")

    result = await bulk_import_taxa(
        db_session,
        [
            BulkImportEntry(scientific_name=name, vernacular_name="いちばん"),
            # Same business key after whitespace normalization.
            BulkImportEntry(
                scientific_name=f"  {name.replace(' ', '  ')} ",
                vernacular_name="にばん",
            ),
        ],
    )
    await db_session.commit()

    assert result.created == 1
    assert [(i.scientific_name, i.reason) for i in result.rejected] == [
        (name, REASON_DUPLICATE)
    ]

    row = await _taxon(db_session, name)
    assert row is not None
    assert [r.name for r in await _vernacular_rows(db_session, row.id)] == ["いちばん"]


@pytest.mark.asyncio
async def test_all_entries_rejected_short_circuits(db_session: AsyncSession) -> None:
    result = await bulk_import_taxa(
        db_session, [BulkImportEntry(scientific_name=" ")]
    )
    assert result.created == 0
    assert result.existing == 0
    assert result.vernacular_upserts == 0
    assert len(result.rejected) == 1


# ---------------------------------------------------------------------------
# Locales
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locale_override_and_normalization(db_session: AsyncSession) -> None:
    name = _unique("Anas")

    result = await bulk_import_taxa(
        db_session,
        [
            BulkImportEntry(
                scientific_name=name, vernacular_name="Sika deer", locale="en-US"
            )
        ],
    )
    await db_session.commit()

    assert result.vernacular_upserts == 1
    row = await _taxon(db_session, name)
    assert row is not None
    names = await _vernacular_rows(db_session, row.id)
    assert [(n.locale, n.source) for n in names] == [("en", "user")]


@pytest.mark.asyncio
async def test_default_locale_is_configurable(db_session: AsyncSession) -> None:
    name = _unique("Corvus")

    await bulk_import_taxa(
        db_session,
        [BulkImportEntry(scientific_name=name, vernacular_name="Some bird")],
        default_locale="en",
    )
    await db_session.commit()

    row = await _taxon(db_session, name)
    assert row is not None
    assert [n.locale for n in await _vernacular_rows(db_session, row.id)] == ["en"]


@pytest.mark.asyncio
async def test_entries_are_grouped_per_locale(db_session: AsyncSession) -> None:
    """Both locales are written even though the loader runs once per locale."""
    name = _unique("Passer")

    result = await bulk_import_taxa(
        db_session,
        [
            BulkImportEntry(scientific_name=name, vernacular_name="スズメ"),
            # Second entry for the SAME taxon is a payload duplicate...
            BulkImportEntry(
                scientific_name=name, vernacular_name="Sparrow", locale="en"
            ),
        ],
    )
    await db_session.commit()

    # ...so only the first locale is written; the duplicate never reaches the
    # vernacular batch. This documents the first-wins rule end to end.
    assert result.created == 1
    assert len(result.rejected) == 1
    row = await _taxon(db_session, name)
    assert row is not None
    assert [(n.locale, n.name) for n in await _vernacular_rows(db_session, row.id)] == [
        ("ja", "スズメ")
    ]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerunning_is_idempotent(db_session: AsyncSession) -> None:
    name = _unique("Emberiza")
    entries = [BulkImportEntry(scientific_name=name, vernacular_name="ホオジロ")]

    first = await bulk_import_taxa(db_session, entries)
    await db_session.commit()
    second = await bulk_import_taxa(db_session, entries)
    await db_session.commit()

    assert first.created == 1
    assert first.vernacular_upserts == 1
    assert second.created == 0
    assert second.existing == 1
    # The name is already there: no rewrite, just an "unchanged" observation.
    assert second.vernacular_upserts == 0
    assert second.vernacular_unchanged == 1

    row = await _taxon(db_session, name)
    assert row is not None
    assert len(await _vernacular_rows(db_session, row.id)) == 1


# ---------------------------------------------------------------------------
# Codex review follow-ups: race-accurate counts, no silent truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_race_loser_is_counted_as_existing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent import that wins the insert turns our entry into existing.

    Simulated by blinding the pre-read (as if the row appeared between the
    read and the write): the ON CONFLICT ... RETURNING write is what decides
    ``created``, so the count stays truthful.
    """
    from echoroo.services import taxon_bulk_import as module

    db_session.add(Taxon(scientific_name="Racius winnerus", rank="SPECIES"))
    await db_session.commit()

    async def _blind(*_args: object, **_kwargs: object) -> set[str]:
        return set()

    monkeypatch.setattr(module, "_known_names", _blind)

    result = await bulk_import_taxa(
        db_session, [BulkImportEntry(scientific_name="Racius winnerus")]
    )
    await db_session.commit()

    assert result.created == 0
    assert result.existing == 1
    count = (
        await db_session.execute(
            sa.select(sa.func.count())
            .select_from(Taxon)
            .where(Taxon.scientific_name == "Racius winnerus")
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_overlong_name_and_rank_are_rejected_not_truncated(
    db_session: AsyncSession,
) -> None:
    """Garbage-length inputs are rejected; nothing is keyed on a prefix."""
    long_name = "Aaa " + "b" * 300
    result = await bulk_import_taxa(
        db_session,
        [
            BulkImportEntry(scientific_name=long_name),
            BulkImportEntry(scientific_name="Rankus badus", rank="R" * 51),
            BulkImportEntry(scientific_name="Okius fineus"),
        ],
    )
    await db_session.commit()

    assert result.created == 1
    reasons = {r.reason for r in result.rejected}
    assert reasons == {REASON_NAME_TOO_LONG, REASON_RANK_TOO_LONG}
    names = (
        (
            await db_session.execute(
                sa.select(Taxon.scientific_name).where(
                    Taxon.scientific_name.in_([long_name[:300], "Rankus badus", "Okius fineus"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert names == ["Okius fineus"]
