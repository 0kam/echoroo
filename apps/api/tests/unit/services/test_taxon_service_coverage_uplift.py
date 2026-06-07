"""Coverage uplift unit tests for ``echoroo.services.taxon``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers TaxonService methods
(list_taxa, get_detail 404 path, search, get_or_create, resolve_gbif_batch)
so the module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.repositories.taxon import normalize_locale
from echoroo.services.taxon import TaxonService, _en_common_name_for_seed


def test_normalize_locale_primary_subtag_and_iso3() -> None:
    """normalize_locale reduces to a lowercase primary 2-letter subtag (F3/F6)."""
    assert normalize_locale("ja-JP") == "ja"
    assert normalize_locale("ja_JP") == "ja"
    assert normalize_locale("EN") == "en"
    assert normalize_locale("en-US") == "en"
    assert normalize_locale("jpn") == "ja"  # 3-letter ISO collapses too
    assert normalize_locale(" Ja ") == "ja"


def _make_taxon_repo() -> MagicMock:
    repo = MagicMock()
    repo.list_taxa = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.search = AsyncMock()
    repo.get_or_create_by_scientific_name = AsyncMock()
    repo.get_by_gbif_taxon_key = AsyncMock(return_value=None)
    repo.get_unresolved = AsyncMock()
    repo.update = AsyncMock()
    repo.persist_vernacular_names = AsyncMock(return_value=0)
    repo.has_vernacular_in_locale = AsyncMock(return_value=False)
    repo.db = MagicMock()
    return repo


def _make_gbif_service() -> MagicMock:
    svc = MagicMock()
    svc.resolve_taxon = AsyncMock()
    return svc


def _make_taxon(scientific_name: str = "Parus major") -> MagicMock:
    taxon = MagicMock()
    taxon.id = uuid4()
    taxon.scientific_name = scientific_name
    taxon.gbif_taxon_key = 12345
    taxon.rank = "SPECIES"
    taxon.is_non_biological = False
    taxon.gbif_metadata = {}
    taxon.gbif_resolved_at = None
    taxon.vernacular_names = []
    taxon.updated_at = None
    return taxon


@pytest.mark.asyncio
async def test_list_taxa_returns_paginated_response() -> None:
    """list_taxa returns TaxonListResponse (lines 49-58)."""
    repo = _make_taxon_repo()
    # Return empty list to avoid TaxonResponse.model_validate needing a real taxon
    repo.list_taxa = AsyncMock(return_value=([], 0))

    service = TaxonService(taxon_repo=repo)
    result = await service.list_taxa(search="Parus", page=1, page_size=10)

    assert result.total == 0
    assert result.items == []
    repo.list_taxa.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_detail_raises_404_when_taxon_not_found() -> None:
    """get_detail raises 404 when taxon not found (lines 67-69)."""
    repo = _make_taxon_repo()
    repo.get_by_id = AsyncMock(return_value=None)

    service = TaxonService(taxon_repo=repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_detail(uuid4())

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_get_detail_returns_taxon_detail() -> None:
    """get_detail returns TaxonDetailResponse when taxon exists (lines 74-83)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_by_id = AsyncMock(return_value=taxon)

    service = TaxonService(taxon_repo=repo)

    mock_taxon_resp = MagicMock()
    mock_taxon_resp.model_dump.return_value = {"scientific_name": "Parus major"}
    sentinel = MagicMock()

    with (
        patch("echoroo.services.taxon.TaxonDetailResponse", return_value=sentinel),
        patch("echoroo.services.taxon.TaxonResponse") as MockResp,
    ):
        MockResp.model_validate.return_value = mock_taxon_resp
        result = await service.get_detail(taxon.id)

    assert result is sentinel


@pytest.mark.asyncio
async def test_search_returns_list_of_results() -> None:
    """search returns list of TaxonSearchResult with resolved display names.

    Matching is decoupled from display: the repo returns bare ``Taxon`` rows
    and the service resolves the display ``common_name`` via
    ``resolve_vernacular_names`` (ja→en fallback).
    """
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.search = AsyncMock(return_value=[taxon])

    service = TaxonService(taxon_repo=repo)

    with patch(
        "echoroo.services.taxon.resolve_vernacular_names",
        new=AsyncMock(return_value={taxon.id: "Great Tit"}),
    ) as mock_resolve:
        results = await service.search(query="Parus", locale="en")

    assert len(results) == 1
    assert results[0].scientific_name == "Parus major"
    assert results[0].common_name == "Great Tit"
    # Locale-agnostic matching: repo.search is called WITHOUT a locale arg.
    repo.search.assert_awaited_once_with("Parus", limit=20)
    mock_resolve.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_omits_common_name_when_no_vernacular() -> None:
    """search leaves common_name None when no vernacular resolves (floor later)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.search = AsyncMock(return_value=[taxon])

    service = TaxonService(taxon_repo=repo)

    with patch(
        "echoroo.services.taxon.resolve_vernacular_names",
        new=AsyncMock(return_value={}),
    ):
        results = await service.search(query="Parus", locale="ja")

    assert len(results) == 1
    assert results[0].common_name is None


@pytest.mark.asyncio
async def test_get_or_create_returns_taxon_response() -> None:
    """get_or_create delegates to repo and returns TaxonResponse (lines 110-116)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_or_create_by_scientific_name = AsyncMock(return_value=taxon)

    service = TaxonService(taxon_repo=repo)

    with patch("echoroo.services.taxon.TaxonResponse") as MockResp:
        mock_resp = MagicMock()
        MockResp.model_validate.return_value = mock_resp
        result = await service.get_or_create(scientific_name="Parus major")

    assert result is mock_resp


