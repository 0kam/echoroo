"""Taxon service for business logic."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.core.pagination import paginate
from echoroo.models.taxon import Taxon
from echoroo.repositories.taxon import TaxonRepository
from echoroo.schemas.taxon import (
    TaxonDetailResponse,
    TaxonListResponse,
    TaxonResponse,
    TaxonSearchResult,
    VernacularNameResponse,
)
from echoroo.services.gbif import GBIFService
from echoroo.services.vernacular import resolve_vernacular_names

# Maximum number of concurrent GBIF HTTP calls during batch resolution.
# GBIF rate limit is 10 req/s; keeping concurrency below that avoids 429s.
_GBIF_BATCH_CONCURRENCY = 8

logger = logging.getLogger(__name__)


class TaxonService:
    """Service for taxon management."""

    def __init__(
        self,
        taxon_repo: TaxonRepository,
        gbif_service: GBIFService | None = None,
    ) -> None:
        self.taxon_repo = taxon_repo
        self.gbif_service = gbif_service or GBIFService()

    async def list_taxa(
        self,
        search: str | None = None,
        is_non_biological: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> TaxonListResponse:
        pagination = paginate(page, page_size)

        taxa, total = await self.taxon_repo.list_taxa(
            search=search,
            is_non_biological=is_non_biological,
            page=pagination.page,
            page_size=pagination.page_size,
        )

        return TaxonListResponse(
            items=[TaxonResponse.model_validate(t) for t in taxa],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def get_detail(self, taxon_id: UUID) -> TaxonDetailResponse:
        taxon = await self.taxon_repo.get_by_id(taxon_id)
        if not taxon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Taxon not found",
            )

        return TaxonDetailResponse(
            **TaxonResponse.model_validate(taxon).model_dump(),
            gbif_metadata=taxon.gbif_metadata,
            gbif_resolved_at=taxon.gbif_resolved_at,
            vernacular_names=[
                VernacularNameResponse.model_validate(vn)
                for vn in taxon.vernacular_names
            ],
            updated_at=taxon.updated_at,
        )

    async def search(
        self,
        query: str,
        locale: str | None = None,
        limit: int = 20,
    ) -> list[TaxonSearchResult]:
        """Search taxa, resolving each result's display ``common_name``.

        Matching is locale-agnostic (an English-name query still works under a
        ``ja`` UI). The ``locale`` argument controls only the display name:
        each result's ``common_name`` is resolved with a requested-locale →
        English fallback chain. When no vernacular row exists in either the
        requested locale or English, ``common_name`` stays ``None`` (the
        scientific-name floor is applied by the frontend display formatter).
        """
        taxa = await self.taxon_repo.search(query, limit=limit)

        # Batch-resolve the display name for the requested locale (ja→en
        # fallback). Default to English when no locale is supplied.
        display_locale = locale or "en"
        common_names = await resolve_vernacular_names(
            self.taxon_repo.db,
            [taxon.id for taxon in taxa],
            display_locale,
        )

        return [
            TaxonSearchResult(
                id=taxon.id,
                scientific_name=taxon.scientific_name,
                gbif_taxon_key=taxon.gbif_taxon_key,
                rank=taxon.rank,
                is_non_biological=taxon.is_non_biological,
                common_name=common_names.get(taxon.id),
            )
            for taxon in taxa
        ]

    async def get_or_create(
        self,
        scientific_name: str,
        common_name: str | None = None,
        is_non_biological: bool = False,
    ) -> TaxonResponse:
        taxon = await self.taxon_repo.get_or_create_by_scientific_name(
            scientific_name=scientific_name,
            common_name=common_name,
            is_non_biological=is_non_biological,
        )
        return TaxonResponse.model_validate(taxon)

    async def resolve_gbif_batch(self, limit: int = 100) -> int:
        """Resolve GBIF data for unresolved taxa. Returns count of resolved.

        Fetches GBIF data for all unresolved taxa concurrently (up to
        _GBIF_BATCH_CONCURRENCY parallel requests) instead of sequentially,
        which eliminates the N+1 HTTP call pattern.
        """
        unresolved = await self.taxon_repo.get_unresolved(limit=limit)
        if not unresolved:
            return 0

        semaphore = asyncio.Semaphore(_GBIF_BATCH_CONCURRENCY)

        async def resolve_one(taxon: Taxon) -> bool:
            """Resolve a single taxon; return True if GBIF data was found."""
            async with semaphore:
                result = await self.gbif_service.resolve_taxon(taxon.scientific_name)
                if result is None:
                    taxon.gbif_resolved_at = datetime.now(UTC)
                    await self.taxon_repo.update(taxon)
                    return False

                taxon.gbif_taxon_key = result.taxon_key
                taxon.rank = result.rank
                taxon.gbif_metadata = result.metadata
                taxon.gbif_resolved_at = datetime.now(UTC)
                await self.taxon_repo.update(taxon)
                return True

        results = await asyncio.gather(*[resolve_one(t) for t in unresolved])
        return sum(1 for r in results if r)
