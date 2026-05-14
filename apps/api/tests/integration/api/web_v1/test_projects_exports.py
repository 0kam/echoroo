"""Spec/009 PR D0 coverage for project export BFF adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response, StreamingResponse

from echoroo.api.v1 import annotation_projects as legacy_annotation_projects
from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.api.web_v1.projects import _media
from echoroo.core.database import get_db
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import get_current_user
from echoroo.models.enums import ProjectVisibility
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected
from tests.integration.api.web_v1.test_projects_read_smoke import (
    _create_project,
    _create_user,
    _seed_refresh_token,
)


async def _fake_db() -> AsyncIterator[object]:
    yield object()


async def _noop_gate_action(**kwargs: object) -> object:
    return object()


def _build_app(user: object, audio_service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(_media.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_datasets.get_audio_service] = lambda: audio_service
    return app


@pytest.mark.asyncio
async def test_annotation_project_export_bff_delegates_response_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_project_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_export_annotations(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"format": kwargs["format"], "annotations": []}

    monkeypatch.setattr(
        legacy_annotation_projects,
        "export_annotations",
        fake_export_annotations,
    )
    monkeypatch.setattr(_media, "gate_action", _noop_gate_action)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(SimpleNamespace(id=uuid4()), object())),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/web-api/v1/projects/"
            f"{project_id}/annotation-projects/{annotation_project_id}/export",
            params={"format": "json"},
        )

    assert response.status_code == 200
    assert response.json() == {"format": "json", "annotations": []}
    assert captured["project_id"] == project_id
    assert captured["annotation_project_id"] == annotation_project_id
    assert captured["format"] == "json"


@pytest.mark.asyncio
async def test_annotation_project_export_bff_preserves_csv_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_project_id = uuid4()

    async def fake_export_annotations(**kwargs: object) -> Response:
        return Response(
            "Selection,Begin Time (s)\n1,0.0\n",
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=annotations.csv"},
        )

    monkeypatch.setattr(
        legacy_annotation_projects,
        "export_annotations",
        fake_export_annotations,
    )
    monkeypatch.setattr(_media, "gate_action", _noop_gate_action)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(SimpleNamespace(id=uuid4()), object())),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/web-api/v1/projects/"
            f"{project_id}/annotation-projects/{annotation_project_id}/export",
            params={"format": "csv"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("Selection,")


@pytest.mark.asyncio
async def test_dataset_export_bff_delegates_streaming_zip_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    dataset_id = uuid4()
    audio_service = object()
    captured: dict[str, object] = {}

    async def fake_export_dataset(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"PK\x03\x04"]),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="dataset_export.zip"'},
        )

    monkeypatch.setattr(legacy_datasets, "export_dataset", fake_export_dataset)
    monkeypatch.setattr(_media, "gate_action", _noop_gate_action)

    async with AsyncClient(
        transport=ASGITransport(
            app=_build_app(SimpleNamespace(id=uuid4()), audio_service)
        ),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export",
            params={"include_audio": "true"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert "attachment" in response.headers["content-disposition"]
    assert response.content == b"PK\x03\x04"
    assert captured["project_id"] == project_id
    assert captured["dataset_id"] == dataset_id
    assert captured["audio_service"] is audio_service
    assert captured["include_audio"] is True


def test_export_bff_paths_are_declared() -> None:
    paths = _build_app(SimpleNamespace(id=uuid4()), object()).openapi()["paths"]
    assert (
        "/web-api/v1/projects/{project_id}/annotation-projects/"
        "{annotation_project_id}/export"
        in paths
    )
    assert "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export" in paths


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/web-api/v1/projects/{project_id}/annotation-projects/"
        "{annotation_project_id}/export",
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export",
    ],
)
async def test_export_bff_rejects_api_key_bearer(
    client: AsyncClient,
    path: str,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "GET",
        path.format(
            project_id=uuid4(),
            annotation_project_id=uuid4(),
            dataset_id=uuid4(),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/web-api/v1/projects/{project_id}/annotation-projects/"
        "{annotation_project_id}/export",
        "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export",
    ],
)
async def test_export_restricted_non_member_returns_403_not_401(
    client: AsyncClient,
    db_session: AsyncSession,
    path: str,
) -> None:
    owner = await _create_user(db_session, email=f"d0-export-owner-{uuid4()}@example.com")
    outsider = await _create_user(
        db_session,
        email=f"d0-export-outsider-{uuid4()}@example.com",
    )
    project = await _create_project(
        db_session,
        owner,
        name="D0 Restricted Export",
        visibility=ProjectVisibility.RESTRICTED,
    )
    project.restricted_config = {
        **project.restricted_config,
        "allow_export": False,
    }
    await db_session.commit()

    refresh_token = await _seed_refresh_token(db_session, outsider)
    refresh = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert refresh.status_code == 200, refresh.text

    response = await client.get(
        path.format(
            project_id=project.id,
            annotation_project_id=uuid4(),
            dataset_id=uuid4(),
        ),
        headers={"Authorization": f"Bearer {refresh.json()['access_token']}"},
    )

    assert response.status_code == 403, response.text
