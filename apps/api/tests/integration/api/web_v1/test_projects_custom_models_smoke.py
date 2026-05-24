"""Smoke coverage for spec/009 PR 3b custom-model BFF adapters.

PR 3b moves the entire custom-SVM-classifier surface from ``/api/v1``
to ``/web-api/v1``. Each BFF handler is a thin adapter that re-uses
:func:`gate_action` and delegates to the legacy handler. Tests assert:

* delegation: legacy handler is called with the right kwargs.
* gating: the canonical ``CUSTOM_MODEL_*_ACTION`` is captured for each
  endpoint.
* OpenAPI: every path is declared on the router.
* surface separation: every path rejects ``Authorization: Bearer
  echoroo_*`` (D-2a #3 / FR-006 mirror).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import custom_models as legacy_custom_models
from echoroo.api.web_v1.projects import _custom_models as bff_custom_models
from echoroo.core.actions import (
    CUSTOM_MODEL_DELETE_ACTION,
    CUSTOM_MODEL_GET_ACTION,
    CUSTOM_MODEL_LIST_ACTION,
    CUSTOM_MODEL_TRAIN_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.custom_model import CustomModelStatus
from echoroo.models.enums import DetectionRunStatus
from echoroo.schemas.custom_model import (
    CustomModelApplyResponse,
    CustomModelDetectionRunListResponse,
    CustomModelListResponse,
    CustomModelResponse,
)
from echoroo.schemas.sampling import (
    SamplingRoundListResponse,
    SamplingRoundResponse,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_custom_model_response(
    *, project_id: UUID, model_id: UUID
) -> CustomModelResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return CustomModelResponse(
        id=model_id,
        project_id=project_id,
        user_id=uuid4(),
        name="fake-model",
        description=None,
        target_tag_id=uuid4(),
        model_type="svm",
        status=CustomModelStatus.DRAFT,
        training_config=None,
        hyperparameters=None,
        metrics=None,
        training_stats=None,
        model_artifact_key=None,
        embedding_model_name="perch",
        error_message=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
        search_session_id=None,
        dataset_id=None,
    )


def _fake_sampling_round_response(
    *, custom_model_id: UUID, round_id: UUID | None = None
) -> SamplingRoundResponse:
    return SamplingRoundResponse(
        id=round_id or uuid4(),
        custom_model_id=custom_model_id,
        round_number=1,
        round_type="seed",
        sampling_config=None,
        sample_count=0,
        status="pending",
        job_id=None,
        error_message=None,
        created_at=datetime(2026, 5, 24, tzinfo=UTC),
        completed_at=None,
        score_distribution=None,
        items=[],
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_custom_models.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_custom_models.get_custom_model_service] = (
        lambda: service
    )
    return app


# ---------------------------------------------------------------------------
# Delegation + gate_action capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_custom_models_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list(**kwargs: object) -> CustomModelListResponse:
        captured.update(kwargs)
        return CustomModelListResponse(models=[], total=0)

    monkeypatch.setattr(legacy_custom_models, "list_custom_models", fake_list)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"/web-api/v1/projects/{project_id}/custom-models")

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    assert gate_captured["action"] is CUSTOM_MODEL_LIST_ACTION


@pytest.mark.asyncio
async def test_create_custom_model_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    target_tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> CustomModelResponse:
        captured.update(kwargs)
        return _fake_custom_model_response(project_id=project_id, model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "create_custom_model", fake_create)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/custom-models",
            json={"name": "m1", "target_tag_id": str(target_tag_id)},
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    payload = captured["request_body"]
    assert isinstance(payload, legacy_custom_models.CustomModelCreate)
    assert payload.name == "m1"
    assert payload.target_tag_id == target_tag_id
    assert gate_captured["action"] is CUSTOM_MODEL_TRAIN_ACTION


@pytest.mark.asyncio
async def test_get_custom_model_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get(**kwargs: object) -> CustomModelResponse:
        captured.update(kwargs)
        return _fake_custom_model_response(project_id=project_id, model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "get_custom_model", fake_get)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert gate_captured["action"] is CUSTOM_MODEL_GET_ACTION


@pytest.mark.asyncio
async def test_update_custom_model_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> CustomModelResponse:
        captured.update(kwargs)
        return _fake_custom_model_response(project_id=project_id, model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "update_custom_model", fake_update)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}",
            json={"name": "renamed"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    payload = captured["request_body"]
    assert isinstance(payload, legacy_custom_models.CustomModelUpdate)
    assert payload.name == "renamed"
    assert gate_captured["action"] is CUSTOM_MODEL_TRAIN_ACTION


@pytest.mark.asyncio
async def test_delete_custom_model_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(legacy_custom_models, "delete_custom_model", fake_delete)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert gate_captured["action"] is CUSTOM_MODEL_DELETE_ACTION


@pytest.mark.asyncio
async def test_train_custom_model_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_train(**kwargs: object) -> CustomModelResponse:
        captured.update(kwargs)
        return _fake_custom_model_response(project_id=project_id, model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "train_custom_model", fake_train)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/train",
            json={"use_unlabeled": False, "max_unlabeled_samples": 100},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    payload = captured["request_body"]
    assert isinstance(payload, legacy_custom_models.CustomModelTrainRequest)
    assert payload.use_unlabeled is False
    assert payload.max_unlabeled_samples == 100
    assert gate_captured["action"] is CUSTOM_MODEL_TRAIN_ACTION


@pytest.mark.asyncio
async def test_get_custom_model_status_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_status(**kwargs: object) -> CustomModelResponse:
        captured.update(kwargs)
        return _fake_custom_model_response(project_id=project_id, model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "get_custom_model_status", fake_status)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/status"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert gate_captured["action"] is CUSTOM_MODEL_GET_ACTION


@pytest.mark.asyncio
async def test_apply_custom_model_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    dataset_id = uuid4()
    detection_run_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_apply(**kwargs: object) -> CustomModelApplyResponse:
        captured.update(kwargs)
        return CustomModelApplyResponse(
            detection_run_id=detection_run_id,
            status=DetectionRunStatus.PENDING,
        )

    monkeypatch.setattr(legacy_custom_models, "apply_custom_model", fake_apply)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/apply"
            f"?dataset_id={dataset_id}&threshold=0.75"
        )

    assert response.status_code == 202, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert captured["dataset_id"] == dataset_id
    assert captured["threshold"] == pytest.approx(0.75)
    assert gate_captured["action"] is CUSTOM_MODEL_TRAIN_ACTION


@pytest.mark.asyncio
async def test_list_detection_runs_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list_runs(**kwargs: object) -> CustomModelDetectionRunListResponse:
        captured.update(kwargs)
        return CustomModelDetectionRunListResponse(runs=[], total=0)

    monkeypatch.setattr(
        legacy_custom_models, "list_custom_model_detection_runs", fake_list_runs
    )
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}"
            "/detection-runs?limit=3"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert captured["limit"] == 3
    assert gate_captured["action"] is CUSTOM_MODEL_GET_ACTION


@pytest.mark.asyncio
async def test_create_seed_samples_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    search_session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_seed(**kwargs: object) -> SamplingRoundResponse:
        captured.update(kwargs)
        return _fake_sampling_round_response(custom_model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "create_seed_samples", fake_seed)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/seed-samples",
            json={"search_session_id": str(search_session_id)},
        )

    assert response.status_code == 202, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    payload = captured["body"]
    assert isinstance(payload, legacy_custom_models.SeedSamplingBody)
    assert payload.search_session_id == search_session_id
    assert gate_captured["action"] is CUSTOM_MODEL_TRAIN_ACTION


@pytest.mark.asyncio
async def test_suggest_next_samples_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_suggest(**kwargs: object) -> SamplingRoundResponse:
        captured.update(kwargs)
        return _fake_sampling_round_response(custom_model_id=model_id)

    monkeypatch.setattr(legacy_custom_models, "suggest_next_samples", fake_suggest)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/suggest-samples",
            json={},
        )

    assert response.status_code == 202, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert gate_captured["action"] is CUSTOM_MODEL_TRAIN_ACTION


@pytest.mark.asyncio
async def test_list_sampling_rounds_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list_rounds(**kwargs: object) -> SamplingRoundListResponse:
        captured.update(kwargs)
        return SamplingRoundListResponse(rounds=[], total=0)

    monkeypatch.setattr(legacy_custom_models, "list_sampling_rounds", fake_list_rounds)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/sampling-rounds"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert gate_captured["action"] is CUSTOM_MODEL_GET_ACTION


@pytest.mark.asyncio
async def test_get_sampling_round_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    round_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_round(**kwargs: object) -> SamplingRoundResponse:
        captured.update(kwargs)
        return _fake_sampling_round_response(
            custom_model_id=model_id, round_id=round_id
        )

    monkeypatch.setattr(legacy_custom_models, "get_sampling_round", fake_get_round)
    monkeypatch.setattr(
        bff_custom_models, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/custom-models/{model_id}"
            f"/sampling-rounds/{round_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["model_id"] == model_id
    assert captured["round_id"] == round_id
    assert gate_captured["action"] is CUSTOM_MODEL_GET_ACTION


# ---------------------------------------------------------------------------
# OpenAPI surface declaration
# ---------------------------------------------------------------------------


def test_custom_model_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    list_path = "/web-api/v1/projects/{project_id}/custom-models"
    assert "get" in paths[list_path]
    assert "post" in paths[list_path]

    detail_path = (
        "/web-api/v1/projects/{project_id}/custom-models/{model_id}"
    )
    assert "get" in paths[detail_path]
    assert "patch" in paths[detail_path]
    assert "delete" in paths[detail_path]

    assert "post" in paths[f"{detail_path}/train"]
    assert "get" in paths[f"{detail_path}/status"]
    assert "post" in paths[f"{detail_path}/apply"]
    assert "get" in paths[f"{detail_path}/detection-runs"]
    assert "post" in paths[f"{detail_path}/seed-samples"]
    assert "post" in paths[f"{detail_path}/suggest-samples"]
    assert "get" in paths[f"{detail_path}/sampling-rounds"]
    assert "get" in paths[f"{detail_path}/sampling-rounds/{{round_id}}"]


# ---------------------------------------------------------------------------
# API-key cross-rejection sweep (D-2a #3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_custom_model_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    model_id = uuid4()
    round_id = uuid4()
    dataset_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/custom-models",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/custom-models",
        body={"name": "m", "target_tag_id": str(uuid4())},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}",
        body={"name": "x"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/train",
        body={},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/status",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/apply"
        f"?dataset_id={dataset_id}&threshold=0.5",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/detection-runs",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/seed-samples",
        body={"search_session_id": str(uuid4())},
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/suggest-samples",
        body={},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}/sampling-rounds",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/custom-models/{model_id}"
        f"/sampling-rounds/{round_id}",
    )
