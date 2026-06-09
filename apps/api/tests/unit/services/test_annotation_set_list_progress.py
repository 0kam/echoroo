"""Unit tests for real per-set progress on the AnnotationSet LIST view.

``AnnotationSetService.list`` previously returned items without any progress
information, forcing the frontend to show a hardcoded placeholder. It now
populates ``AnnotationSetResponse.progress`` with real per-status segment
counts, computed via TWO grouped queries (per-status + is_empty) over all
listed set ids to avoid an N+1 query per row.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.services.annotation_set import AnnotationSetService


def _make_service() -> AnnotationSetService:
    set_repo = MagicMock()
    set_repo.db = MagicMock()
    segment_repo = MagicMock()
    return AnnotationSetService(set_repo=set_repo, segment_repo=segment_repo)


def _set_row(set_id) -> SimpleNamespace:
    """Minimal AnnotationSet-like row for ``model_validate`` (from_attributes)."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=set_id,
        project_id=uuid4(),
        dataset_id=uuid4(),
        created_by_id=uuid4(),
        name="Set A",
        filter_date_range=None,
        filter_time_of_day_range=None,
        segment_length_sec=10,
        num_segments=20,
        status="in_progress",
        sampling_warning=None,
        created_at=now,
        updated_at=now,
    )


def _execute_result(rows: list[tuple]) -> MagicMock:
    """Wrap rows so ``(await db.execute(...)).all()`` returns them."""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    return result


@pytest.mark.asyncio
async def test_list_populates_real_progress() -> None:
    """1 annotated of 20 → progress.annotated=1, progress.total=20."""
    service = _make_service()
    set_id = uuid4()

    # Repo returns one in_progress set with 20 segments.
    service.set_repo.list_by_project = AsyncMock(return_value=([_set_row(set_id)], 1))

    # Two grouped queries: per-status counts, then is_empty counts.
    status_rows = [
        (set_id, AnnotationSegmentStatus.ANNOTATED, 1),
        (set_id, AnnotationSegmentStatus.UNANNOTATED, 19),
    ]
    empty_rows: list[tuple] = []  # no empty segments
    service._db.execute = AsyncMock(
        side_effect=[
            _execute_result(status_rows),
            _execute_result(empty_rows),
        ]
    )

    response = await service.list(
        project_id=uuid4(),
        dataset_id=None,
        status_filter=None,
        page=1,
        page_size=20,
    )

    assert len(response.items) == 1
    progress = response.items[0].progress
    assert progress is not None
    assert progress.annotated == 1
    assert progress.unannotated == 19
    assert progress.skipped == 0
    assert progress.empty == 0
    # total = unannotated + annotated + skipped (matches _build_progress).
    assert progress.total == 20

    # N+1 guard: exactly TWO grouped queries regardless of set count.
    assert service._db.execute.await_count == 2


@pytest.mark.asyncio
async def test_list_empty_set_list_runs_no_progress_queries() -> None:
    """An empty result set short-circuits the grouped progress queries."""
    service = _make_service()
    service.set_repo.list_by_project = AsyncMock(return_value=([], 0))
    service._db.execute = AsyncMock()

    response = await service.list(
        project_id=uuid4(),
        dataset_id=None,
        status_filter=None,
        page=1,
        page_size=20,
    )

    assert response.items == []
    service._db.execute.assert_not_awaited()
