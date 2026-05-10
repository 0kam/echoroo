"""Coverage uplift unit tests for ``echoroo.api.v1.taxa``.

Phase 17 §C medium-gap batch: targets ``get_taxon_service`` (line 32),
``list_taxa`` (line 68), ``search_taxa`` (line 106), ``gbif_search_taxa``
(lines 139-141), and ``get_taxon`` (line 169) so the module clears the
85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.api.v1 import taxa as mod


def test_get_taxon_service_returns_service_instance() -> None:
    """get_taxon_service constructs a TaxonService."""
    db = MagicMock()
    svc = mod.get_taxon_service(db)
    assert svc is not None


@pytest.mark.asyncio
async def test_list_taxa_delegates_to_service() -> None:
    """list_taxa forwards args to service.list_taxa (line 68)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.list_taxa = AsyncMock(return_value=sentinel)

    user = MagicMock()
    result = await mod.list_taxa(
        current_user=user,
        service=service,
        search="oak",
        is_non_biological=False,
        page=1,
        page_size=50,
    )
    assert result is sentinel
    service.list_taxa.assert_awaited_once_with(
        search="oak", is_non_biological=False, page=1, page_size=50
    )


@pytest.mark.asyncio
async def test_search_taxa_delegates_to_service() -> None:
    """search_taxa forwards args to service.search (line 106)."""
    sentinel = [MagicMock()]
    service = MagicMock()
    service.search = AsyncMock(return_value=sentinel)

    user = MagicMock()
    result = await mod.search_taxa(
        current_user=user,
        service=service,
        q="quercus",
        locale="en",
        limit=10,
    )
    assert result is sentinel
    service.search.assert_awaited_once_with(query="quercus", locale="en", limit=10)


@pytest.mark.asyncio
async def test_gbif_search_taxa_returns_validated_results() -> None:
    """gbif_search_taxa instantiates GBIFService and validates each row (lines 139-141)."""
    raw = [{"key": 1, "scientificName": "Quercus rubra"}]
    gbif = MagicMock()
    gbif.search_species_full = AsyncMock(return_value=raw)

    sentinel = MagicMock()
    user = MagicMock()
    with patch.object(mod, "GBIFService", return_value=gbif), \
            patch.object(mod.GBIFSpeciesResult, "model_validate", return_value=sentinel):
        result = await mod.gbif_search_taxa(current_user=user, q="oak", limit=5)
    assert result == [sentinel]
    gbif.search_species_full.assert_awaited_once_with(query="oak", limit=5)


@pytest.mark.asyncio
async def test_get_taxon_delegates_to_service() -> None:
    """get_taxon forwards taxon_id to service.get_detail (line 169)."""
    sentinel = MagicMock()
    service = MagicMock()
    service.get_detail = AsyncMock(return_value=sentinel)
    user = MagicMock()
    taxon_id = uuid4()
    result = await mod.get_taxon(taxon_id=taxon_id, current_user=user, service=service)
    assert result is sentinel
    service.get_detail.assert_awaited_once_with(taxon_id=taxon_id)
