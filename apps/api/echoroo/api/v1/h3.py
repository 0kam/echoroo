"""H3 utility API endpoints."""

from fastapi import APIRouter, HTTPException, status

from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.site import (
    H3FromCoordinatesRequest,
    H3FromCoordinatesResponse,
    H3ValidationRequest,
    H3ValidationResponse,
)
from echoroo.services.h3_utils import (
    h3_from_coordinates,
    h3_to_boundary,
    h3_to_center,
    validate_h3_index,
)

router = APIRouter(prefix="/h3", tags=["h3"])


@router.post(
    "/validate",
    response_model=H3ValidationResponse,
    summary="Validate H3 index",
    description="Validate an H3 index and return its properties",
)
async def validate_h3(
    request: H3ValidationRequest,
    current_user: CurrentUser,  # noqa: ARG001
) -> H3ValidationResponse:
    """Validate an H3 index and return its properties.

    Args:
        request: H3 validation request
        current_user: Current authenticated user

    Returns:
        H3 validation response with properties

    Raises:
        401: Not authenticated
    """
    is_valid, resolution, error = validate_h3_index(request.h3_index)

    if not is_valid:
        return H3ValidationResponse(
            valid=False,
            resolution=None,
            latitude=None,
            longitude=None,
            error=error,
        )

    lat, lng = h3_to_center(request.h3_index)
    return H3ValidationResponse(
        valid=True,
        resolution=resolution,
        latitude=lat,
        longitude=lng,
        error=None,
    )


@router.post(
    "/from-coordinates",
    response_model=H3FromCoordinatesResponse,
    summary="Get H3 from coordinates",
    description="Get H3 index from latitude/longitude coordinates",
)
async def get_h3_from_coordinates(
    request: H3FromCoordinatesRequest,
    current_user: CurrentUser,  # noqa: ARG001
) -> H3FromCoordinatesResponse:
    """Get H3 index from latitude/longitude coordinates.

    Args:
        request: Coordinates and resolution
        current_user: Current authenticated user

    Returns:
        H3 index and properties

    Raises:
        400: Invalid coordinates or resolution
        401: Not authenticated
    """
    try:
        h3_index = h3_from_coordinates(
            request.latitude, request.longitude, request.resolution
        )
        lat, lng = h3_to_center(h3_index)
        boundary = h3_to_boundary(h3_index)

        return H3FromCoordinatesResponse(
            h3_index=h3_index,
            resolution=request.resolution,
            latitude=lat,
            longitude=lng,
            boundary=boundary,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
