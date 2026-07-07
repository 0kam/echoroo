"""Smoke coverage for spec/009 PR 2 project write BFF adapters.

PR 2 migrates the dataset / detection / detection-run / recording write
surface from ``/api/v1`` to ``/web-api/v1``. The legacy handlers continue
to own service orchestration; the BFF layer only adds the cookie + CSRF
gating and re-uses :func:`gate_action` for the permission decision.

These tests follow the same pattern as
:mod:`test_projects_recordings_media` and :mod:`test_projects_exports`:
build a minimal FastAPI app with the BFF router mounted, override the
legacy handler with a capture-style fake, and assert the BFF (1) routes
the call through to the legacy handler with the right arguments, (2)
preserves the legacy response shape, and (3) declares each path in the
OpenAPI schema so downstream contract diff suites detect drift.

The fakes return fully-formed Pydantic instances (one builder per
response model) so FastAPI's ``response_model`` validation passes
without forcing each per-endpoint fake to know the exact schema shape
inline.

Spec/009 §D-2a contract checks (CSRF / API-key cross-rejection / 403 vs
401 / audit actor_kind == session) are exercised at the integration
boundary by the existing helpers in :mod:`_helpers` and the per-PR
broader fixtures; this module focuses on the BFF→legacy wiring contract.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.api.v1 import detection_runs as legacy_detection_runs
from echoroo.api.v1 import detections as legacy_detections
from echoroo.api.v1 import recordings as legacy_recordings
from echoroo.api.web_v1.projects import (
    _datasets as bff_datasets,
)
from echoroo.api.web_v1.projects import (
    _detection_runs as bff_detection_runs,
)
from echoroo.api.web_v1.projects import (
    _detections as bff_detections,
)
from echoroo.api.web_v1.projects import (
    _recordings as bff_recordings,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DetectionRunStatus,
    DetectionRunType,
    DetectionSource,
    DetectionStatus,
)
from echoroo.schemas.dataset import (
    DatasetDetailResponse,
    DatetimeApplyResponse,
    DatetimeAutoDetectResponse,
    ImportStatusResponse,
)
from echoroo.schemas.detection import DetectionResponse
from echoroo.schemas.detection_run import DetectionRunResponse
from echoroo.schemas.recording import RecordingDetailResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected

# ---------------------------------------------------------------------------
# Response-model builders.
# ---------------------------------------------------------------------------


def _fake_detection_run_response(
    *, project_id: UUID, dataset_id: UUID | None
) -> DetectionRunResponse:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    return DetectionRunResponse(
        id=uuid4(),
        project_id=project_id,
        dataset_id=dataset_id,
        model_name="birdnet",
        model_version="2.4",
        parameters=None,
        run_type=DetectionRunType.DETECTION,
        status=DetectionRunStatus.PENDING,
        annotation_count=0,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _fake_detection_response(
    *, recording_id: UUID, tag_id: UUID | None
) -> DetectionResponse:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    return DetectionResponse(
        id=uuid4(),
        recording_id=recording_id,
        tag_id=tag_id,
        detection_run_id=None,
        source=DetectionSource.HUMAN,
        status=DetectionStatus.UNREVIEWED,
        confidence=None,
        start_time=0.0,
        end_time=1.0,
        freq_low=None,
        freq_high=None,
        reviewed_by_id=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
        tag=None,
    )


def _fake_recording_detail_response(
    *, recording_id: UUID, dataset_id: UUID
) -> RecordingDetailResponse:
    from echoroo.models.enums import DatetimeParseStatus

    now = datetime(2026, 5, 23, tzinfo=UTC)
    return RecordingDetailResponse(
        id=recording_id,
        dataset_id=dataset_id,
        filename="fake.wav",
        path=f"recordings/{dataset_id}/{recording_id}.wav",
        hash="fakehash",
        duration=1.0,
        samplerate=48_000,
        channels=1,
        bit_depth=16,
        datetime=now,
        datetime_parse_status=DatetimeParseStatus.SUCCESS,
        datetime_parse_error=None,
        time_expansion=1.0,
        note=None,
        created_at=now,
        updated_at=now,
        dataset=None,
        site=None,
        clip_count=0,
        effective_duration=1.0,
        is_ultrasonic=False,
    )


def _fake_dataset_detail_response(
    *, project_id: UUID, dataset_id: UUID, user_id: UUID
) -> DatasetDetailResponse:
    now = datetime(2026, 5, 23, tzinfo=UTC)
    return DatasetDetailResponse(
        id=dataset_id,
        project_id=project_id,
        site_id=uuid4(),
        recorder_id=None,
        license_id=None,
        created_by_id=user_id,
        name="fake-dataset",
        description=None,
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.PENDING,
        doi=None,
        gain=None,
        note=None,
        datetime_timezone=None,
        total_files=0,
        processed_files=0,
        processing_error=None,
        created_at=now,
        updated_at=now,
        site=None,
        recorder=None,
        license=None,
        created_by=None,
        recording_count=0,
        total_duration=0.0,
        start_date=None,
        end_date=None,
    )


def _fake_import_status_response() -> ImportStatusResponse:
    return ImportStatusResponse(
        status=DatasetStatus.PROCESSING,
        total_files=0,
        processed_files=0,
        progress_percent=0.0,
        error=None,
    )


# ---------------------------------------------------------------------------
# Test app + utilities.
# ---------------------------------------------------------------------------


async def _fake_db() -> AsyncIterator[object]:
    yield object()


async def _noop_gate_action(**_kwargs: object) -> object:
    return object()


def _build_app(
    *,
    bff_module: ModuleType,
    legacy_service_dep: Any,
    user: object,
    service: object,
) -> FastAPI:
    """Build a minimal FastAPI app with one BFF router mounted."""
    app = FastAPI()
    app.include_router(bff_module.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_service_dep] = lambda: service
    return app


# ---------------------------------------------------------------------------
# detection-runs: create / retry / cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_run_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_create_detection_run(**kwargs: object) -> DetectionRunResponse:
        captured.update(kwargs)
        return _fake_detection_run_response(
            project_id=project_id, dataset_id=dataset_id
        )

    monkeypatch.setattr(
        legacy_detection_runs,
        "create_detection_run",
        fake_create_detection_run,
    )
    monkeypatch.setattr(bff_detection_runs, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_detection_runs,
        legacy_service_dep=legacy_detection_runs.get_detection_run_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/detection-runs",
            json={
                "dataset_id": str(dataset_id),
                "model_name": "birdnet",
                "model_version": "2.4",
                "embedding_only": False,
            },
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    payload = captured["request"]
    assert isinstance(payload, legacy_detection_runs.DetectionRunCreate)
    assert payload.dataset_id == dataset_id
    assert payload.model_name == "birdnet"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path_suffix", "legacy_name"),
    [
        ("retry", "retry_detection_run"),
        ("cancel", "cancel_detection_run"),
    ],
)
async def test_detection_run_lifecycle_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    legacy_name: str,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_action(**kwargs: object) -> DetectionRunResponse:
        captured.update(kwargs)
        return _fake_detection_run_response(project_id=project_id, dataset_id=None)

    monkeypatch.setattr(legacy_detection_runs, legacy_name, fake_action)
    monkeypatch.setattr(bff_detection_runs, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_detection_runs,
        legacy_service_dep=legacy_detection_runs.get_detection_run_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/detection-runs/{run_id}/{path_suffix}",
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["run_id"] == run_id
    assert captured["current_user"] is user
    assert captured["service"] is service


def test_detection_run_write_paths_declared_in_openapi() -> None:
    app = _build_app(
        bff_module=bff_detection_runs,
        legacy_service_dep=legacy_detection_runs.get_detection_run_service,
        user=SimpleNamespace(id=uuid4()),
        service=object(),
    )
    paths = app.openapi()["paths"]
    assert "/web-api/v1/projects/{project_id}/detection-runs" in paths
    assert "post" in paths["/web-api/v1/projects/{project_id}/detection-runs"]
    assert (
        "/web-api/v1/projects/{project_id}/detection-runs/{run_id}/retry" in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/detection-runs/{run_id}/cancel" in paths
    )


@pytest.mark.asyncio
async def test_detection_run_write_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    run_id = uuid4()
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/detection-runs",
        body={
            "dataset_id": str(uuid4()),
            "model_name": "birdnet",
            "model_version": "2.4",
        },
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/detection-runs/{run_id}/retry",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/detection-runs/{run_id}/cancel",
    )


# ---------------------------------------------------------------------------
# detections: create + change-species
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_create_detection(**kwargs: object) -> DetectionResponse:
        captured.update(kwargs)
        return _fake_detection_response(recording_id=recording_id, tag_id=tag_id)

    monkeypatch.setattr(legacy_detections, "create_detection", fake_create_detection)
    monkeypatch.setattr(bff_detections, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_detections,
        legacy_service_dep=legacy_detections.get_detection_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/detections",
            json={
                "recording_id": str(recording_id),
                "tag_id": str(tag_id),
                "source": "human",
                "start_time": 0.0,
                "end_time": 3.0,
                "freq_low": 0,
                "freq_high": 24000,
            },
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    payload = captured["request"]
    assert isinstance(payload, legacy_detections.DetectionCreate)
    assert payload.recording_id == recording_id
    assert payload.tag_id == tag_id


@pytest.mark.asyncio
async def test_detection_change_species_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    detection_id = uuid4()
    recording_id = uuid4()
    new_tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_change_species(**kwargs: object) -> DetectionResponse:
        captured.update(kwargs)
        return _fake_detection_response(recording_id=recording_id, tag_id=new_tag_id)

    monkeypatch.setattr(legacy_detections, "change_species", fake_change_species)
    monkeypatch.setattr(bff_detections, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_detections,
        legacy_service_dep=legacy_detections.get_detection_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/detections/{detection_id}/change-species",
            json={"new_tag_id": str(new_tag_id)},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["detection_id"] == detection_id
    payload = captured["request"]
    assert isinstance(payload, legacy_detections.ChangeSpeciesRequest)


def test_detection_write_paths_declared_in_openapi() -> None:
    app = _build_app(
        bff_module=bff_detections,
        legacy_service_dep=legacy_detections.get_detection_service,
        user=SimpleNamespace(id=uuid4()),
        service=object(),
    )
    paths = app.openapi()["paths"]
    assert "post" in paths["/web-api/v1/projects/{project_id}/detections"]
    assert (
        "/web-api/v1/projects/{project_id}/detections/{detection_id}/change-species"
        in paths
    )


@pytest.mark.asyncio
async def test_detection_write_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    detection_id = uuid4()
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/detections",
        body={
            "recording_id": str(uuid4()),
            "tag_id": str(uuid4()),
            "start_time": 0.0,
            "end_time": 1.0,
            "freq_low": 0,
            "freq_high": 24000,
        },
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/detections/{detection_id}/change-species",
        body={"new_tag_id": str(uuid4())},
    )


# ---------------------------------------------------------------------------
# recordings: PATCH / DELETE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recording_update_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_update_recording(**kwargs: object) -> RecordingDetailResponse:
        captured.update(kwargs)
        return _fake_recording_detail_response(
            recording_id=recording_id, dataset_id=dataset_id
        )

    monkeypatch.setattr(legacy_recordings, "update_recording", fake_update_recording)
    monkeypatch.setattr(bff_recordings, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_recordings,
        legacy_service_dep=legacy_recordings.get_recording_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}",
            json={"note": "patched"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    assert captured["current_user"] is user
    assert captured["service"] is service


@pytest.mark.asyncio
async def test_recording_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_delete_recording(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_recordings, "delete_recording", fake_delete_recording)
    monkeypatch.setattr(bff_recordings, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_recordings,
        legacy_service_dep=legacy_recordings.get_recording_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}",
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    assert captured["current_user"] is user
    assert captured["service"] is service


def test_recording_write_paths_declared_in_openapi() -> None:
    app = _build_app(
        bff_module=bff_recordings,
        legacy_service_dep=legacy_recordings.get_recording_service,
        user=SimpleNamespace(id=uuid4()),
        service=object(),
    )
    paths = app.openapi()["paths"]
    methods = paths["/web-api/v1/projects/{project_id}/recordings/{recording_id}"]
    assert "patch" in methods
    assert "delete" in methods


@pytest.mark.asyncio
async def test_recording_write_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}",
        body={"note": "x"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}",
    )


# ---------------------------------------------------------------------------
# datasets: write surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dataset_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_create_dataset(**kwargs: object) -> DatasetDetailResponse:
        captured.update(kwargs)
        return _fake_dataset_detail_response(
            project_id=project_id, dataset_id=dataset_id, user_id=user.id
        )

    monkeypatch.setattr(legacy_datasets, "create_dataset", fake_create_dataset)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets",
            json={
                "site_id": str(uuid4()),
                "name": "smoke-create",
                "visibility": "public",
            },
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id


@pytest.mark.asyncio
async def test_dataset_update_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_update_dataset(**kwargs: object) -> DatasetDetailResponse:
        captured.update(kwargs)
        return _fake_dataset_detail_response(
            project_id=project_id, dataset_id=dataset_id, user_id=user.id
        )

    monkeypatch.setattr(legacy_datasets, "update_dataset", fake_update_dataset)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}",
            json={"name": "smoke-update"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_dataset_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_delete_dataset(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_datasets, "delete_dataset", fake_delete_dataset)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}",
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_dataset_start_import_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_start_import(**kwargs: object) -> ImportStatusResponse:
        captured.update(kwargs)
        return _fake_import_status_response()

    monkeypatch.setattr(legacy_datasets, "start_import", fake_start_import)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import",
            json={},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_dataset_get_import_status_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_get_import_status(**kwargs: object) -> ImportStatusResponse:
        captured.update(kwargs)
        return _fake_import_status_response()

    monkeypatch.setattr(legacy_datasets, "get_import_status", fake_get_import_status)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import-status",
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_dataset_auto_detect_datetime_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_auto_detect(**kwargs: object) -> DatetimeAutoDetectResponse:
        captured.update(kwargs)
        return DatetimeAutoDetectResponse(
            detected=False,
            pattern=None,
            format_str=None,
            preset_name=None,
            results=[],
        )

    monkeypatch.setattr(legacy_datasets, "auto_detect_datetime", fake_auto_detect)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/auto-detect",
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_dataset_test_datetime_pattern_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_test(**kwargs: object) -> list:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(legacy_datasets, "test_datetime_pattern", fake_test)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/test",
            json={"pattern": "yyyy", "format_str": "%Y", "timezone": None},
        )

    assert response.status_code == 200, response.text
    assert response.json() == []
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


@pytest.mark.asyncio
async def test_dataset_apply_datetime_pattern_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_apply(**kwargs: object) -> DatetimeApplyResponse:
        captured.update(kwargs)
        return DatetimeApplyResponse(task_id="task-1", total_recordings=0)

    monkeypatch.setattr(legacy_datasets, "apply_datetime_pattern", fake_apply)
    monkeypatch.setattr(bff_datasets, "gate_action", _noop_gate_action)

    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=user,
        service=service,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/apply",
            json={"pattern": "yyyy", "format_str": "%Y", "timezone": None},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id


def test_dataset_write_paths_declared_in_openapi() -> None:
    app = _build_app(
        bff_module=bff_datasets,
        legacy_service_dep=legacy_datasets.get_dataset_service,
        user=SimpleNamespace(id=uuid4()),
        service=object(),
    )
    paths = app.openapi()["paths"]
    assert "post" in paths["/web-api/v1/projects/{project_id}/datasets"]
    dataset_path = "/web-api/v1/projects/{project_id}/datasets/{dataset_id}"
    assert "patch" in paths[dataset_path]
    assert "delete" in paths[dataset_path]
    assert (
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import" in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import-status"
        in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/auto-detect"
        in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/test"
        in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/apply"
        in paths
    )


@pytest.mark.asyncio
async def test_dataset_write_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/datasets",
        body={"site_id": str(uuid4()), "name": "x", "visibility": "public"},
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}",
        body={"name": "y"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import",
        body={},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import-status",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/apply",
        body={"pattern": "yyyy", "format_str": "%Y", "timezone": None},
    )
