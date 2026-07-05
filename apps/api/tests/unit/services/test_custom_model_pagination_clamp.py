"""Security unit tests: custom-model service clamps client-controlled limit.

W3-3: ``CustomModelService.list_models`` must clamp ``limit`` to
``MAX_PAGE_SIZE`` before delegating to the repository so a caller cannot force
an unbounded SQL query.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.core.pagination import MAX_PAGE_SIZE
from echoroo.services.custom_model import CustomModelService


def _service_with_mock_repo() -> tuple[CustomModelService, AsyncMock]:
    service = CustomModelService(MagicMock())
    repo_call = AsyncMock(return_value=([], 0))
    service._repo.list_for_project = repo_call  # type: ignore[method-assign]
    return service, repo_call


@pytest.mark.asyncio
async def test_list_models_clamps_oversized_limit() -> None:
    """An over-max limit is clamped to MAX_PAGE_SIZE before hitting the repo."""
    service, repo_call = _service_with_mock_repo()

    await service.list_models(uuid4(), limit=100000, offset=0)

    assert repo_call.call_args.kwargs["limit"] == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_list_models_preserves_normal_limit() -> None:
    """A normal limit below the max is passed through unchanged."""
    service, repo_call = _service_with_mock_repo()

    await service.list_models(uuid4(), limit=50, offset=0)

    assert repo_call.call_args.kwargs["limit"] == 50


@pytest.mark.asyncio
async def test_list_models_floors_negative_offset() -> None:
    """A negative offset is floored to 0 before hitting the repo."""
    service, repo_call = _service_with_mock_repo()

    await service.list_models(uuid4(), limit=50, offset=-10)

    assert repo_call.call_args.kwargs["offset"] == 0
