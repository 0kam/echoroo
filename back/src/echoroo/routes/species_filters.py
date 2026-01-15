"""Routes for species filter operations."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from echoroo import models, schemas
from echoroo.api import species_filters
from echoroo.routes.dependencies import (
    Session,
    EchorooSettings,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)

__all__ = ["get_species_filters_router"]


def get_species_filters_router(settings: EchorooSettings) -> APIRouter:
    """Create router for species filter endpoints."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # Species Filters
    # =========================================================================

    @router.get(
        "/",
        response_model=list[schemas.SpeciesFilter],
    )
    async def list_filters(
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """List available species filters."""
        return await species_filters.list_filters(session)

    return router


def get_species_filter_applications_router(settings: EchorooSettings) -> APIRouter:
    """Create router for species filter application endpoints under runs."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # Filter Applications for Runs
    # =========================================================================

    @router.post(
        "/apply",
        response_model=schemas.SpeciesFilterApplication,
        status_code=status.HTTP_201_CREATED,
    )
    async def apply_filter(
        run_uuid: UUID,
        data: schemas.SpeciesFilterApplicationCreate,
        session: Session,
        user: models.User = Depends(current_user_dep),
    ):
        """Apply a species filter to a foundation model run."""
        application = await species_filters.apply_filter(
            session,
            run_uuid,
            data.filter_slug,
            data.threshold,
            user=user,
            apply_to_all_detections=data.apply_to_all_detections,
        )
        await session.commit()
        return application

    @router.get(
        "/",
        response_model=list[schemas.SpeciesFilterApplication],
    )
    async def list_applications(
        run_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """List filter applications for a foundation model run."""
        return await species_filters.list_applications(
            session,
            run_uuid,
            user=user,
        )

    @router.get(
        "/{filter_uuid}",
        response_model=schemas.SpeciesFilterApplication,
    )
    async def get_application(
        run_uuid: UUID,
        filter_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get a filter application by UUID."""
        return await species_filters.get_application_by_run_and_uuid(
            session,
            run_uuid,
            filter_uuid,
            user=user,
        )

    @router.get(
        "/{filter_uuid}/progress",
        response_model=schemas.SpeciesFilterApplicationProgress,
    )
    async def get_application_progress(
        run_uuid: UUID,
        filter_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get progress for a filter application."""
        return await species_filters.get_application_progress(
            session,
            run_uuid,
            filter_uuid,
            user=user,
        )

    @router.get(
        "/{filter_uuid}/species",
        response_model=schemas.SpeciesFilterResults,
    )
    async def get_filter_species(
        run_uuid: UUID,
        filter_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
        locale: str = Query("ja", description="Locale for common names (e.g., 'ja', 'en')"),
    ):
        """Get species results for a filter application."""
        return await species_filters.get_application_species_results(
            session,
            run_uuid,
            filter_uuid,
            user=user,
            locale=locale,
        )

    @router.post(
        "/{filter_uuid}/cancel",
        response_model=schemas.SpeciesFilterApplication,
    )
    async def cancel_application(
        run_uuid: UUID,
        filter_uuid: UUID,
        session: Session,
        user: models.User = Depends(current_user_dep),
    ):
        """Cancel a running or queued species filter application."""
        result = await species_filters.cancel_application(
            session,
            run_uuid,
            filter_uuid,
            user=user,
        )
        await session.commit()
        return result

    return router
