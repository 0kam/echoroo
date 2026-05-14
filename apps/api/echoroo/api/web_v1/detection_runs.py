"""Detection-run BFF adapters outside a project prefix."""

from __future__ import annotations

from fastapi import APIRouter

from echoroo.api.v1 import detection_runs as legacy_detection_runs
from echoroo.middleware.auth import CurrentUser

router = APIRouter(prefix="/detection-runs", tags=["detection-runs"])


@router.get(
    "/available-models",
    response_model=legacy_detection_runs.AvailableModelsResponse,
    summary="Get available detection models",
    description="BFF adapter for the legacy available detection models endpoint.",
)
async def get_available_models(
    current_user: CurrentUser,
) -> legacy_detection_runs.AvailableModelsResponse:
    """Delegate available-model discovery to the legacy handler."""
    return await legacy_detection_runs.list_available_models(current_user=current_user)
