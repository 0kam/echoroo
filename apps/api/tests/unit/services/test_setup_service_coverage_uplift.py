"""Coverage uplift unit tests for ``echoroo.services.setup``.

Phase 17 §C medium-gap batch: targets ``_raise_phase4_stub`` (lines 20-23)
and ``initialize_setup`` (lines 75-76) so the module clears the 85%
threshold without touching production code. Also exercises the
``__init__`` path (line 35-36) and ``get_setup_status`` happy path (lines
51, 54) for completeness.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status

from echoroo.schemas.setup import SetupInitializeRequest
from echoroo.services.setup import SetupService, _raise_phase4_stub


def test_raise_phase4_stub_raises_501() -> None:
    """_raise_phase4_stub() always raises 501 (lines 20-23)."""
    with pytest.raises(HTTPException) as exc_info:
        _raise_phase4_stub()
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED
    assert "Phase 4" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_initialize_setup_raises_phase4_stub() -> None:
    """initialize_setup() raises the Phase 4 stub regardless of input (lines 75-76)."""
    db = MagicMock()
    service = SetupService(db)
    request = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!",
        display_name="Admin",
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.initialize_setup(request)
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_get_setup_status_no_users_no_completion_returns_required() -> None:
    """get_setup_status returns setup_required=True when DB is empty (lines 51, 54)."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    service = SetupService(db)
    # Patch the system_repo method directly to avoid DB calls.
    service.system_repo.is_setup_completed = AsyncMock(return_value=False)  # type: ignore[method-assign]

    status_resp = await service.get_setup_status()
    assert status_resp.setup_required is True
    assert status_resp.setup_completed is False


@pytest.mark.asyncio
async def test_get_setup_status_completed_returns_not_required() -> None:
    """get_setup_status returns setup_required=False when setup_completed."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    service = SetupService(db)
    service.system_repo.is_setup_completed = AsyncMock(return_value=True)  # type: ignore[method-assign]

    status_resp = await service.get_setup_status()
    assert status_resp.setup_required is False
    assert status_resp.setup_completed is True
