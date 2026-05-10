"""Coverage uplift unit tests for ``echoroo.repositories.search_session``.

Phase 17 §C easy-win batch 1: covers the only public method
:py:meth:`SearchSessionRepository.exists_in_project` (lines 20, 26) using
an :class:`unittest.mock.AsyncMock` session so the module clears the 85%
threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.repositories.search_session import SearchSessionRepository


@pytest.mark.asyncio
async def test_exists_in_project_returns_true_when_row_present() -> None:
    """exists_in_project() returns True when the SQL returns a non-None scalar."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = uuid4()
    db.execute = AsyncMock(return_value=result)

    repo = SearchSessionRepository(db)
    assert await repo.exists_in_project(uuid4(), uuid4()) is True
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_exists_in_project_returns_false_when_no_row() -> None:
    """exists_in_project() returns False when the scalar is None."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    repo = SearchSessionRepository(db)
    assert await repo.exists_in_project(uuid4(), uuid4()) is False
