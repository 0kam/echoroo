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

from echoroo.services.taxon import TaxonService


def _make_taxon_repo() -> MagicMock:
    repo = MagicMock()
    repo.list_taxa = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.search = AsyncMock()
    repo.get_or_create_by_scientific_name = AsyncMock()
    repo.get_unresolved = AsyncMock()
    repo.update = AsyncMock()
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
    """search returns list of TaxonSearchResult (lines 91-100)."""
    repo = _make_taxon_repo()
    taxon = _make_taxon()
    repo.search = AsyncMock(return_value=[(taxon, "Great Tit")])

    service = TaxonService(taxon_repo=repo)
    results = await service.search(query="Parus")

    assert len(results) == 1
    assert results[0].scientific_name == "Parus major"
    assert results[0].common_name == "Great Tit"


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
