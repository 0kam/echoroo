"""Smoke coverage for spec/009 PR 3a upload-session BFF adapters.

PR 3a moves the upload-session orchestration endpoints from ``/api/v1``
to ``/web-api/v1``. The legacy handlers continue to own presigned URL
issuance, S3 bucket verification, Celery task dispatch, and per-file
status aggregation; the BFF layer only adds the cookie + CSRF gating
and re-uses :func:`gate_action` for the permission decision.

Both mutating endpoints attach a Redis-backed
:class:`fastapi_limiter.depends.RateLimiter` dependency, which would
otherwise reach for a live Redis connection during the smoke test. We
walk the router's :class:`APIRoute` instances and override each
``RateLimiter`` instance with a no-op via FastAPI's
``dependency_overrides`` table so the tests stay hermetic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi_limiter.depends import RateLimiter
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import uploads as legacy_uploads
from echoroo.api.web_v1.projects import _uploads as bff_uploads
from echoroo.core.actions import UPLOAD_CREATE_ACTION
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.schemas.upload import (
    CompleteUploadResponse,
    CreateUploadSessionResponse,
    UploadSessionStatusResponse,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_create_response(*, session_id: str) -> CreateUploadSessionResponse:
    return CreateUploadSessionResponse(
        session_id=session_id,
        status="issued",
        expires_at=datetime(2026, 5, 25, tzinfo=UTC),
        total_files=1,
        total_bytes=1024,
        files=[],
    )


def _fake_complete_response(*, session_id: str) -> CompleteUploadResponse:
    return CompleteUploadResponse(
        session_id=session_id,
        status="uploaded",
        verified_files=1,
        missing_files=0,
        mismatched_files=0,
    )


def _fake_status_response(*, session_id: str) -> UploadSessionStatusResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return UploadSessionStatusResponse(
        session_id=session_id,
        status="uploaded",
        total_files=1,
        total_bytes=1024,
        validated_files=0,
        imported_files=0,
        progress_percent=0.0,
        error=None,
        files=[],
        created_at=now,
        updated_at=now,
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


async def _noop_rate_limit() -> None:
    return None


def _build_app(*, user: object, service: object) -> FastAPI:
    """Build a minimal app with rate-limit deps overridden.

    Each ``RateLimiter`` instance baked into the BFF route signatures is
    mapped to :func:`_noop_rate_limit` so the smoke test stays hermetic
    (no Redis connection required).
    """
    app = FastAPI()
    app.include_router(bff_uploads.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_uploads.get_upload_service] = lambda: service
    # Override every ``RateLimiter`` Depends instance in the router so the
    # tests do not try to reach Redis. The dependency callable is the
    # ``RateLimiter`` instance itself (``__call__`` is async).
    for route in bff_uploads.router.routes:
        if not isinstance(route, APIRoute):
            continue
        for dep in route.dependant.dependencies:
            if isinstance(dep.call, RateLimiter):
                app.dependency_overrides[dep.call] = _noop_rate_limit
    return app


@pytest.mark.asyncio
async def test_upload_session_create_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    session_id = str(uuid4())
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> CreateUploadSessionResponse:
        captured.update(kwargs)
        return _fake_create_response(session_id=session_id)

    monkeypatch.setattr(legacy_uploads, "create_upload_session", fake_create)
    monkeypatch.setattr(
        bff_uploads, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions",
            json={"files": [{"filename": "rec.wav", "size": 1024}]},
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id
    payload = captured["request_body"]
    assert isinstance(payload, legacy_uploads.CreateUploadSessionRequest)
    assert payload.files[0].filename == "rec.wav"
    assert gate_captured["action"] is UPLOAD_CREATE_ACTION


@pytest.mark.asyncio
async def test_upload_session_complete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_complete(**kwargs: object) -> CompleteUploadResponse:
        captured.update(kwargs)
        return _fake_complete_response(session_id=str(session_id))

    monkeypatch.setattr(legacy_uploads, "complete_upload_session", fake_complete)
    monkeypatch.setattr(
        bff_uploads, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}/complete",
            json={},
        )

    assert response.status_code == 202, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id
    assert captured["session_id"] == session_id
    assert gate_captured["action"] is UPLOAD_CREATE_ACTION


@pytest.mark.asyncio
async def test_upload_session_status_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_status(**kwargs: object) -> UploadSessionStatusResponse:
        captured.update(kwargs)
        return _fake_status_response(session_id=str(session_id))

    monkeypatch.setattr(legacy_uploads, "get_upload_session_status", fake_status)

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id
    assert captured["session_id"] == session_id
    # Read endpoint: legacy delegates to service.access_check, no gate_action.


def test_upload_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    create_path = (
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions"
    )
    assert "post" in paths[create_path]

    session_root = f"{create_path}/{{session_id}}"
    assert "get" in paths[session_root]
    assert "post" in paths[f"{session_root}/complete"]


@pytest.mark.asyncio
async def test_upload_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    session_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions",
        body={"files": [{"filename": "rec.wav", "size": 1024}]},
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}/complete",
        body={},
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}",
    )
