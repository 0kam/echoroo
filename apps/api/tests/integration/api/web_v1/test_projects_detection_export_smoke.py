"""Smoke coverage for spec/009 PR 4 detection export BFF adapters.

PR 4 moves the two ``/api/v1/projects/{pid}/detections/export/...``
streaming endpoints (CSV row-by-row, ZIP archive) to the cookie + CSRF
BFF surface. Tests assert:

* delegation: legacy handler is called with the right kwargs
  (including the optional filter Query args).
* gating: the canonical ``DETECTION_EXPORT_*_ACTION`` is captured for
  each endpoint.
* OpenAPI: every path is declared on the router.
* surface separation: every path rejects ``Authorization: Bearer
  echoroo_*`` (D-2a #3 / FR-006 mirror).
* streaming shape: the BFF returns the legacy ``StreamingResponse``
  unchanged so the ``Content-Disposition`` filename + media_type land
  exactly as the legacy declared.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import detections as legacy_detections
from echoroo.api.web_v1.projects import _detection_export as bff_detection_export
from echoroo.core.actions import (
    DETECTION_EXPORT_CSV_ACTION,
    DETECTION_EXPORT_ML_DATASET_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(
        bff_detection_export.router, prefix="/web-api/v1/projects"
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_csv_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    tag_id = uuid4()
    dataset_id = uuid4()
    detection_run_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_export_csv(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"a,b\n1,2\n"]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=detections.csv"},
        )

    monkeypatch.setattr(legacy_detections, "export_csv", fake_export_csv)
    monkeypatch.setattr(
        bff_detection_export,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/detections/export/csv"
            f"?status=unreviewed&tag_id={tag_id}&dataset_id={dataset_id}"
            f"&detection_run_id={detection_run_id}"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "detections.csv" in response.headers["content-disposition"]
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["tag_id"] == tag_id
    assert captured["dataset_id"] == dataset_id
    assert captured["detection_run_id"] == detection_run_id
    assert gate_captured["action"] is DETECTION_EXPORT_CSV_ACTION


# ---------------------------------------------------------------------------
# ML-dataset export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_ml_dataset_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_export_ml(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"PK\x03\x04"]),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=ml-dataset.zip"
            },
        )

    monkeypatch.setattr(legacy_detections, "export_ml_dataset", fake_export_ml)
    monkeypatch.setattr(
        bff_detection_export,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/detections/export/ml-dataset"
            f"?dataset_id={dataset_id}"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    assert "ml-dataset.zip" in response.headers["content-disposition"]
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["dataset_id"] == dataset_id
    assert captured["detection_run_id"] is None
    assert gate_captured["action"] is DETECTION_EXPORT_ML_DATASET_ACTION


# ---------------------------------------------------------------------------
# OpenAPI declaration
# ---------------------------------------------------------------------------


def test_detection_export_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()))
    paths = app.openapi()["paths"]
    assert "get" in paths[
        "/web-api/v1/projects/{project_id}/detections/export/csv"
    ]
    assert "get" in paths[
        "/web-api/v1/projects/{project_id}/detections/export/ml-dataset"
    ]


# ---------------------------------------------------------------------------
# API-key cross-rejection sweep (D-2a #3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detection_export_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/detections/export/csv",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/detections/export/ml-dataset",
    )
