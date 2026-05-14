"""Spec/009 PR D0 coverage for project recording media BFF adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from echoroo.api.v1 import recordings as legacy_recordings
from echoroo.api.web_v1.projects import _media
from echoroo.core.actions import RECORDING_MEDIA_ACTION
from echoroo.core.auth import verify_media_token
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


def _build_app(user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(_media.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_recordings.get_recording_service] = lambda: service
    return app


@pytest.mark.asyncio
async def test_recording_audio_bff_delegates_range_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_stream_audio(**kwargs: object) -> Response:
        captured.update(kwargs)
        return Response(
            b"abcd",
            status_code=206,
            media_type="audio/wav",
            headers={"Content-Range": "bytes 0-3/10"},
        )

    monkeypatch.setattr(legacy_recordings, "stream_audio", fake_stream_audio)
    monkeypatch.setattr(_media, "gate_action", _noop_gate_action)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(user, service)),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/audio",
            headers={"Range": "bytes=0-3"},
            params={"speed": "1.25", "start": "0.5", "end": "1.5"},
        )

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-3/10"
    assert response.headers["content-type"].startswith("audio/wav")
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    assert captured["range"] == "bytes=0-3"
    assert captured["speed"] == 1.25
    assert captured["start"] == 0.5
    assert captured["end"] == 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path_suffix", "legacy_name", "expected_media_type"),
    [
        ("playback", "get_playback_audio", "audio/wav"),
        ("spectrogram", "get_spectrogram", "image/png"),
    ],
)
async def test_recording_media_bff_routes_delegate_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
    path_suffix: str,
    legacy_name: str,
    expected_media_type: str,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_legacy(**kwargs: object) -> Response:
        captured.update(kwargs)
        return Response(b"ok", media_type=expected_media_type)

    monkeypatch.setattr(legacy_recordings, legacy_name, fake_legacy)
    monkeypatch.setattr(_media, "gate_action", _noop_gate_action)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(SimpleNamespace(id=uuid4()), object())),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/{path_suffix}",
            headers={"Range": "bytes=10-"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(expected_media_type)
    assert captured["project_id"] == project_id
    assert captured["recording_id"] == recording_id
    if path_suffix == "playback":
        assert captured["range"] == "bytes=10-"


@pytest.mark.asyncio
async def test_recording_media_token_bff_gates_and_issues_scoped_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    user = SimpleNamespace(id=uuid4(), security_stamp="media-bff-stamp")

    class _Service:
        async def get_by_id_in_project(self, rid: object, pid: object) -> object:
            return SimpleNamespace(id=rid, project_id=pid)

    service = _Service()
    captured: dict[str, object] = {}

    async def fake_gate_action(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(_media, "gate_action", fake_gate_action)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(user, service)),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/media-token",
            json={"scope": "spectrogram"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] > 0
    assert captured["action"] == RECORDING_MEDIA_ACTION
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user

    claims = verify_media_token(
        body["token"],
        current_security_stamp=user.security_stamp,
        project_id=project_id,
        recording_id=recording_id,
        scope="spectrogram",
    )
    assert claims.user_id == user.id


def test_recording_media_bff_paths_are_declared() -> None:
    app = _build_app(SimpleNamespace(id=uuid4()), object())
    paths = app.openapi()["paths"]
    assert (
        "/web-api/v1/projects/{project_id}/recordings/{recording_id}/audio"
        in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback"
        in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram"
        in paths
    )
    assert (
        "/web-api/v1/projects/{project_id}/recordings/{recording_id}/media-token"
        in paths
    )


@pytest.mark.asyncio
async def test_recording_audio_bff_rejects_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{uuid4()}/recordings/{uuid4()}/audio",
    )


@pytest.mark.asyncio
async def test_recording_audio_restricted_non_member_returns_403_not_401(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(db_session, email="d0-media-owner@example.com")
    outsider = await _create_user(db_session, email="d0-media-outsider@example.com")
    project = await _create_project(
        db_session,
        owner,
        name="D0 Restricted Media",
        visibility=ProjectVisibility.RESTRICTED,
    )
    project.restricted_config = {
        **project.restricted_config,
        "allow_media_playback": False,
    }
    await db_session.commit()

    refresh_token = await _seed_refresh_token(db_session, outsider)
    refresh = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert refresh.status_code == 200, refresh.text

    response = await client.get(
        f"/web-api/v1/projects/{project.id}/recordings/{uuid4()}/audio",
        headers={"Authorization": f"Bearer {refresh.json()['access_token']}"},
    )

    assert response.status_code == 403, response.text
