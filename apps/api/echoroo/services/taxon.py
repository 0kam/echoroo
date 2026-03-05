"""Taxon service for business logic."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.repositories.taxon import TaxonRepository
from echoroo.schemas.taxon import (
    TaxonDetailResponse,
    TaxonListResponse,
    TaxonResponse,
    TaxonSearchResult,
    VernacularNameResponse,
)
from echoroo.services.gbif import GBIFService

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
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 200:
            page_size = 50

        taxa, total = await self.taxon_repo.list_taxa(
            search=search,
            is_non_biological=is_non_biological,
            page=page,
            page_size=page_size,
        )
        pages = math.ceil(total / page_size) if total > 0 else 1

        return TaxonListResponse(
            items=[TaxonResponse.model_validate(t) for t in taxa],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
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
        results = await self.taxon_repo.search(query, locale=locale, limit=limit)
        return [
            TaxonSearchResult(
                id=taxon.id,
                scientific_name=taxon.scientific_name,
                gbif_taxon_key=taxon.gbif_taxon_key,
                rank=taxon.rank,
                is_non_biological=taxon.is_non_biological,
                common_name=common_name,
            )
            for taxon, common_name in results
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
        """Resolve GBIF data for unresolved taxa. Returns count of resolved."""
        unresolved = await self.taxon_repo.get_unresolved(limit=limit)
        resolved_count = 0

        for taxon in unresolved:
            result = await self.gbif_service.resolve_taxon(taxon.scientific_name)
            if result is None:
                # Mark as attempted even if not found
                taxon.gbif_resolved_at = datetime.now(UTC)
                await self.taxon_repo.update(taxon)
                continue

            taxon.gbif_taxon_key = result.taxon_key
            taxon.rank = result.rank
            taxon.gbif_metadata = result.metadata
            taxon.gbif_resolved_at = datetime.now(UTC)
            await self.taxon_repo.update(taxon)
            resolved_count += 1

        return resolved_count
