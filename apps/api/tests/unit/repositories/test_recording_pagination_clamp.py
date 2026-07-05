"""Security unit tests: recording repository clamps client page_size.

W3-3: ``RecordingRepository.list_by_dataset`` and ``search_by_project`` must
clamp ``page_size`` to ``MAX_PAGE_SIZE`` so a caller cannot force an unbounded
SQL query.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.core.pagination import MAX_PAGE_SIZE
from echoroo.repositories.recording import RecordingRepository


def _mock_db() -> tuple[MagicMock, MagicMock]:
    """Return a mock db whose two ``execute`` calls (count, main) succeed."""
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
    limit_value = getattr(main_query._limit_clause, "value", None)
    if limit_value is not None:
        return int(limit_value)
    params = main_query.compile().params
    return next((v for v in params.values() if isinstance(v, int)), None)


@pytest.mark.asyncio
async def test_list_by_dataset_clamps_oversized_page_size() -> None:
    """list_by_dataset clamps an over-max page_size to MAX_PAGE_SIZE."""
    db, execute_mock = _mock_db()
    repo = RecordingRepository(db)

    await repo.list_by_dataset(uuid4(), page=1, page_size=100000)

    assert _applied_limit(execute_mock) == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_list_by_dataset_preserves_normal_page_size() -> None:
    """list_by_dataset passes a normal page_size through unchanged."""
    db, execute_mock = _mock_db()
    repo = RecordingRepository(db)

    await repo.list_by_dataset(uuid4(), page=1, page_size=20)

    assert _applied_limit(execute_mock) == 20


@pytest.mark.asyncio
async def test_search_by_project_clamps_oversized_page_size() -> None:
    """search_by_project clamps an over-max page_size to MAX_PAGE_SIZE."""
    db, execute_mock = _mock_db()
    repo = RecordingRepository(db)

    await repo.search_by_project(uuid4(), page=1, page_size=100000)

    assert _applied_limit(execute_mock) == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_search_by_project_preserves_normal_page_size() -> None:
    """search_by_project passes a normal page_size through unchanged."""
    db, execute_mock = _mock_db()
    repo = RecordingRepository(db)

    await repo.search_by_project(uuid4(), page=1, page_size=20)

    assert _applied_limit(execute_mock) == 20
