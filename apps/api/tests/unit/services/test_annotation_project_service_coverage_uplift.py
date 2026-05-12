"""Coverage uplift unit tests for ``echoroo.services.annotation_project``.

Phase 17 §C Batch 9a (35-50pp gap range): covers AnnotationProjectService
methods so the module clears the 85% threshold.

Missing lines: 126-130,132,172,175,179,182,187,195,213-214,220,222,247-261,
              264-265,268,271-272,275,280,282,294-295,319-320,327-328,333,343-344,367,370
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.services.annotation_project import AnnotationProjectService


def _make_annotation_project_repo() -> MagicMock:
    repo = MagicMock()
    repo.db = MagicMock()
    repo.db.execute = AsyncMock()
    repo.list_by_project = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    return repo


def _make_annotation_task_repo() -> MagicMock:
    repo = MagicMock()
    repo.count_by_status_batch = AsyncMock(return_value={})
    repo.count_by_status = AsyncMock(return_value={})
    repo.create_batch = AsyncMock()
    return repo


def _make_ap(project_id: object = None) -> MagicMock:
    ap = MagicMock()
    ap.id = uuid4()
    ap.project_id = project_id or uuid4()
    ap.created_by_id = uuid4()
    ap.name = "Test AP"
    ap.description = "desc"
    ap.instructions = None
    ap.visibility = MagicMock(value="private")
    ap.created_at = None
    ap.updated_at = None
    ap.datasets = []
    ap.tags = []
    return ap


@pytest.mark.asyncio
async def test_list_projects_returns_paginated_response() -> None:
    """list_projects returns paginated AnnotationProjectListResponse (lines 126-132)."""
    ap = _make_ap()
    ap_repo = _make_annotation_project_repo()
    ap_repo.list_by_project = AsyncMock(return_value=([ap], 1))

    task_repo = _make_annotation_task_repo()
    task_repo.count_by_status_batch = AsyncMock(return_value={ap.id: {}})

    service = AnnotationProjectService(ap_repo, task_repo)

    fake_list_response = MagicMock()
    fake_list_response.total = 1
    mock_list_class = MagicMock(return_value=fake_list_response)

    with (
        patch(
            "echoroo.services.annotation_project.AnnotationProjectDetailResponse",
            return_value=MagicMock(),
        ),
        patch(
            "echoroo.services.annotation_project.AnnotationProjectListResponse",
            mock_list_class,
        ),
    ):
        result = await service.list_projects(uuid4(), page=1, page_size=10)

    assert result.total == 1


@pytest.mark.asyncio
async def test_create_annotation_project_returns_detail() -> None:
    """create() creates the project and returns detail response (lines 172-195)."""
    ap = _make_ap()
    ap_repo = _make_annotation_project_repo()
    ap_repo.create = AsyncMock(return_value=ap)

    task_repo = _make_annotation_task_repo()

    service = AnnotationProjectService(ap_repo, task_repo)

    request = MagicMock()
    request.name = "New AP"
    request.description = "desc"
    request.instructions = None
    request.visibility = MagicMock()
    request.dataset_ids = []
    request.tag_ids = []

    with patch(
        "echoroo.services.annotation_project.AnnotationProjectDetailResponse",
        return_value=MagicMock(),
    ):
        await service.create(uuid4(), uuid4(), request)

    ap_repo.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_annotation_project_with_datasets_and_tags() -> None:
    """create() resolves dataset_ids and tag_ids when provided (lines 179-187)."""
    ap = _make_ap()
    ap_repo = _make_annotation_project_repo()
    ap_repo.create = AsyncMock(return_value=ap)

    # Mock execute to return datasets and tags
    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = [MagicMock()]
    ap_repo.db.execute = AsyncMock(return_value=scalars_result)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    request = MagicMock()
    request.name = "New AP"
    request.description = "desc"
    request.instructions = None
    request.visibility = MagicMock()
    request.dataset_ids = [uuid4()]
    request.tag_ids = [uuid4()]

    with patch(
        "echoroo.services.annotation_project.AnnotationProjectDetailResponse",
        return_value=MagicMock(),
    ):
        await service.create(uuid4(), uuid4(), request)


@pytest.mark.asyncio
async def test_get_detail_raises_404_when_not_found() -> None:
    """get_detail raises 404 when annotation project not found (lines 213-214)."""
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=None)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.get_detail(uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_detail_returns_detail_when_found() -> None:
    """get_detail returns AnnotationProjectDetailResponse when found (lines 220-222)."""
    ap = _make_ap()
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=ap)

    task_repo = _make_annotation_task_repo()
    task_repo.count_by_status = AsyncMock(return_value={"completed": 5})

    service = AnnotationProjectService(ap_repo, task_repo)

    with patch(
        "echoroo.services.annotation_project.AnnotationProjectDetailResponse",
        return_value=MagicMock(),
    ):
        result = await service.get_detail(uuid4())

    assert result is not None


@pytest.mark.asyncio
async def test_update_raises_404_when_not_found() -> None:
    """update() raises 404 when annotation project not found (lines 247-248)."""
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=None)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.update(uuid4(), MagicMock())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_updates_scalar_fields() -> None:
    """update() updates scalar fields on the annotation project (lines 254-282)."""
    ap = _make_ap()
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=ap)
    ap_repo.update = AsyncMock(return_value=ap)

    scalars_result = MagicMock()
    scalars_result.scalars.return_value.all.return_value = []
    ap_repo.db.execute = AsyncMock(return_value=scalars_result)

    task_repo = _make_annotation_task_repo()
    task_repo.count_by_status = AsyncMock(return_value={})

    service = AnnotationProjectService(ap_repo, task_repo)

    request = MagicMock()
    request.name = "Updated AP"
    request.description = "new desc"
    request.instructions = "new instructions"
    request.visibility = MagicMock()
    request.dataset_ids = []
    request.tag_ids = []

    with patch(
        "echoroo.services.annotation_project.AnnotationProjectDetailResponse",
        return_value=MagicMock(),
    ):
        await service.update(uuid4(), request)

    assert ap.name == "Updated AP"
    assert ap.description == "new desc"


@pytest.mark.asyncio
async def test_delete_raises_404_when_not_found() -> None:
    """delete() raises 404 when annotation project not found (lines 319-320)."""
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=None)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.delete(uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_calls_repo_delete_when_found() -> None:
    """delete() calls repo.delete when annotation project exists (lines 327-328)."""
    ap = _make_ap()
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=ap)
    ap_repo.delete = AsyncMock()

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    await service.delete(ap.id)

    ap_repo.delete.assert_called_once_with(ap.id)


@pytest.mark.asyncio
async def test_generate_tasks_raises_404_when_not_found() -> None:
    """generate_tasks raises 404 when annotation project not found (lines 343-344)."""
    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=None)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    with pytest.raises(HTTPException) as exc_info:
        await service.generate_tasks(uuid4())

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_generate_tasks_returns_zero_when_no_datasets() -> None:
    """generate_tasks returns 0 when no datasets linked (lines 333,367,370)."""
    ap = _make_ap()
    ap.datasets = []

    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=ap)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    result = await service.generate_tasks(ap.id)

    assert "Tasks generated: 0" in result.message


@pytest.mark.asyncio
async def test_generate_tasks_returns_zero_when_no_clips_in_datasets() -> None:
    """generate_tasks returns 0 when datasets exist but no clips (lines 338-346)."""
    ap = _make_ap()
    dataset = MagicMock()
    dataset.id = uuid4()
    ap.datasets = [dataset]

    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=ap)

    # db.execute returns a result with no rows
    clips_result = MagicMock()
    clips_result.all.return_value = []
    ap_repo.db.execute = AsyncMock(return_value=clips_result)

    task_repo = _make_annotation_task_repo()
    service = AnnotationProjectService(ap_repo, task_repo)

    result = await service.generate_tasks(ap.id)

    assert "Tasks generated: 0" in result.message


@pytest.mark.asyncio
async def test_generate_tasks_creates_new_tasks_for_clips() -> None:
    """generate_tasks creates AnnotationTasks for new clips (lines 348-370)."""
    ap = _make_ap()
    dataset = MagicMock()
    dataset.id = uuid4()
    ap.datasets = [dataset]

    clip_id_1 = uuid4()
    clip_id_2 = uuid4()

    ap_repo = _make_annotation_project_repo()
    ap_repo.get_by_id = AsyncMock(return_value=ap)

    # First execute: returns clip rows; second execute: returns existing task rows (empty)
    clips_result = MagicMock()
    clips_result.all.return_value = [(clip_id_1,), (clip_id_2,)]
    existing_result = MagicMock()
    existing_result.all.return_value = []
    ap_repo.db.execute = AsyncMock(side_effect=[clips_result, existing_result])

    task_repo = _make_annotation_task_repo()
    task_repo.create_batch = AsyncMock()
    service = AnnotationProjectService(ap_repo, task_repo)

    result = await service.generate_tasks(ap.id)

    assert "Tasks generated: 2" in result.message
    task_repo.create_batch.assert_called_once()
