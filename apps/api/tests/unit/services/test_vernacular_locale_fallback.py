"""Unit tests for the ja→en fallback chain in ``resolve_vernacular_names``.

WS-A / PR1 (A3): when the UI requests ``ja`` the helper resolves the
Japanese vernacular name when available, otherwise falls back to the English
vernacular name. Taxa with neither a requested-locale nor an English row are
omitted (the final scientific-name floor is a display concern handled by the
frontend formatter, not by this helper).

These tests exercise the real database session (the matching
``tests/contract/test_tag_detection_locale.py`` suite is skipped pending the
Phase 14+ ``recording_annotations`` rework, so the helper needs runnable
coverage here).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.services.vernacular import resolve_vernacular_names


async def _seed_taxon(
    db: AsyncSession,
    scientific_name: str,
    vernaculars: Sequence[tuple[str, str, bool] | tuple[str, str, bool, str]],
) -> Taxon:
    """Create a taxon with ``(locale, name, is_primary[, source])`` rows.

    ``source`` defaults to ``"gbif"`` when the 3-tuple form is used.
    """
    taxon = Taxon(scientific_name=scientific_name, rank="SPECIES")
    db.add(taxon)
    await db.commit()
    await db.refresh(taxon)

    for row in vernaculars:
        locale, name, is_primary = row[0], row[1], row[2]
        source = row[3] if len(row) == 4 else "gbif"
        db.add(
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale=locale,
                name=name,
                source=source,
                is_primary=is_primary,
            )
        )
    if vernaculars:
        await db.commit()
    return taxon


@pytest.mark.asyncio
async def test_ja_present_returns_ja(db_session: AsyncSession) -> None:
    """Requested ja present → ja name wins over the en fallback."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Fallback ja-present {suffix}",
        [("en", "English Name", True), ("ja", "ニホンゴ", True)],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "ニホンゴ"


@pytest.mark.asyncio
async def test_ja_missing_en_present_falls_back_to_en(
    db_session: AsyncSession,
) -> None:
    """Requested ja missing + en present → en name."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Fallback en-only {suffix}",
        [("en", "English Name", True)],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "English Name"


@pytest.mark.asyncio
async def test_neither_ja_nor_en_is_omitted(db_session: AsyncSession) -> None:
    """Neither ja nor en → taxon omitted from the mapping (no scientific floor)."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Fallback neither {suffix}",
        [("fr", "Nom Francais", True)],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert taxon.id not in mapping


@pytest.mark.asyncio
async def test_ja_non_primary_used_over_en(db_session: AsyncSession) -> None:
    """A non-primary ja row still beats the en fallback (tier ordering)."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Fallback ja-nonprimary {suffix}",
        [
            ("en", "English Primary", True),
            ("ja", "ニホンゴ非プライマリ", False),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "ニホンゴ非プライマリ"


@pytest.mark.asyncio
async def test_en_request_returns_en_only(db_session: AsyncSession) -> None:
    """A plain ``en`` request resolves the English name (chain collapses)."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Fallback en-request {suffix}",
        [("en", "English Name", True), ("ja", "ニホンゴ", True)],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "en")
    assert mapping[taxon.id] == "English Name"


