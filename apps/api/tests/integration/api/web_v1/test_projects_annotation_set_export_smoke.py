"""Smoke coverage for the annotation-set export BFF endpoints.

Covers ``GET /{project_id}/annotation-sets/{set_id}/export/csv`` and
``GET /{project_id}/annotation-sets/{set_id}/export/dataset`` in
``echoroo.api.web_v1.projects._annotation_set_export``.

Test strategy mirrors ``test_projects_detection_export_smoke.py``:
lightweight monkeypatch of service internals + gate_action so no live DB
or audio files are needed, while the endpoint handler code paths (gate,
existence check, project-scope guard, 413 size guard, streaming response)
all execute and are measured by coverage.
"""

from __future__ import annotations

import io
import os
import zipfile
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.web_v1.projects import _annotation_set_export as bff_export
from echoroo.core.actions import ANNOTATION_SET_GET_ACTION
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _make_denying_gate_action() -> Any:
    """Return a gate_action that raises a 403 PermissionError immediately."""
    from fastapi import HTTPException

    async def fake(**kwargs: object) -> object:
        raise HTTPException(status_code=403, detail="Forbidden")

    return fake


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(
        bff_export.router, prefix="/web-api/v1/projects"
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


async def _async_return(value: object) -> object:
    return value


# ---------------------------------------------------------------------------
# CSV export — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_csv_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 + text/csv + RFC 6266 Content-Disposition, header row present."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    gate_captured: dict[str, object] = {}

    # A minimal CSV body: header + one data row.
    csv_header = "deploymentID,mediaID,eventID,observationID,scientificName"
    csv_row = f"{project_id},{set_id},{uuid4()},{uuid4()},Parus major"
    csv_bytes = f"{csv_header}\r\n{csv_row}\r\n".encode()

    async def fake_csv_stream(
        *, project_id: UUID, set_id: UUID  # noqa: ARG001
    ) -> AsyncIterator[bytes]:
        yield csv_bytes

    # Stub gate_action so we can capture which Action constant was used.
    monkeypatch.setattr(
        bff_export,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )
    fake_set = SimpleNamespace(id=set_id, project_id=project_id, name="My Set")
    monkeypatch.setattr(
        bff_export.AnnotationSetExportService,
        "_require_set",
        lambda _self, _sid: _async_return(fake_set),
    )
    monkeypatch.setattr(
        bff_export.AnnotationSetExportService,
        "export_csv_stream",
        lambda _self, **kwargs: fake_csv_stream(**kwargs),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/csv"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    cd = response.headers["content-disposition"]
    assert "attachment" in cd
    assert str(set_id) in cd  # filename contains set_id
    body = response.content.decode()
    # Header row must NOT contain annotator_* columns.
    assert "annotator_" not in body
    # Must contain core CamtrapDP columns.
    assert "scientificName" in body
    assert "Parus major" in body
    # Gate was fired with the correct Action.
    assert gate_captured["action"] is ANNOTATION_SET_GET_ACTION


# ---------------------------------------------------------------------------
# CSV export — set not found (ValueError from _require_set → 404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_csv_set_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_require_set raising ValueError maps to HTTP 404."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_capturing_gate_action({}))

    async def _raise(_self: object, _sid: UUID) -> object:
        raise ValueError(f"not found: {_sid}")

    monkeypatch.setattr(bff_export.AnnotationSetExportService, "_require_set", _raise)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/csv"
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# CSV export — project_id mismatch → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_csv_wrong_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set belonging to a different project returns 404 (project-scope guard)."""
    project_id = uuid4()
    set_id = uuid4()
    other_project_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_capturing_gate_action({}))
    # The set belongs to *another* project.
    fake_set = SimpleNamespace(id=set_id, project_id=other_project_id, name="X")
    monkeypatch.setattr(
        bff_export.AnnotationSetExportService,
        "_require_set",
        lambda _self, _sid: _async_return(fake_set),
    )

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/csv"
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# CSV export — gate denial → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_csv_gate_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permission gate raising 403 is propagated directly."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_denying_gate_action())

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/csv"
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Dataset ZIP export — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_dataset_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 + application/zip + RFC 6266 Content-Disposition with filename*."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    gate_captured: dict[str, object] = {}
    set_name = "テストセット"

    monkeypatch.setattr(
        bff_export,
        "gate_action",
        _make_capturing_gate_action(gate_captured),
    )

    fake_set = SimpleNamespace(id=set_id, project_id=project_id, name=set_name)
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "_require_set",
        lambda _self, _sid: _async_return(fake_set),
    )

    # Segment count well below the 5000 guard.
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "count_finalized_segments",
        lambda _self, _sid: _async_return(3),
    )

    from echoroo.services.annotation_set_dataset_export import DatasetExportPlan

    fake_plan = DatasetExportPlan(annotations_csv="", segments=[])
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "prepare_plan",
        lambda _self, **_kwargs: _async_return(fake_plan),
    )

    # write_dataset_zip must produce an actual (empty) ZIP file on disk.
    def fake_write_zip(
        plan: object, audio_service: object, out_path: str  # noqa: ARG001
    ) -> None:
        with zipfile.ZipFile(out_path, "w") as zf:
            zf.writestr("annotations.csv", "deploymentID\r\n")
            zf.writestr("segments.csv", "segment_id\r\n")

    monkeypatch.setattr(bff_export, "write_dataset_zip", fake_write_zip)

    # Stub AudioService construction so no real settings are needed.
    fake_audio = SimpleNamespace()
    monkeypatch.setattr(bff_export, "_build_audio_service", lambda: fake_audio)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            "/export/dataset"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    cd = response.headers["content-disposition"]
    assert "attachment" in cd
    # RFC 6266: both ASCII fallback and UTF-8 percent-encoded forms present.
    assert "filename=" in cd
    assert "filename*=UTF-8''" in cd
    # The gate was fired with the correct Action.
    assert gate_captured["action"] is ANNOTATION_SET_GET_ACTION
    # Body is a valid ZIP.
    content = io.BytesIO(response.content)
    with zipfile.ZipFile(content) as zf:
        names = zf.namelist()
    assert "annotations.csv" in names
    assert "segments.csv" in names


