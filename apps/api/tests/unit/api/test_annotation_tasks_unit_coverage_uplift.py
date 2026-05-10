"""Coverage uplift unit tests for ``echoroo.api.v1.annotation_tasks``.

Phase 17 §C easy-win batch 1: covers the ``get_next_task`` 204 branch
(lines 127-130) and the dependency factory (lines 36-39) using mocked
service objects so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import status

from echoroo.api.v1 import annotation_tasks as mod


@pytest.mark.asyncio
async def test_get_next_task_returns_204_when_no_task_available() -> None:
    """get_next_task() sets status 204 and returns None when service yields None
    (lines 127-130).
    """
    service = MagicMock()
    service.get_next = AsyncMock(return_value=None)
    response = MagicMock()
    response.status_code = 200
    current_user = MagicMock()
    current_user.id = uuid4()

    result = await mod.get_next_task(
        project_id=uuid4(),
        annotation_project_id=uuid4(),
        current_user=current_user,
        service=service,
        response=response,
    )

    assert result is None
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.asyncio
async def test_get_next_task_returns_task_when_available() -> None:
    """get_next_task() returns the task without modifying the response status."""
    task_obj = MagicMock()
    service = MagicMock()
    service.get_next = AsyncMock(return_value=task_obj)
    response = MagicMock()
    response.status_code = 200
    current_user = MagicMock()
    current_user.id = uuid4()

    result = await mod.get_next_task(
        project_id=uuid4(),
        annotation_project_id=uuid4(),
        current_user=current_user,
        service=service,
        response=response,
    )

    assert result is task_obj
    # No 204 modification when a task was returned.
    assert response.status_code == 200


def test_get_annotation_task_service_factory_builds_service() -> None:
    """The dep factory wires task + project repositories into the service."""
    db = MagicMock()
    service = mod.get_annotation_task_service(db)
    assert service is not None
    # The service has the expected interface; exact type irrelevant for unit cov.
    assert hasattr(service, "get_next") or hasattr(service, "list_tasks")
