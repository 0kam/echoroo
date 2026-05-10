"""Coverage uplift unit tests for ``echoroo.api.v1.h3`` and
``echoroo.services.h3_utils``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the route handlers
and utility functions so both modules clear the 85% threshold.

echoroo/api/v1/h3.py missing lines: 44,46,47,55,56,88,89,92,93,95,102,103
echoroo/services/h3_utils.py missing lines: 21,24,25,42-50,62,63,90,92,110
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from echoroo.services.h3_utils import (
    h3_coordinate_uncertainty,
    h3_from_coordinates,
    h3_to_boundary,
    h3_to_center,
    validate_h3_index,
)

# ---------------------------------------------------------------------------
# echoroo/services/h3_utils.py
# ---------------------------------------------------------------------------


def test_validate_h3_index_invalid_format() -> None:
    """validate_h3_index returns (False, None, error) for invalid index (line 21)."""
    with patch("echoroo.services.h3_utils.h3.is_valid_cell", return_value=False):
        valid, resolution, error = validate_h3_index("INVALID")
    assert valid is False
    assert resolution is None
    assert error is not None


def test_validate_h3_index_resolution_out_of_range() -> None:
    """validate_h3_index returns False when resolution < 5 (lines 24-25)."""
    with (
        patch("echoroo.services.h3_utils.h3.is_valid_cell", return_value=True),
        patch("echoroo.services.h3_utils.h3.get_resolution", return_value=2),
    ):
        valid, resolution, error = validate_h3_index("someindex")
    assert valid is False
    assert resolution == 2
    assert "out of range" in (error or "")


def test_validate_h3_index_exception_path() -> None:
    """validate_h3_index catches any exception and returns False (line 26-27)."""
    with patch(
        "echoroo.services.h3_utils.h3.is_valid_cell",
        side_effect=RuntimeError("h3 error"),
    ):
        valid, resolution, error = validate_h3_index("x")
    assert valid is False
    assert error is not None


def test_h3_from_coordinates_invalid_latitude() -> None:
    """h3_from_coordinates raises ValueError for invalid latitude (lines 42-43)."""
    with pytest.raises(ValueError, match="Latitude"):
        h3_from_coordinates(91.0, 0.0, 7)


def test_h3_from_coordinates_invalid_longitude() -> None:
    """h3_from_coordinates raises ValueError for invalid longitude (lines 44-45)."""
    with pytest.raises(ValueError, match="Longitude"):
        h3_from_coordinates(0.0, 181.0, 7)


def test_h3_from_coordinates_invalid_resolution() -> None:
    """h3_from_coordinates raises ValueError for invalid resolution (lines 46-47)."""
    with pytest.raises(ValueError, match="Resolution"):
        h3_from_coordinates(0.0, 0.0, 3)


def test_h3_from_coordinates_happy_path() -> None:
    """h3_from_coordinates calls h3.latlng_to_cell and returns index (lines 49-50)."""
    with patch(
        "echoroo.services.h3_utils.h3.latlng_to_cell", return_value="fake_h3"
    ):
        result = h3_from_coordinates(35.0, 135.0, 7)
    assert result == "fake_h3"


def test_h3_to_center_returns_lat_lng() -> None:
    """h3_to_center calls h3.cell_to_latlng and returns (lat, lng) (lines 62-63)."""
    with patch(
        "echoroo.services.h3_utils.h3.cell_to_latlng", return_value=(35.0, 135.0)
    ):
        lat, lng = h3_to_center("87283082bffffff")
    assert lat == 35.0
    assert lng == 135.0


def test_h3_to_boundary_converts_list() -> None:
    """h3_to_boundary converts cell_to_boundary output to [[lat,lng],...] (line 75)."""
    boundary_pairs = [(35.0, 135.0), (35.1, 135.1), (35.2, 135.2)]
    with patch(
        "echoroo.services.h3_utils.h3.cell_to_boundary", return_value=boundary_pairs
    ):
        result = h3_to_boundary("87283082bffffff")
    assert result == [[35.0, 135.0], [35.1, 135.1], [35.2, 135.2]]


def test_h3_coordinate_uncertainty_known_resolution() -> None:
    """h3_coordinate_uncertainty returns edge length for a known resolution (line 90)."""
    with patch(
        "echoroo.services.h3_utils.h3.get_resolution", return_value=7
    ):
        result = h3_coordinate_uncertainty("87283082bffffff")
    assert result == 1220.63  # resolution 7 value from the table


def test_h3_coordinate_uncertainty_unknown_resolution_returns_zero() -> None:
    """h3_coordinate_uncertainty returns 0.0 for an unmapped resolution (line 92)."""
    with patch(
        "echoroo.services.h3_utils.h3.get_resolution", return_value=16
    ):
        result = h3_coordinate_uncertainty("bad_index")
    assert result == 0.0


# ---------------------------------------------------------------------------
# echoroo/api/v1/h3.py
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_h3_returns_invalid_response_when_not_valid() -> None:
    """validate_h3() returns invalid response when h3 index is invalid (lines 44,46,47)."""
    from echoroo.api.v1.h3 import validate_h3
    from echoroo.schemas.site import H3ValidationRequest

    request = H3ValidationRequest(h3_index="INVALID")
    current_user = MagicMock()

    with patch(
        "echoroo.api.v1.h3.validate_h3_index",
        return_value=(False, None, "Invalid H3 index format"),
    ):
        response = await validate_h3(request=request, current_user=current_user)

    assert response.valid is False
    assert response.resolution is None
    assert response.error == "Invalid H3 index format"


@pytest.mark.asyncio
async def test_validate_h3_returns_valid_response_with_coords() -> None:
    """validate_h3() returns valid response with center coords (lines 55-56)."""
    from echoroo.api.v1.h3 import validate_h3
    from echoroo.schemas.site import H3ValidationRequest

    request = H3ValidationRequest(h3_index="87283082bffffff")
    current_user = MagicMock()

    with (
        patch(
            "echoroo.api.v1.h3.validate_h3_index",
            return_value=(True, 7, None),
        ),
        patch(
            "echoroo.api.v1.h3.h3_to_center",
            return_value=(35.0, 135.0),
        ),
    ):
        response = await validate_h3(request=request, current_user=current_user)

    assert response.valid is True
    assert response.resolution == 7
    assert response.latitude == 35.0
    assert response.longitude == 135.0


@pytest.mark.asyncio
async def test_get_h3_from_coordinates_happy_path() -> None:
    """get_h3_from_coordinates returns H3 index and boundary (lines 88-95)."""
    from echoroo.api.v1.h3 import get_h3_from_coordinates
    from echoroo.schemas.site import H3FromCoordinatesRequest

    request = H3FromCoordinatesRequest(latitude=35.0, longitude=135.0, resolution=7)
    current_user = MagicMock()

    with (
        patch(
            "echoroo.api.v1.h3.h3_from_coordinates",
            return_value="87283082bffffff",
        ),
        patch(
            "echoroo.api.v1.h3.h3_to_center",
            return_value=(35.0, 135.0),
        ),
        patch(
            "echoroo.api.v1.h3.h3_to_boundary",
            return_value=[[35.0, 135.0]],
        ),
    ):
        response = await get_h3_from_coordinates(
            request=request, current_user=current_user
        )

    assert response.h3_index == "87283082bffffff"
    assert response.latitude == 35.0
    assert response.boundary == [[35.0, 135.0]]


@pytest.mark.asyncio
async def test_get_h3_from_coordinates_raises_400_on_value_error() -> None:
    """get_h3_from_coordinates raises 400 when ValueError raised (lines 102-103)."""
    from echoroo.api.v1.h3 import get_h3_from_coordinates
    from echoroo.schemas.site import H3FromCoordinatesRequest

    # Use valid schema values (validation happens at schema level already)
    # but make the service function raise ValueError
    request = H3FromCoordinatesRequest(latitude=35.0, longitude=0.0, resolution=7)
    current_user = MagicMock()

    with (
        patch(
            "echoroo.api.v1.h3.h3_from_coordinates",
            side_effect=ValueError("Latitude must be between -90 and 90"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_h3_from_coordinates(request=request, current_user=current_user)

    assert exc_info.value.status_code == 400
