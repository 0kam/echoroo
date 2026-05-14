"""Detection-run BFF adapters outside a project prefix."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from echoroo.api.v1 import detection_runs as legacy_detection_runs
from echoroo.middleware.auth import CurrentUser
from echoroo.models.user import User

router = APIRouter(prefix="/detection-runs", tags=["detection-runs"])


def _require_authenticated(current_user: User | None) -> User:
    """Return the authenticated caller for global auth-only routes."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user


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
    _require_authenticated(current_user)
    return await legacy_detection_runs.list_available_models(current_user=current_user)