# ---------------------------------------------------------------------------
# Dataset ZIP export — set not found → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_dataset_set_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_require_set raising ValueError → 404 for dataset endpoint."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_capturing_gate_action({}))

    async def _raise(_self: object, _sid: UUID) -> object:
        raise ValueError(f"not found: {_sid}")

    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService, "_require_set", _raise
    )
    monkeypatch.setattr(bff_export, "_build_audio_service", lambda: SimpleNamespace())

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            "/export/dataset"
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Dataset ZIP export — project_id mismatch → 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_dataset_wrong_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set belonging to a different project returns 404 for dataset endpoint."""
    project_id = uuid4()
    set_id = uuid4()
    other_project_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_capturing_gate_action({}))
    fake_set = SimpleNamespace(id=set_id, project_id=other_project_id, name="X")
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "_require_set",
        lambda _self, _sid: _async_return(fake_set),
    )
    monkeypatch.setattr(bff_export, "_build_audio_service", lambda: SimpleNamespace())

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            "/export/dataset"
        )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Dataset ZIP export — gate denial → 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_dataset_gate_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permission gate raising 403 is propagated for dataset endpoint."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_denying_gate_action())
    monkeypatch.setattr(bff_export, "_build_audio_service", lambda: SimpleNamespace())

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            "/export/dataset"
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Dataset ZIP export — _MAX_DATASET_SEGMENTS guard → 413
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_dataset_too_many_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exceeding _MAX_DATASET_SEGMENTS (5000) returns HTTP 413."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_capturing_gate_action({}))
    fake_set = SimpleNamespace(id=set_id, project_id=project_id, name="Big")
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "_require_set",
        lambda _self, _sid: _async_return(fake_set),
    )
    # Simulate more than _MAX_DATASET_SEGMENTS finalized segments.
    over_limit = bff_export._MAX_DATASET_SEGMENTS + 1
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "count_finalized_segments",
        lambda _self, _sid: _async_return(over_limit),
    )
    monkeypatch.setattr(bff_export, "_build_audio_service", lambda: SimpleNamespace())

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
            "/export/dataset"
        )

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert str(over_limit) in detail
    assert str(bff_export._MAX_DATASET_SEGMENTS) in detail


# ---------------------------------------------------------------------------
# Dataset ZIP export — write_dataset_zip raises → temp file cleaned up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_annotation_set_dataset_zip_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If write_dataset_zip raises, the error propagates and temp file removed."""
    project_id = uuid4()
    set_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    monkeypatch.setattr(bff_export, "gate_action", _make_capturing_gate_action({}))
    fake_set = SimpleNamespace(id=set_id, project_id=project_id, name="Test")
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "_require_set",
        lambda _self, _sid: _async_return(fake_set),
    )
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "count_finalized_segments",
        lambda _self, _sid: _async_return(1),
    )
    from echoroo.services.annotation_set_dataset_export import DatasetExportPlan

    fake_plan = DatasetExportPlan(annotations_csv="", segments=[])
    monkeypatch.setattr(
        bff_export.AnnotationSetDatasetExportService,
        "prepare_plan",
        lambda _self, **_kwargs: _async_return(fake_plan),
    )

    # Track the temp file path so we can check it's cleaned up.
    captured_paths: list[str] = []

    def _failing_write(
        plan: object, audio_service: object, out_path: str  # noqa: ARG001
    ) -> None:
        captured_paths.append(out_path)
        raise RuntimeError("Simulated build failure")

    monkeypatch.setattr(bff_export, "write_dataset_zip", _failing_write)
    monkeypatch.setattr(bff_export, "_build_audio_service", lambda: SimpleNamespace())

    app = _build_app(user=user)
    # ASGITransport propagates unhandled server exceptions as-is rather than
    # converting them to 500 responses (FastAPI's exception handler does that
    # in production). We therefore expect the RuntimeError to bubble up and
    # assert the temp file is cleaned up by the except-block in the endpoint.
    with pytest.raises(RuntimeError, match="Simulated build failure"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            await client.get(
                f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}"
                "/export/dataset"
            )

    # Temp file should have been deleted by the except-block cleanup.
    for path in captured_paths:
        assert not os.path.exists(path), f"Temp file leaked: {path}"


