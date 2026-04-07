"""Taxa API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.taxon import TaxonRepository
from echoroo.schemas.taxon import (
    GBIFSpeciesResult,
    TaxonDetailResponse,
    TaxonListResponse,
    TaxonSearchResult,
)
from echoroo.services.gbif import GBIFService
from echoroo.services.taxon import TaxonService

router = APIRouter(prefix="/taxa", tags=["taxa"])


def get_taxon_service(db: DbSession) -> TaxonService:
    """Get TaxonService instance.

    Args:
        db: Database session

    Returns:
        TaxonService instance
    """
    return TaxonService(taxon_repo=TaxonRepository(db))


TaxonServiceDep = Annotated[TaxonService, Depends(get_taxon_service)]


@router.get(
    "",
    response_model=TaxonListResponse,
    summary="List taxa",
    description="List taxa with optional filtering and pagination",
)
async def list_taxa(
    current_user: CurrentUser,
    service: TaxonServiceDep,
    search: str | None = None,
    is_non_biological: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> TaxonListResponse:
    """List taxa with optional filtering and pagination.

    Args:
        current_user: Current authenticated user
        service: Taxon service instance
        search: Optional search string for scientific name
        is_non_biological: Optional filter for non-biological taxa
        page: Page number (default: 1)
        page_size: Items per page (default: 50)

    Returns:
        Paginated list of taxa

    Raises:
        401: Not authenticated
    """
    return await service.list_taxa(
        search=search,
        is_non_biological=is_non_biological,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/search",
    response_model=list[TaxonSearchResult],
    summary="Search taxa",
    description="Search taxa by scientific name or vernacular name",
)
async def search_taxa(
    current_user: CurrentUser,
    service: TaxonServiceDep,
    q: str,
    locale: str | None = None,
    limit: int = 20,
) -> list[TaxonSearchResult]:
    """Search taxa by scientific name or vernacular name.

    NOTE: This route must appear before /{taxon_id} to avoid routing conflicts.

    Args:
        current_user: Current authenticated user
        service: Taxon service instance
        q: Search query string (required)
        locale: Optional locale filter for vernacular names
        limit: Maximum results to return (default: 20)

    Returns:
        List of matching taxa with optional common names

    Raises:
        401: Not authenticated
    """
    return await service.search(query=q, locale=locale, limit=limit)


@router.get(
    "/gbif-search",
    response_model=list[GBIFSpeciesResult],
    summary="Search species via GBIF real-time API",
    description=(
        "Search any species using the GBIF /v1/species/search API. "
        "Returns results from the GBIF Backbone Taxonomy including vernacular names. "
        "Useful for finding species not yet in the local taxa database."
    ),
)
async def gbif_search_taxa(
    current_user: CurrentUser,
    q: str,
    limit: int = 10,
) -> list[GBIFSpeciesResult]:
    """Search GBIF Backbone Taxonomy for species matching the query string.

    NOTE: This route must appear before /{taxon_id} to avoid routing conflicts.

    Args:
        current_user: Current authenticated user
        q: Search query string (scientific name, vernacular name, etc.)
        limit: Maximum number of results to return (default: 10)

    Returns:
        List of matching species results with vernacular names

    Raises:
        401: Not authenticated
    """
    gbif_service = GBIFService()
    raw_results = await gbif_service.search_species_full(query=q, limit=limit)
    return [GBIFSpeciesResult.model_validate(r) for r in raw_results]


@router.get(
    "/{taxon_id}",
    response_model=TaxonDetailResponse,
    summary="Get taxon detail",
    description="Get taxon detail with vernacular names and GBIF metadata",
)
async def get_taxon(
    taxon_id: UUID,
    current_user: CurrentUser,
    service: TaxonServiceDep,
) -> TaxonDetailResponse:
    """Get taxon detail with vernacular names.

    Args:
        taxon_id: Taxon's UUID
        current_user: Current authenticated user
        service: Taxon service instance

    Returns:
        Taxon detail with vernacular names and GBIF metadata

    Raises:
        401: Not authenticated
        404: Taxon not found
    """
    return await service.get_detail(taxon_id=taxon_id)