def test_en_common_name_for_seed_prefers_en_vernacular_entry() -> None:
    """The en slot is derived from the ``en`` entry, not the ja display name."""
    result = _en_common_name_for_seed(
        common_name="スズメ",
        locale="ja",
        vernacular_names=[
            {"name": "スズメ", "language": "ja", "source": "inaturalist"},
            {"name": "Eurasian Tree Sparrow", "language": "en", "source": "gbif"},
        ],
    )
    assert result == "Eurasian Tree Sparrow"


def test_en_common_name_for_seed_no_en_entry_returns_none_for_ja() -> None:
    """A ja locale with no en entry must not fabricate an en row."""
    result = _en_common_name_for_seed(
        common_name="スズメ",
        locale="ja",
        vernacular_names=[
            {"name": "スズメ", "language": "ja", "source": "inaturalist"},
        ],
    )
    assert result is None


def test_en_common_name_for_seed_en_locale_uses_client_common_name() -> None:
    """Backward compat: an en locale keeps using the client common_name."""
    assert (
        _en_common_name_for_seed("Eurasian Tree Sparrow", "en", None)
        == "Eurasian Tree Sparrow"
    )
    # No vernacular_names + en locale → pass through.
    assert _en_common_name_for_seed("Great Tit", "EN", None) == "Great Tit"


def test_en_common_name_for_seed_normalizes_en_language_tag() -> None:
    """A normalized en entry (e.g. ``eng``/``en-US``) is recognized."""
    assert (
        _en_common_name_for_seed(
            "和名",
            "ja",
            [{"name": "Eng Name", "language": "eng", "source": "gbif"}],
        )
        == "Eng Name"
    )


@pytest.mark.asyncio
async def test_from_gbif_seeds_en_slot_from_en_vernacular_entry() -> None:
    """create_from_gbif passes the en entry (not the ja display) to the repo."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_or_create_by_scientific_name = AsyncMock(return_value=taxon)
    repo.has_vernacular_in_locale = AsyncMock(return_value=True)

    service = TaxonService(taxon_repo=repo)

    with patch(
        "echoroo.services.taxon.resolve_vernacular_names",
        new=AsyncMock(return_value={taxon.id: "スズメ"}),
    ):
        await service.create_from_gbif(
            scientific_name="Passer montanus",
            gbif_taxon_key=12345,
            common_name="スズメ",
            locale="ja",
            vernacular_names=[
                {"name": "スズメ", "language": "ja", "source": "inaturalist"},
                {"name": "Eurasian Tree Sparrow", "language": "en", "source": "gbif"},
            ],
        )

    # The legacy/en seed is the authoritative English name, NOT the 和名.
    repo.get_or_create_by_scientific_name.assert_awaited_once_with(
        scientific_name="Passer montanus",
        common_name="Eurasian Tree Sparrow",
    )


@pytest.mark.asyncio
async def test_from_gbif_omits_en_seed_when_no_en_entry_for_ja() -> None:
    """A ja locale with no en entry passes common_name=None to the repo."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_or_create_by_scientific_name = AsyncMock(return_value=taxon)
    repo.has_vernacular_in_locale = AsyncMock(return_value=True)

    service = TaxonService(taxon_repo=repo)

    with patch(
        "echoroo.services.taxon.resolve_vernacular_names",
        new=AsyncMock(return_value={taxon.id: "ノーエン"}),
    ):
        await service.create_from_gbif(
            scientific_name="Wsa Noenrow testus",
            gbif_taxon_key=12345,
            common_name="ノーエン",
            locale="ja",
            vernacular_names=[
                {"name": "ノーエン", "language": "ja", "source": "inaturalist"},
            ],
        )

    repo.get_or_create_by_scientific_name.assert_awaited_once_with(
        scientific_name="Wsa Noenrow testus",
        common_name=None,
    )


