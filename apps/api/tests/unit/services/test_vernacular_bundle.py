"""Tests for the bundled vernacular-name loader (WS-A v2 slice 2a).

``load_vernacular_rows`` upserts a ``(locale, source)`` row per matching
taxon. The interesting behaviours are:

* the crosswalk hop (BirdNET's eBird scientific name → the AviList concept the
  IOC list keys on) and its fallback to the taxon's own name;
* idempotency — a second identical run must not rewrite anything;
* the ``source="authority"`` path an operator-supplied national checklist will
  reuse once its license question is settled.

These exercise the real database session (same pattern as
``test_vernacular_locale_fallback.py``).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.services.vernacular import resolve_vernacular_names
from echoroo.services.vernacular_bundle import (
    VernacularLoadResult,
    load_bundled_ja_names,
    load_vernacular_rows,
    read_bundled_birdnet_crosswalk,
    read_bundled_ja_names,
)


async def _seed_taxa(db: AsyncSession, scientific_names: list[str]) -> list[Taxon]:
    taxa = [Taxon(scientific_name=name, rank="SPECIES") for name in scientific_names]
    db.add_all(taxa)
    await db.commit()
    for taxon in taxa:
        await db.refresh(taxon)
    return taxa


async def _rows_for(db: AsyncSession, taxon_id: object, locale: str) -> list[TaxonVernacularName]:
    result = await db.execute(
        select(TaxonVernacularName)
        .where(TaxonVernacularName.taxon_id == taxon_id)
        .where(TaxonVernacularName.locale == locale)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# load_vernacular_rows — matching + counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_inserts_matching_rows_and_counts_leftovers(
    db_session: AsyncSession,
) -> None:
    """Exact match, crosswalk hop, and a taxon with no name at all."""
    suffix = uuid4().hex[:12]
    exact = f"Bundle exact {suffix}"
    stale = f"Bundle stale-genus {suffix}"
    current = f"Bundle current-genus {suffix}"
    orphan = f"Bundle orphan {suffix}"
    taxa = await _seed_taxa(db_session, [exact, stale, orphan])

    result = await load_vernacular_rows(
        db_session,
        [(exact, "エグザクト"), (current, "クロスウォーク"), ("Unused species", "未使用")],
        source="ioc",
        locale="ja",
        crosswalk={stale: current},
    )

    assert result == VernacularLoadResult(
        matched_taxa=2,
        inserted=2,
        updated=0,
        unchanged=0,
        # "Unused species" matched no taxon; the orphan taxon consumed nothing.
        unmatched_names=1,
    )

    exact_taxon, stale_taxon, orphan_taxon = taxa
    assert [row.name for row in await _rows_for(db_session, exact_taxon.id, "ja")] == ["エグザクト"]
    assert [row.name for row in await _rows_for(db_session, stale_taxon.id, "ja")] == [
        "クロスウォーク"
    ]
    assert await _rows_for(db_session, orphan_taxon.id, "ja") == []


@pytest.mark.asyncio
async def test_rows_are_written_with_the_requested_source(
    db_session: AsyncSession,
) -> None:
    """``source`` must survive intact — an unknown value would corrupt ranking."""
    suffix = uuid4().hex[:12]
    name = f"Bundle source {suffix}"
    (taxon,) = await _seed_taxa(db_session, [name])

    await load_vernacular_rows(db_session, [(name, "アイオーシー")], source="ioc", locale="ja")

    rows = await _rows_for(db_session, taxon.id, "ja")
    assert [(row.source, row.is_primary) for row in rows] == [("ioc", False)]


@pytest.mark.asyncio
async def test_crosswalk_falls_back_to_the_taxon_scientific_name(
    db_session: AsyncSession,
) -> None:
    """A hop whose target is missing must not lose a directly-available name."""
    suffix = uuid4().hex[:12]
    name = f"Bundle fallback {suffix}"
    (taxon,) = await _seed_taxa(db_session, [name])

    result = await load_vernacular_rows(
        db_session,
        [(name, "フォールバック")],
        source="ioc",
        locale="ja",
        crosswalk={name: f"Bundle missing target {suffix}"},
    )

    assert result.matched_taxa == 1
    assert [row.name for row in await _rows_for(db_session, taxon.id, "ja")] == ["フォールバック"]


@pytest.mark.asyncio
async def test_rerunning_is_idempotent(db_session: AsyncSession) -> None:
    suffix = uuid4().hex[:12]
    name = f"Bundle idempotent {suffix}"
    (taxon,) = await _seed_taxa(db_session, [name])
    rows = [(name, "イデンポテント")]

    first = await load_vernacular_rows(db_session, rows, source="ioc", locale="ja")
    await db_session.commit()
    second = await load_vernacular_rows(db_session, rows, source="ioc", locale="ja")
    await db_session.commit()

    assert (first.inserted, first.unchanged) == (1, 0)
    assert (second.inserted, second.updated, second.unchanged) == (0, 0, 1)
    assert len(await _rows_for(db_session, taxon.id, "ja")) == 1


@pytest.mark.asyncio
async def test_changed_name_updates_in_place(db_session: AsyncSession) -> None:
    """A regenerated bundle rewrites the row rather than adding a second one."""
    suffix = uuid4().hex[:12]
    name = f"Bundle renamed {suffix}"
    (taxon,) = await _seed_taxa(db_session, [name])

    await load_vernacular_rows(db_session, [(name, "キュウメイ")], source="ioc", locale="ja")
    await db_session.commit()
    result = await load_vernacular_rows(db_session, [(name, "シンメイ")], source="ioc", locale="ja")
    await db_session.commit()

    assert (result.inserted, result.updated, result.unchanged) == (0, 1, 0)
    assert [row.name for row in await _rows_for(db_session, taxon.id, "ja")] == ["シンメイ"]


@pytest.mark.asyncio
async def test_authority_source_coexists_with_ioc_and_outranks_it(
    db_session: AsyncSession,
) -> None:
    """The operator-checklist path shares the loader and wins at display time."""
    suffix = uuid4().hex[:12]
    name = f"Bundle authority {suffix}"
    (taxon,) = await _seed_taxa(db_session, [name])

    await load_vernacular_rows(db_session, [(name, "アイオーシーメイ")], source="ioc", locale="ja")
    result = await load_vernacular_rows(
        db_session, [(name, "モクロクメイ")], source="authority", locale="ja"
    )
    await db_session.commit()

    assert result.inserted == 1
    rows = await _rows_for(db_session, taxon.id, "ja")
    assert {row.source: row.name for row in rows} == {
        "ioc": "アイオーシーメイ",
        "authority": "モクロクメイ",
    }

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "モクロクメイ"


@pytest.mark.asyncio
async def test_empty_name_map_is_a_no_op(db_session: AsyncSession) -> None:
    suffix = uuid4().hex[:12]
    (taxon,) = await _seed_taxa(db_session, [f"Bundle empty {suffix}"])

    result = await load_vernacular_rows(
        db_session, [("", "空"), ("Something", "  ")], source="ioc", locale="ja"
    )

    assert result == VernacularLoadResult()
    assert await _rows_for(db_session, taxon.id, "ja") == []


@pytest.mark.asyncio
async def test_overlong_names_are_clipped_to_the_column_width(
    db_session: AsyncSession,
) -> None:
    suffix = uuid4().hex[:12]
    name = f"Bundle overlong {suffix}"
    (taxon,) = await _seed_taxa(db_session, [name])

    await load_vernacular_rows(db_session, [(name, "あ" * 400)], source="ioc", locale="ja")
    await db_session.commit()

    rows = await _rows_for(db_session, taxon.id, "ja")
    assert len(rows[0].name) == 300


# ---------------------------------------------------------------------------
# The real packaged bundle
# ---------------------------------------------------------------------------


def test_packaged_bundle_is_readable_and_non_trivial() -> None:
    names = dict(read_bundled_ja_names())
    crosswalk = read_bundled_birdnet_crosswalk()

    # Guard against an empty / truncated bundle sneaking into a release.
    assert len(names) > 10_000
    assert len(crosswalk) > 6_000
    assert names["Passer montanus"] == "スズメ"
    assert crosswalk["Accipiter gularis"] == "Tachyspiza gularis"


@pytest.mark.asyncio
async def test_load_bundled_ja_names_resolves_known_taxa(
    db_session: AsyncSession,
) -> None:
    """End-to-end against the shipped CSVs, including a crosswalk hop.

    ``Accipiter gularis`` is the canonical regression: BirdNET labels it under
    the old eBird genus while the IOC list files ツミ under ``Tachyspiza
    gularis``, so a naive scientific-name join silently drops the 和名.
    """
    sparrow, sparrowhawk = await _seed_taxa(db_session, ["Passer montanus", "Accipiter gularis"])

    result = await load_bundled_ja_names(db_session)
    await db_session.commit()

    assert result.matched_taxa >= 2
    mapping = await resolve_vernacular_names(db_session, [sparrow.id, sparrowhawk.id], "ja")
    assert mapping[sparrow.id] == "スズメ"
    assert mapping[sparrowhawk.id] == "ツミ"

    assert [row.source for row in await _rows_for(db_session, sparrow.id, "ja")] == ["ioc"]


# ---------------------------------------------------------------------------
# Codex review follow-ups: race safety, primacy semantics, bundle integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_absorbs_a_row_inserted_behind_its_back(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate two loaders racing: our snapshot says "no row", but one exists.

    Before the ON CONFLICT rewrite this raised ``IntegrityError`` on the
    unique ``(taxon_id, locale, source)`` constraint. Now the stale insert
    becomes an update and the final name is the one we intended to write.
    """
    from echoroo.services import vernacular_bundle

    (taxon,) = await _seed_taxa(db_session, ["Race Sparrow"])
    db_session.add(
        TaxonVernacularName(
            taxon_id=taxon.id,
            locale="ja",
            name="古い名前",
            source="ioc",
            is_primary=False,
        )
    )
    await db_session.commit()

    async def _stale_snapshot(*_args: object, **_kwargs: object) -> dict[object, str]:
        return {}

    monkeypatch.setattr(vernacular_bundle, "_existing_names", _stale_snapshot)

    result = await load_vernacular_rows(
        db_session, [("Race Sparrow", "新しい名前")], source="ioc", locale="ja"
    )
    await db_session.commit()

    # Counters reflect the (stale) snapshot; the database reflects reality.
    assert result.inserted == 1
    rows = await _rows_for(db_session, taxon.id, "ja")
    assert [(row.source, row.name) for row in rows] == [("ioc", "新しい名前")]