@pytest.mark.asyncio
async def test_en_fallback_emits_debug_log(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """Falling back to English for a non-en locale emits a DEBUG diagnostic.

    No behaviour change — the mapping is still the English name; this only
    asserts the new ``logger.debug`` so operators can spot poor ja coverage.
    """
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Fallback log {suffix}",
        [("en", "English Name", True)],
    )

    with caplog.at_level(logging.DEBUG, logger="echoroo.services.vernacular"):
        mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")

    assert mapping[taxon.id] == "English Name"
    assert any(
        "fell back to English" in record.getMessage()
        and str(taxon.id) in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_no_fallback_log_when_locale_present(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """When the requested locale is present, no fallback log is emitted."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"No fallback log {suffix}",
        [("en", "English Name", True), ("ja", "ニホンゴ", True)],
    )

    with caplog.at_level(logging.DEBUG, logger="echoroo.services.vernacular"):
        mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")

    assert mapping[taxon.id] == "ニホンゴ"
    assert not any(
        "fell back to English" in record.getMessage()
        and str(taxon.id) in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_inaturalist_beats_gbif_within_ja_tier(
    db_session: AsyncSession,
) -> None:
    """Both ja rows non-primary → the iNaturalist name wins over GBIF.

    This is the trial-feedback fix: GBIF ja names skew kanji, iNaturalist
    skew katakana, and without a source tiebreak the winner was arbitrary.
    """
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source inat-vs-gbif {suffix}",
        [
            ("ja", "鶯", False, "gbif"),
            ("ja", "ウグイス", False, "inaturalist"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "ウグイス"


@pytest.mark.asyncio
async def test_user_beats_inaturalist_and_authority_beats_user(
    db_session: AsyncSession,
) -> None:
    """Full source ranking: authority > user > inaturalist."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source authority-chain {suffix}",
        [
            ("ja", "イナットメイ", False, "inaturalist"),
            ("ja", "ユーザーメイ", False, "user"),
            ("ja", "モクロクメイ", False, "authority"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "モクロクメイ"


@pytest.mark.asyncio
async def test_ioc_beats_inaturalist_and_gbif_within_ja_tier(
    db_session: AsyncSession,
) -> None:
    """WS-A v2 slice 2a: the bundled IOC name outranks both scraped sources.

    The bundled list is versioned and taxonomically self-consistent, so it
    must win over the API-sourced names it is meant to replace.
    """
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source ioc-vs-scraped {suffix}",
        [
            ("ja", "ジービーアイエフメイ", False, "gbif"),
            ("ja", "イナットメイ", False, "inaturalist"),
            ("ja", "アイオーシーメイ", False, "ioc"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "アイオーシーメイ"


@pytest.mark.asyncio
async def test_ioc_beats_gbif_when_it_is_the_only_alternative(
    db_session: AsyncSession,
) -> None:
    """Minimal ioc > gbif pair (the common shape on a real install)."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source ioc-vs-gbif {suffix}",
        [
            ("ja", "ジービーアイエフメイ", False, "gbif"),
            ("ja", "アイオーシーメイ", False, "ioc"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "アイオーシーメイ"


@pytest.mark.asyncio
async def test_authority_and_user_still_outrank_ioc(
    db_session: AsyncSession,
) -> None:
    """Full chain: authority > user > ioc > inaturalist.

    An operator-loaded national checklist and an in-app manual override both
    stay above the bundle, so slice 2a does not demote curated names.
    """
    suffix = uuid4().hex[:12]
    inat_and_ioc = await _seed_taxon(
        db_session,
        f"Source ioc-over-inat {suffix}",
        [
            ("ja", "イナットメイ", False, "inaturalist"),
            ("ja", "アイオーシーメイ", False, "ioc"),
        ],
    )
    user_over_ioc = await _seed_taxon(
        db_session,
        f"Source user-over-ioc {suffix}",
        [
            ("ja", "アイオーシーメイ", False, "ioc"),
            ("ja", "ユーザーメイ", False, "user"),
        ],
    )
    authority_over_user = await _seed_taxon(
        db_session,
        f"Source authority-over-user {suffix}",
        [
            ("ja", "アイオーシーメイ", False, "ioc"),
            ("ja", "ユーザーメイ", False, "user"),
            ("ja", "モクロクメイ", False, "authority"),
        ],
    )

    mapping = await resolve_vernacular_names(
        db_session,
        [inat_and_ioc.id, user_over_ioc.id, authority_over_user.id],
        "ja",
    )
    assert mapping[inat_and_ioc.id] == "アイオーシーメイ"
    assert mapping[user_over_ioc.id] == "ユーザーメイ"
    assert mapping[authority_over_user.id] == "モクロクメイ"


@pytest.mark.asyncio
async def test_primary_flag_outranks_source(db_session: AsyncSession) -> None:
    """A primary row wins even against a higher-ranked non-primary source.

    ``is_primary`` is an explicit curation decision, so it stays above the
    source tiebreak.
    """
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source primary-wins {suffix}",
        [
            ("ja", "キュレーションメイ", True, "gbif"),
            ("ja", "イナットメイ", False, "inaturalist"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "キュレーションメイ"


@pytest.mark.asyncio
async def test_unknown_source_ranks_last(db_session: AsyncSession) -> None:
    """A row with an unrecognized source loses to any known source."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source unknown-last {suffix}",
        [
            ("ja", "ミチノミナモト", False, "mystery-import"),
            ("ja", "バードネットメイ", False, "birdnet"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "バードネットメイ"


@pytest.mark.asyncio
async def test_source_tiebreak_applies_to_en_fallback_tier(
    db_session: AsyncSession,
) -> None:
    """The tiebreak also stabilizes the en fallback tier when ja is absent."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source en-tier {suffix}",
        [
            ("en", "Gbif English", False, "gbif"),
            ("en", "User English", False, "user"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "User English"


@pytest.mark.asyncio
async def test_two_unknown_sources_resolve_deterministically(
    db_session: AsyncSession,
) -> None:
    """Two unrecognized sources tie on rank → lexicographic source order wins.

    Guards against the winner depending on DB return order.
    """
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source unknown-pair {suffix}",
        [
            ("ja", "ミナモトビー", False, "mystery-b"),
            ("ja", "ミナモトエー", False, "mystery-a"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "ja")
    assert mapping[taxon.id] == "ミナモトエー"


@pytest.mark.asyncio
async def test_source_tiebreak_applies_to_en_request(
    db_session: AsyncSession,
) -> None:
    """A plain ``en`` request also uses the source tiebreak."""
    suffix = uuid4().hex[:12]
    taxon = await _seed_taxon(
        db_session,
        f"Source en-request {suffix}",
        [
            ("en", "Birdnet English", False, "birdnet"),
            ("en", "Gbif English", False, "gbif"),
        ],
    )

    mapping = await resolve_vernacular_names(db_session, [taxon.id], "en")
    assert mapping[taxon.id] == "Gbif English"
