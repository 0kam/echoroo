"""Security unit tests: clip repository clamps client-controlled page_size.

W3-3: ``ClipRepository.list_by_recording`` must clamp ``page_size`` to
``MAX_PAGE_SIZE`` so a caller cannot force an unbounded SQL query, regardless
of the entry point (v1 helper, BFF delegate, or internal call).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.core.pagination import MAX_PAGE_SIZE
from echoroo.repositories.clip import ClipRepository


def _mock_db() -> tuple[MagicMock, MagicMock]:
    """Return a mock db whose two ``execute`` calls (count, main) succeed.

    The second call's query object is what we inspect for the applied LIMIT.
    """
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    main_result = MagicMock()
    main_result.scalars.return_value.all.return_value = []

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[count_result, main_result])
    return db, db.execute


def _applied_limit(execute_mock: MagicMock) -> int | None:
    """Extract the LIMIT bind value from the main (second) query."""
    main_query = execute_mock.call_args_list[1].args[0]
    params = main_query.compile().params
    # The LIMIT parameter is emitted as a bound param; its value is the clamp.
    limit_value = getattr(main_query._limit_clause, "value", None)
    if limit_value is not None:
        return int(limit_value)
    # Fallback: the limit is among the compiled params.
    return next((v for v in params.values() if isinstance(v, int)), None)


@pytest.mark.asyncio
async def test_list_by_recording_clamps_oversized_page_size() -> None:
    """An over-max page_size is clamped to MAX_PAGE_SIZE in the SQL LIMIT."""
    db, execute_mock = _mock_db()
    repo = ClipRepository(db)

    await repo.list_by_recording(uuid4(), page=1, page_size=99999)

    assert _applied_limit(execute_mock) == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_list_by_recording_preserves_normal_page_size() -> None:
    """A normal page_size below the max is passed through unchanged."""
    db, execute_mock = _mock_db()
    repo = ClipRepository(db)

    await repo.list_by_recording(uuid4(), page=1, page_size=50)

    assert _applied_limit(execute_mock) == 50