@pytest.mark.asyncio
async def test_scraped_non_primary_rows_lose_to_bundled_ioc(
    db_session: AsyncSession,
) -> None:
    """The API-scraped ja rows are never primary, so the ioc row wins display.

    This pins the assumption the whole migration rests on: every scraped
    writer (``workers/taxon_tasks.py``, ``repositories/taxon.py
    persist_vernacular_names``) stores ``is_primary=False`` for non-en rows,
    and the resolver's source rank then prefers ``ioc`` over ``gbif`` /
    ``inaturalist``.
    """
    (taxon,) = await _seed_taxa(db_session, ["Passer montanus"])
    db_session.add_all(
        [
            TaxonVernacularName(
                taxon_id=taxon.id, locale="ja", name="雀", source="gbif", is_primary=False
            ),
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="ja",
                name="スズメ（iNat）",
                source="inaturalist",
                is_primary=False,
            ),
        ]
    )
    await db_session.commit()

    await load_vernacular_rows(
        db_session, [("Passer montanus", "スズメ")], source="ioc", locale="ja"
    )
    await db_session.commit()

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "スズメ"


@pytest.mark.asyncio
async def test_curated_primary_row_still_outranks_ioc(db_session: AsyncSession) -> None:
    """An operator-marked primary row is an explicit decision and is kept.

    The loader never touches ``is_primary`` (neither on insert nor in the
    ON CONFLICT update set), so curation survives bundle reloads.
    """
    (taxon,) = await _seed_taxa(db_session, ["Curated Sparrow"])
    db_session.add(
        TaxonVernacularName(
            taxon_id=taxon.id,
            locale="ja",
            name="キュレーション名",
            source="user",
            is_primary=True,
        )
    )
    await db_session.commit()

    await load_vernacular_rows(
        db_session, [("Curated Sparrow", "バンドル名")], source="ioc", locale="ja"
    )
    await db_session.commit()

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "キュレーション名"
    rows = {row.source: row.is_primary for row in await _rows_for(db_session, taxon.id, "ja")}
    assert rows == {"user": True, "ioc": False}


def test_bundle_integrity_rejects_a_truncated_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CSV whose row count disagrees with its sidecar metadata is refused."""
    from echoroo.services import vernacular_bundle

    real_read = vernacular_bundle._read_text

    def _truncated(name: str) -> str:
        text = real_read(name)
        if name == "ioc_ja.csv":
            return "\n".join(text.splitlines()[:50])
        return text

    monkeypatch.setattr(vernacular_bundle, "_read_text", _truncated)

    with pytest.raises(ValueError, match="declares"):
        read_bundled_ja_names()
    # The crosswalk is untouched and still validates.
    assert len(read_bundled_birdnet_crosswalk()) > 6_000
