"""Coverage uplift unit tests for ``echoroo.api.v1.h3``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers validate_h3 and
get_h3_from_coordinates handlers so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1 import h3 as mod
from echoroo.schemas.site import (
    H3FromCoordinatesRequest,
    H3ValidationRequest,
)


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    return user


@pytest.mark.asyncio
async def test_validate_h3_returns_invalid_when_bad_index() -> None:
    """validate_h3 returns invalid response when index is invalid (lines 44-47)."""
    user = _make_user()
    request = H3ValidationRequest(h3_index="INVALID_H3")

    with patch.object(mod, "validate_h3_index", return_value=(False, None, "bad index")):
        result = await mod.validate_h3(request=request, current_user=user)

    assert result.valid is False
    assert result.resolution is None
    assert result.error == "bad index"


@pytest.mark.asyncio
async def test_validate_h3_returns_valid_with_center_when_good_index() -> None:
    """validate_h3 returns valid response with lat/lng when index is valid (lines 55-62)."""
    user = _make_user()
    request = H3ValidationRequest(h3_index="8928308280fffff")

    with (
        patch.object(mod, "validate_h3_index", return_value=(True, 9, None)),
        patch.object(mod, "h3_to_center", return_value=(35.68, 139.76)),
    ):
        result = await mod.validate_h3(request=request, current_user=user)

    assert result.valid is True
    assert result.resolution == 9
    assert result.latitude == 35.68
    assert result.longitude == 139.76
    assert result.error is None


@pytest.mark.asyncio
async def test_get_h3_from_coordinates_returns_h3_index() -> None:
    """get_h3_from_coordinates returns H3 index (lines 88-95)."""
    user = _make_user()
    request = H3FromCoordinatesRequest(latitude=35.68, longitude=139.76, resolution=9)
    expected_h3 = "8928308280fffff"

    with (
        patch.object(mod, "h3_from_coordinates", return_value=expected_h3),
        patch.object(mod, "h3_to_center", return_value=(35.68, 139.76)),
        patch.object(mod, "h3_to_boundary", return_value=[[35.0, 139.0], [36.0, 140.0]]),
    ):
        result = await mod.get_h3_from_coordinates(
            request=request, current_user=user
        )

    assert result.h3_index == expected_h3
    assert result.resolution == 9
    assert result.latitude == 35.68
    assert result.longitude == 139.76


@pytest.mark.asyncio
async def test_get_h3_from_coordinates_raises_400_on_value_error() -> None:
    """get_h3_from_coordinates raises 400 on ValueError from service (lines 102-103)."""
    user = _make_user()
    # Valid schema values but h3_from_coordinates raises ValueError at service level
    request = H3FromCoordinatesRequest(latitude=35.68, longitude=139.76, resolution=9)

    with (
        patch.object(mod, "h3_from_coordinates", side_effect=ValueError("resolution out of range")),
        pytest.raises(HTTPException) as exc_info,
    ):
        await mod.get_h3_from_coordinates(request=request, current_user=user)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "resolution out of range" in str(exc_info.value.detail)
