"""First-party session taxa search routes for the Web UI."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.user import User
from echoroo.repositories.taxon import TaxonRepository
from echoroo.schemas.taxon import (
    GBIFSpeciesResult,
    TaxonFromGBIFRequest,
    TaxonSearchResult,
)
from echoroo.services.gbif import GBIFService
from echoroo.services.taxon import TaxonService

router = APIRouter(prefix="/taxa", tags=["taxa"])


def get_taxon_service(db: DbSession) -> TaxonService:
    """Build the shared taxon service used by legacy and BFF routers."""
    return TaxonService(taxon_repo=TaxonRepository(db))


TaxonServiceDep = Annotated[TaxonService, Depends(get_taxon_service)]


def _require_authenticated(current_user: User | None) -> User:
    """Return the authenticated caller or raise the existing 401 response."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user


@router.get(
    "/search",
    response_model=list[TaxonSearchResult],
    summary="Search taxa (Web UI)",
    description=(
        "Cookie/Bearer session mirror of the programmatic taxa search route. "
        "Used by species autocomplete surfaces in the first-party UI."
    ),
)
async def search_taxa(
    current_user: CurrentUser,
    service: TaxonServiceDep,
    q: str,
    locale: str | None = None,
    limit: int = 20,
) -> list[TaxonSearchResult]:
    """Search taxa by scientific or vernacular name for the Web UI."""
    _require_authenticated(current_user)
    return await service.search(query=q, locale=locale, limit=limit)


@router.get(
    "/gbif-search",
    response_model=list[GBIFSpeciesResult],
    summary="Search species via GBIF real-time API (Web UI)",
    description=(
        "Cookie/Bearer session mirror of the programmatic GBIF species search "
        "route. Used by first-party species autocomplete when local taxa do "
        "not contain the desired species."
    ),
)
async def gbif_search_taxa(
    current_user: CurrentUser,
    q: str,
    limit: int = 10,
    locale: str = "en",
) -> list[GBIFSpeciesResult]:
    """Search GBIF Backbone Taxonomy for species matching the query string.

    For non-en ``locale`` the top results' vernacular names are live-enriched
    (iNaturalist/GBIF) so the picker can display the localized common name. The
    ``en`` path makes no extra external calls.
    """
    _require_authenticated(current_user)
    gbif_service = GBIFService()
    raw_results = await gbif_service.search_species_full(
        query=q, limit=limit, locale=locale
    )
    return [GBIFSpeciesResult.model_validate(r) for r in raw_results]


@router.post(
    "/from-gbif",
    response_model=TaxonSearchResult,
    summary="Create a local taxon from a GBIF pick (Web UI)",
    description=(
        "Cookie/Bearer session mirror of the programmatic from-GBIF route. "
        "Get-or-creates a local taxa row for a species picked from the live "
        "GBIF search and returns it so the annotation-set palette can add the "
        "species. Idempotent: repeated calls return the same taxon."
    ),
)
async def create_taxon_from_gbif(
    current_user: CurrentUser,
    service: TaxonServiceDep,
    payload: TaxonFromGBIFRequest,
    locale: str | None = None,
) -> TaxonSearchResult:
    """Materialise a GBIF search pick into a local taxon for the Web UI."""
    _require_authenticated(current_user)
    return await service.create_from_gbif(
        scientific_name=payload.scientific_name,
        gbif_taxon_key=payload.gbif_taxon_key,
        common_name=payload.common_name,
        locale=locale or "en",
        vernacular_names=(
            [vn.model_dump() for vn in payload.vernacular_names]
            if payload.vernacular_names
            else None
        ),
    )


__all__ = ["router"]