# ---------------------------------------------------------------------------
# OpenAPI declaration
# ---------------------------------------------------------------------------


def test_annotation_set_export_bff_paths_declared_in_openapi() -> None:
    """Both export paths appear in the OpenAPI schema."""
    app = _build_app(user=SimpleNamespace(id=uuid4()))
    paths = app.openapi()["paths"]
    assert "get" in paths[
        "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/csv"
    ]
    assert "get" in paths[
        "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/dataset"
    ]


# ---------------------------------------------------------------------------
# _build_content_disposition — unit coverage of the RFC 6266 helper
# ---------------------------------------------------------------------------


def test_build_content_disposition_ascii_name() -> None:
    """ASCII-only name stays as-is in the filename= field."""
    sid = uuid4()
    header = bff_export._build_content_disposition("MySet", sid)
    assert "MySet_dataset.zip" in header
    assert "filename*=UTF-8''" in header
    # Must be Latin-1 encodable (no raise means OK).
    header.encode("latin-1")


def test_build_content_disposition_double_underscore_name() -> None:
    """Name with consecutive underscores is collapsed by the while loop."""
    sid = uuid4()
    # Non-ASCII chars become underscores; consecutive ones are collapsed.
    # "A テスト B" → "A___B" → "A_B" after while-loop collapse.
    header = bff_export._build_content_disposition("A テスト B", sid)
    assert "A_B_dataset.zip" in header
    header.encode("latin-1")


def test_build_content_disposition_japanese_name() -> None:
    """Japanese name collapses to UUID in ASCII fallback; UTF-8 form preserved."""
    sid = uuid4()
    name = "テストセット"
    header = bff_export._build_content_disposition(name, sid)
    # ASCII fallback should be the UUID (no ASCII chars survive from the JP name).
    assert str(sid) in header
    # UTF-8 percent-encoded form must contain percent-encoded Japanese.
    assert "filename*=UTF-8''" in header
    assert "%" in header
    header.encode("latin-1")


def test_build_content_disposition_none_name() -> None:
    """None name uses UUID as both ASCII fallback and UTF-8 stem."""
    sid = uuid4()
    header = bff_export._build_content_disposition(None, sid)
    assert str(sid) in header
    header.encode("latin-1")


def test_build_content_disposition_mixed_ascii_name() -> None:
    """Mixed ASCII/non-ASCII name: ASCII chars kept, non-ASCII collapsed to _."""
    sid = uuid4()
    header = bff_export._build_content_disposition("My_Set-2026", sid)
    assert "My_Set-2026_dataset.zip" in header
    header.encode("latin-1")


# ---------------------------------------------------------------------------
# API-key cross-rejection sweep (D-2a #3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annotation_set_export_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    """Both export paths reject echoroo_* Bearer credentials with 401."""
    from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected

    project_id = uuid4()
    set_id = uuid4()
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/csv",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/export/dataset",
    )
