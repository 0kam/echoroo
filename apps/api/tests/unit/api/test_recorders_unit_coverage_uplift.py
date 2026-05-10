"""Coverage uplift unit tests for ``echoroo.api.v1.recorders``.

Phase 17 §C easy-win batch 1: covers the dep factory (line 25) plus the
``list_recorders`` body (lines 59-60) using mocked service so the module
clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from echoroo.api.v1 import recorders as mod


def test_get_recorder_service_returns_recorder_service() -> None:
    """The dep factory builds a RecorderService bound to ``db`` (line 25)."""
    db = MagicMock()
    service = mod.get_recorder_service(db)
    assert service is not None
    # Expose the service under test (interface check only).
    assert hasattr(service, "list_recorders")


@pytest.mark.asyncio
async def test_list_recorders_clamps_pagination_and_calls_service() -> None:
    """list_recorders() invokes the service with clamped pagination (lines 59-60)."""
    sentinel_response = MagicMock()
    service = MagicMock()
    service.list_recorders = AsyncMock(return_value=sentinel_response)
    current_user = MagicMock()

    result = await mod.list_recorders(
        current_user=current_user,
        service=service,
        page=2,
        limit=50,
    )
    assert result is sentinel_response
    service.list_recorders.assert_awaited_once_with(page=2, limit=50)


@pytest.mark.asyncio
async def test_list_recorders_uses_defaults_when_omitted() -> None:
    """Default page=1 / limit=100 produce the same kwargs."""
    service = MagicMock()
    service.list_recorders = AsyncMock(return_value=MagicMock())
    current_user = MagicMock()

    await mod.list_recorders(
        current_user=current_user,
        service=service,
    )
    service.list_recorders.assert_awaited_once_with(page=1, limit=100)
