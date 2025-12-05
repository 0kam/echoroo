"""REST API routes for species search."""

from fastapi import APIRouter, Query

from echoroo import api, schemas

species_router = APIRouter()


@species_router.get(
    "/search/",
    response_model=list[schemas.SpeciesCandidate],
)
async def search_species(
    q: str = Query(..., min_length=2, description="Search term for GBIF."),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[schemas.SpeciesCandidate]:
    """Search GBIF's backbone taxonomy for species suggestions."""
    return await api.search_gbif_species(q, limit=limit)
