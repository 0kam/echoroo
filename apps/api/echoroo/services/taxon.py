"""Taxon service for business logic."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

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

    async def create_from_gbif(
        self,
        scientific_name: str,
        gbif_taxon_key: int | None = None,
        common_name: str | None = None,
        locale: str = "en",
    ) -> TaxonSearchResult:
        """Materialise a GBIF search pick into a local taxon (idempotent).

        Get-or-creates the ``taxa`` row keyed by ``scientific_name`` (the
        unique business key). When a ``gbif_taxon_key`` is supplied and the
        taxon does not yet have one, the key is backfilled — but only if no
        other taxon already owns it, because ``ix_taxa_gbif_taxon_key`` is a
        partial-unique index (``WHERE gbif_taxon_key IS NOT NULL``). If the
        key is already owned elsewhere it is silently left unset rather than
        raising; the row is still returned so the caller can use it.

        The returned shape mirrors :meth:`search` (``TaxonSearchResult``) so
        the frontend can reuse the same type, including a locale-resolved
        ``common_name`` (requested locale → English fallback).
        """
        # ``get_or_create_by_scientific_name`` has already ``add``+``flush``ed
        # the taxon (no commit) when it is newly created, so the SAVEPOINT
        # below scopes only the subsequent key assignment.
        taxon = await self.taxon_repo.get_or_create_by_scientific_name(
            scientific_name=scientific_name,
            common_name=common_name,
        )

        # Backfill the GBIF key only when the taxon lacks one. Guard the
        # partial-unique constraint: skip the assignment when another taxon
        # already owns this key, and defensively catch a concurrent insert
        # that races past the pre-check.
        if gbif_taxon_key is not None and taxon.gbif_taxon_key is None:
            owner = await self.taxon_repo.get_by_gbif_taxon_key(gbif_taxon_key)
            if owner is None or owner.id == taxon.id:
                try:
                    # SAVEPOINT-scope BOTH the key assignment and its flush so
                    # a lost race for the unique key rolls back ONLY this
                    # assignment — never the just-created taxon (and its seeded
                    # en vernacular) living in the same uncommitted
                    # transaction. Assigning inside the savepoint lets the
                    # ROLLBACK TO SAVEPOINT discard the pending dirty attribute,
                    # so the next flush does not re-emit the failing UPDATE.
                    async with self.taxon_repo.db.begin_nested():
                        taxon.gbif_taxon_key = gbif_taxon_key
                        await self.taxon_repo.update(taxon)
                except IntegrityError:
                    # Lost the race for the unique key. ROLLBACK TO SAVEPOINT
                    # reverted the DB row and expired the ORM instance, leaving
                    # the surrounding transaction usable. Refresh the SAME
                    # taxon (the row still exists — never re-fetch a phantom)
                    # in the async context so its attributes — including the
                    # now-NULL gbif_taxon_key — are eagerly reloaded; this
                    # avoids a synchronous lazy-load (MissingGreenlet) when the
                    # response is built below.
                    await self.taxon_repo.db.refresh(taxon)

        display_locale = locale or "en"
        common_names = await resolve_vernacular_names(
            self.taxon_repo.db,
            [taxon.id],
            display_locale,
        )

        return TaxonSearchResult(
            id=taxon.id,
            scientific_name=taxon.scientific_name,
            gbif_taxon_key=taxon.gbif_taxon_key,
            rank=taxon.rank,
            is_non_biological=taxon.is_non_biological,
            common_name=common_names.get(taxon.id),
        )

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
