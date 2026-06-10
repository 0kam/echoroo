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
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.services.vernacular import resolve_vernacular_names


async def _seed_taxon(
    db: AsyncSession,
    scientific_name: str,
    vernaculars: list[tuple[str, str, bool]],
) -> Taxon:
    """Create a taxon with the given ``(locale, name, is_primary)`` rows."""
    taxon = Taxon(scientific_name=scientific_name, rank="SPECIES")
    db.add(taxon)
    await db.commit()
    await db.refresh(taxon)

    for locale, name, is_primary in vernaculars:
        db.add(
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale=locale,
                name=name,
                source="gbif",
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
