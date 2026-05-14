"""Coverage uplift tests for thin Web v1 adapter modules."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

from echoroo.api.web_v1 import detection_runs as global_detection_runs
from echoroo.api.web_v1.projects import (
    _annotation_projects,
    _annotation_tasks,
    _audit,
    _datasets,
    _detection_runs,
    _detections,
    _media,
)


def _request(headers: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    request.client = SimpleNamespace(host="203.0.113.9")
    return request


async def _noop_gate_action(**kwargs: object) -> object:
    return SimpleNamespace(id=kwargs.get("project_id"))


@pytest.mark.asyncio
async def test_global_available_models_requires_authenticated_user() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await global_detection_runs.get_available_models(current_user=None)

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_global_available_models_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    sentinel = object()
    fake_list = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(
        global_detection_runs.legacy_detection_runs,
        "list_available_models",
        fake_list,
    )

    result = await global_detection_runs.get_available_models(current_user=user)

    assert result is sentinel
    fake_list.assert_awaited_once_with(current_user=user)


@pytest.mark.asyncio
async def test_annotation_project_bff_adapters_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_annotation_projects, "gate_action", _noop_gate_action)

    project_id = uuid4()
    annotation_project_id = uuid4()
    request = _request()
    user = SimpleNamespace(id=uuid4())
    service = object()
    db = object()
    payload = object()
    sentinel = object()

    legacy = _annotation_projects.legacy_annotation_projects
    monkeypatch.setattr(legacy, "list_annotation_projects", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "create_annotation_project", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "get_annotation_project", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "update_annotation_project", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "delete_annotation_project", AsyncMock(return_value=None))
    monkeypatch.setattr(legacy, "generate_tasks", AsyncMock(return_value=sentinel))

    assert (
        await _annotation_projects.list_annotation_projects(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            page=2,
            page_size=3,
        )
        is sentinel
    )
    assert (
        await _annotation_projects.create_annotation_project(
            project_id=project_id,
            request=payload,
            http_request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    assert (
        await _annotation_projects.get_annotation_project(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    assert (
        await _annotation_projects.update_annotation_project(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            request=payload,
            http_request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    await _annotation_projects.delete_annotation_project(
        project_id=project_id,
        annotation_project_id=annotation_project_id,
        request=request,
        current_user=user,
        service=service,
        db=db,
    )
    assert (
        await _annotation_projects.generate_tasks(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )


@pytest.mark.asyncio
async def test_annotation_task_bff_adapters_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_annotation_tasks, "gate_action", _noop_gate_action)

    project_id = uuid4()
    annotation_project_id = uuid4()
    task_id = uuid4()
    request = _request()
    response = Response()
    user = SimpleNamespace(id=uuid4())
    service = object()
    db = object()
    payload = object()
    sentinel = object()

    legacy = _annotation_tasks.legacy_annotation_tasks
    monkeypatch.setattr(legacy, "list_tasks", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "get_next_task", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "get_task", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "update_task", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "complete_task", AsyncMock(return_value=sentinel))

    assert (
        await _annotation_tasks.list_tasks(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            page=2,
            page_size=4,
        )
        is sentinel
    )
    assert (
        await _annotation_tasks.get_next_task(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            request=request,
            current_user=user,
            service=service,
            response=response,
            db=db,
        )
        is sentinel
    )
    assert (
        await _annotation_tasks.get_task(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            task_id=task_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    assert (
        await _annotation_tasks.update_task(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            task_id=task_id,
            request=payload,
            http_request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    assert (
        await _annotation_tasks.complete_task(
            project_id=project_id,
            annotation_project_id=annotation_project_id,
            task_id=task_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )


@pytest.mark.asyncio
async def test_dataset_bff_adapters_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_datasets, "gate_action", _noop_gate_action)

    project_id = uuid4()
    dataset_id = uuid4()
    request = _request()
    user = SimpleNamespace(id=uuid4())
    service = object()
    db = object()
    sentinel = object()

    legacy = _datasets.legacy_datasets
    monkeypatch.setattr(legacy, "list_datasets", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "get_dataset", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "get_dataset_statistics", AsyncMock(return_value=sentinel))
    monkeypatch.setattr(legacy, "get_datetime_config", AsyncMock(return_value=sentinel))

    assert (
        await _datasets.list_datasets(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            page=2,
            page_size=4,
            search="frog",
        )
        is sentinel
    )
    assert (
        await _datasets.get_dataset(
            project_id=project_id,
            dataset_id=dataset_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    assert (
        await _datasets.get_dataset_statistics(
            project_id=project_id,
            dataset_id=dataset_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )
    assert (
        await _datasets.get_datetime_config(
            project_id=project_id,
            dataset_id=dataset_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
        is sentinel
    )


@pytest.mark.asyncio
async def test_project_detection_run_and_detection_bff_adapters_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_detection_runs, "gate_action", _noop_gate_action)
    monkeypatch.setattr(_detections, "gate_action", _noop_gate_action)

    project_id = uuid4()
    request = _request()
    user = SimpleNamespace(id=uuid4())
    service = object()
    db = object()
    sentinel = object()

    monkeypatch.setattr(
        _detection_runs.legacy_detection_runs,
        "list_detection_runs",
        AsyncMock(return_value=sentinel),
    )
    monkeypatch.setattr(
        _detections.legacy_detections,
        "list_detections",
        AsyncMock(return_value=sentinel),
    )
    monkeypatch.setattr(
        _detections.legacy_detections,
        "get_species_summary",
        AsyncMock(return_value=sentinel),
    )
    monkeypatch.setattr(
        _detections.legacy_detections,
        "get_temporal_data",
        AsyncMock(return_value=sentinel),
    )

    assert (
        await _detection_runs.list_detection_runs(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            page=2,
            page_size=4,
        )
        is sentinel
    )
    assert (
        await _detections.list_detections(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            confidence_min=0.2,
            confidence_max=0.9,
            locale="ja",
        )
        is sentinel
    )
    assert (
        await _detections.get_species_summary(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            locale="ja",
        )
        is sentinel
    )
    assert (
        await _detections.get_temporal_data(
            project_id=project_id,
            request=request,
            current_user=user,
            service=service,
            db=db,
            locale="ja",
        )
        is sentinel
    )


@pytest.mark.asyncio
async def test_media_recording_detail_adapter_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_media, "gate_action", _noop_gate_action)

    sentinel = object()
    fake_get_recording = AsyncMock(return_value=sentinel)
    monkeypatch.setattr(_media.legacy_recordings, "get_recording", fake_get_recording)

    project_id = uuid4()
    recording_id = uuid4()
    request = _request()
    user = SimpleNamespace(id=uuid4())
    service = object()
    db = object()

    result = await _media.get_recording(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        current_user=user,
        service=service,
        db=db,
    )

    assert result is sentinel
    fake_get_recording.assert_awaited_once()


class _AsyncSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def test_audit_request_helpers_cover_header_fallbacks() -> None:
    assert _audit._client_ip(_request({"x-forwarded-for": "198.51.100.1, 198.51.100.2"})) == (
        "198.51.100.1"
    )
    assert _audit._client_ip(_request({"x-forwarded-for": ""})) == "203.0.113.9"
    no_client = _request()
    no_client.client = None
    assert _audit._client_ip(no_client) == "unknown"
    assert _audit._user_agent(_request({"user-agent": "ua"})) == "ua"
    assert _audit._user_agent(_request()) == ""
    assert _audit._request_id(_request({"x-request-id": "req-1"})) == "req-1"
    assert _audit._request_id(_request()) == ""


@pytest.mark.asyncio
async def test_project_audit_soft_success_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success_session = MagicMock()
    success_session.commit = AsyncMock()
    success_session.rollback = AsyncMock()
    success_service = MagicMock()
    success_service.write_project_event = AsyncMock()

    monkeypatch.setattr(
        _audit.database,
        "AsyncSessionLocal",
        lambda: _AsyncSessionContext(success_session),
    )
    monkeypatch.setattr(_audit, "AuditLogService", MagicMock(return_value=success_service))

    await _audit.write_project_bff_audit_soft(
        actor_user_id=uuid4(),
        project_id=uuid4(),
        action="project.test",
        request=_request({"x-request-id": "req", "user-agent": "ua"}),
    )

    success_service.write_project_event.assert_awaited_once()
    success_session.commit.assert_awaited_once()
    success_session.rollback.assert_not_awaited()

    failing_session = MagicMock()
    failing_session.commit = AsyncMock()
    failing_session.rollback = AsyncMock()
    failing_service = MagicMock()
    failing_service.write_project_event = AsyncMock(side_effect=RuntimeError("down"))
    monkeypatch.setattr(
        _audit.database,
        "AsyncSessionLocal",
        lambda: _AsyncSessionContext(failing_session),
    )
    monkeypatch.setattr(_audit, "AuditLogService", MagicMock(return_value=failing_service))

    await _audit.write_project_bff_audit_soft(
        actor_user_id=uuid4(),
        project_id=uuid4(),
        action="project.test",
        request=_request(),
    )

    failing_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_platform_audit_soft_success_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    success_session = MagicMock()
    success_session.commit = AsyncMock()
    success_session.rollback = AsyncMock()
    success_service = MagicMock()
    success_service.write_platform_event = AsyncMock()

    monkeypatch.setattr(
        _audit.database,
        "AsyncSessionLocal",
        lambda: _AsyncSessionContext(success_session),
    )
    monkeypatch.setattr(_audit, "AuditLogService", MagicMock(return_value=success_service))

    await _audit.write_platform_bff_audit_soft(
        actor_user_id=uuid4(),
        action="platform.test",
        request=_request({"x-request-id": "req", "user-agent": "ua"}),
    )

    success_service.write_platform_event.assert_awaited_once()
    success_session.commit.assert_awaited_once()
    success_session.rollback.assert_not_awaited()

    failing_session = MagicMock()
    failing_session.commit = AsyncMock()
    failing_session.rollback = AsyncMock()
    failing_service = MagicMock()
    failing_service.write_platform_event = AsyncMock(side_effect=RuntimeError("down"))
    monkeypatch.setattr(
        _audit.database,
        "AsyncSessionLocal",
        lambda: _AsyncSessionContext(failing_session),
    )
    monkeypatch.setattr(_audit, "AuditLogService", MagicMock(return_value=failing_service))

    await _audit.write_platform_bff_audit_soft(
        actor_user_id=uuid4(),
        action="platform.test",
        request=_request(),
    )

    failing_session.rollback.assert_awaited_once()
