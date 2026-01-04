"""Routes for detection visualization endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from echoroo import models
from echoroo.api import detection_visualization
from echoroo.routes.dependencies import (
    Session,
    EchorooSettings,
    get_optional_current_user_dependency,
)
from echoroo.schemas.detection_visualization import DetectionTemporalData

__all__ = ["get_detection_visualization_router"]


def get_detection_visualization_router(settings: EchorooSettings) -> APIRouter:
    """Create router for detection visualization endpoints."""
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    @router.get(
        "/temporal/",
        response_model=DetectionTemporalData,
    )
    async def get_temporal_data(
        session: Session,
        run_uuid: UUID = Query(..., description="Foundation model run UUID"),
        filter_application_uuid: UUID | None = Query(
            default=None,
            description="Species filter application UUID. If provided, only include detections that passed the filter.",
        ),
        locale: str = Query(
            default="en",
            description="Locale for common names (e.g., 'en', 'ja')",
        ),
        user: models.User | None = Depends(optional_user_dep),
    ) -> DetectionTemporalData:
        """Get detection temporal data for polar heatmap visualization.

        Returns aggregated detection counts by hour (0-23) and date,
        grouped by species. This data is suitable for rendering polar
        heatmaps that show detection patterns over time.

        If filter_application_uuid is provided, only detections that
        passed the species filter (is_included=true) are included.
        """
        return await detection_visualization.get_detection_temporal_data(
            session,
            run_uuid,
            filter_application_uuid=filter_application_uuid,
            locale=locale,
            user=user,
        )

    return router