@pytest.mark.asyncio
async def test_from_gbif_enqueues_ja_fetch_when_no_ja_row() -> None:
    """create_from_gbif enqueues the ja fetch only when no ja row exists (F4).

    The taxon has a GBIF key and ja is requested; ``has_vernacular_in_locale``
    reports no exact ja row, so the best-effort backfill fires regardless of the
    en-fallback display name.
    """
    repo = _make_taxon_repo()
    taxon = _make_taxon()  # gbif_taxon_key is set on the mock
    repo.get_or_create_by_scientific_name = AsyncMock(return_value=taxon)
    repo.has_vernacular_in_locale = AsyncMock(return_value=False)

    service = TaxonService(taxon_repo=repo)

    with (
        patch(
            "echoroo.services.taxon.resolve_vernacular_names",
            # en-fallback resolves a name, but enqueue must still fire because
            # the EXACT ja row is absent.
            new=AsyncMock(return_value={taxon.id: "Great Tit"}),
        ),
        patch.object(TaxonService, "_maybe_enqueue_ja_fetch") as mock_enqueue,
    ):
        await service.create_from_gbif(
            scientific_name="Parus major",
            gbif_taxon_key=12345,
            locale="ja",
        )

    repo.has_vernacular_in_locale.assert_awaited_once_with(taxon.id, "ja")
    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_from_gbif_does_not_enqueue_when_ja_row_exists() -> None:
    """No enqueue when an exact ja row already exists (F4)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_or_create_by_scientific_name = AsyncMock(return_value=taxon)
    repo.has_vernacular_in_locale = AsyncMock(return_value=True)

    service = TaxonService(taxon_repo=repo)

    with (
        patch(
            "echoroo.services.taxon.resolve_vernacular_names",
            new=AsyncMock(return_value={taxon.id: "シジュウカラ"}),
        ),
        patch.object(TaxonService, "_maybe_enqueue_ja_fetch") as mock_enqueue,
    ):
        await service.create_from_gbif(
            scientific_name="Parus major",
            gbif_taxon_key=12345,
            locale="ja",
        )

    repo.has_vernacular_in_locale.assert_awaited_once_with(taxon.id, "ja")
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_from_gbif_ja_jp_locale_normalized_for_enqueue() -> None:
    """``ja-JP`` normalizes to ``ja`` and still gates the enqueue (F3 + F4)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_or_create_by_scientific_name = AsyncMock(return_value=taxon)
    repo.has_vernacular_in_locale = AsyncMock(return_value=False)

    service = TaxonService(taxon_repo=repo)

    with (
        patch(
            "echoroo.services.taxon.resolve_vernacular_names",
            new=AsyncMock(return_value={}),
        ),
        patch.object(TaxonService, "_maybe_enqueue_ja_fetch") as mock_enqueue,
    ):
        await service.create_from_gbif(
            scientific_name="Parus major",
            gbif_taxon_key=12345,
            locale="ja-JP",
        )

    mock_enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_gbif_batch_returns_zero_when_no_unresolved() -> None:
    """resolve_gbif_batch returns 0 when no unresolved taxa (line 124-125)."""
    repo = _make_taxon_repo()
    repo.get_unresolved = AsyncMock(return_value=[])

    service = TaxonService(taxon_repo=repo)
    result = await service.resolve_gbif_batch()

    assert result == 0


@pytest.mark.asyncio
async def test_resolve_gbif_batch_resolves_taxon_with_gbif_data() -> None:
    """resolve_gbif_batch processes taxa and returns count resolved (lines 126-147)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_unresolved = AsyncMock(return_value=[taxon])
    repo.update = AsyncMock()

    gbif_result = MagicMock()
    gbif_result.taxon_key = 98765
    gbif_result.rank = "SPECIES"
    gbif_result.metadata = {"key": "val"}

    gbif_service = _make_gbif_service()
    gbif_service.resolve_taxon = AsyncMock(return_value=gbif_result)

    service = TaxonService(taxon_repo=repo, gbif_service=gbif_service)
    count = await service.resolve_gbif_batch(limit=10)

    assert count == 1
    repo.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_gbif_batch_handles_no_gbif_match() -> None:
    """resolve_gbif_batch handles None GBIF result (lines 130-133)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.get_unresolved = AsyncMock(return_value=[taxon])
    repo.update = AsyncMock()

    gbif_service = _make_gbif_service()
    gbif_service.resolve_taxon = AsyncMock(return_value=None)

    service = TaxonService(taxon_repo=repo, gbif_service=gbif_service)
    count = await service.resolve_gbif_batch(limit=10)

    # None result means gbif data not found — not counted as resolved
    assert count == 0
    repo.update.assert_awaited_once()
