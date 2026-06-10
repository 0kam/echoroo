"""Unit tests for the project recording datetime re-parse endpoint.

``POST /web-api/v1/projects/{project_id}/recordings/reparse-datetimes`` is
gated by ``DATASET_DATETIME_APPLY_ACTION`` (MANAGE_DATASET_ADMIN) and
re-parses every recording's datetime for the dataset named in the body. The
dataset is validated to belong to the path project before dispatch.

These tests invoke the handler directly with mocked dependencies, mirroring
``tests/unit/api/test_web_v1_thin_adapters_coverage_uplift.py``:

* admin caller -> task dispatched, response carries task id + count, project
  audit emitted;
* dataset belonging to a different project -> 404 surfaced from the service;
* invalid body (bad timezone) -> Pydantic ValidationError.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from echoroo.api.web_v1.projects import _recordings as mod
from echoroo.schemas.recording import RecordingReparseDatetimesRequest


class _AsyncSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _request(headers: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    request.client = SimpleNamespace(host="203.0.113.9")
    return request


async def _noop_gate_action(**kwargs: object) -> object:
    return SimpleNamespace(id=kwargs.get("project_id"))


def _patch_audit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service = MagicMock()
    service.write_project_event = AsyncMock()
    monkeypatch.setattr(
        mod, "AsyncSessionLocal", lambda: _AsyncSessionContext(session)
    )
    monkeypatch.setattr(mod, "AuditLogService", MagicMock(return_value=service))
    return service


@pytest.mark.asyncio
async def test_reparse_admin_dispatches_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "gate_action", _noop_gate_action)
    audit_service = _patch_audit(monkeypatch)

    dataset_id = uuid4()
    project_id = uuid4()

    service = MagicMock()
    service.get_by_id = AsyncMock(return_value=MagicMock())
    service.apply_datetime_pattern = AsyncMock(return_value=("task-reparse-1", 17))

    db = MagicMock()
    db.commit = AsyncMock()
    user = SimpleNamespace(id=uuid4())

    body = RecordingReparseDatetimesRequest(
        dataset_id=dataset_id,
        pattern=r"(\d{8}_\d{6})",
        format="%Y%m%d_%H%M%S",
        timezone="Asia/Tokyo",
    )

    out = await mod.reparse_recording_datetimes(
        project_id=project_id,
        body=body,
        http_request=_request({"x-request-id": "req"}),
        current_user=user,
        service=service,
        db=db,
    )

    assert out.task_id == "task-reparse-1"
    assert out.total_recordings == 17
    service.get_by_id.assert_awaited_once_with(user.id, project_id, dataset_id)
    service.apply_datetime_pattern.assert_awaited_once_with(
        dataset_id, body.pattern, body.format, body.timezone
    )
    audit_service.write_project_event.assert_awaited_once()
    assert (
        audit_service.write_project_event.await_args.kwargs["action"]
        == "dataset.datetime_config.apply"
    )


@pytest.mark.asyncio
async def test_reparse_dataset_project_mismatch_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mod, "gate_action", _noop_gate_action)

    service = MagicMock()
    # ``get_by_id`` raises 404 when the dataset belongs to another project.
    service.get_by_id = AsyncMock(
        side_effect=HTTPException(status_code=404, detail="Dataset not found")
    )
    service.apply_datetime_pattern = AsyncMock()

    db = MagicMock()
    db.commit = AsyncMock()

    body = RecordingReparseDatetimesRequest(
        dataset_id=uuid4(),
        pattern=r"(\d{8})",
        format="%Y%m%d",
        timezone=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await mod.reparse_recording_datetimes(
            project_id=uuid4(),
            body=body,
            http_request=_request(),
            current_user=SimpleNamespace(id=uuid4()),
            service=service,
            db=db,
        )

    assert exc_info.value.status_code == 404
    # The task must never be dispatched on a mismatch.
    service.apply_datetime_pattern.assert_not_awaited()


def test_reparse_request_rejects_invalid_timezone() -> None:
    with pytest.raises(ValidationError):
        RecordingReparseDatetimesRequest(
            dataset_id=uuid4(),
            pattern=r"(\d{8})",
            format="%Y%m%d",
            timezone="Not/AZone",
        )


def test_reparse_request_allows_optional_timezone() -> None:
    req = RecordingReparseDatetimesRequest(
        dataset_id=uuid4(),
        pattern=r"(\d{8})",
        format="%Y%m%d",
    )
    assert req.timezone is None
