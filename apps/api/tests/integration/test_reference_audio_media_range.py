"""HTTP Range coverage for search-session reference audio."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1.search import deps as search_deps
from echoroo.api.web_v1.projects import _search
from echoroo.core import storage
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user


async def _fake_db() -> AsyncIterator[object]:
    yield object()


@pytest.mark.asyncio
async def test_reference_audio_range_responses(
    storage_root, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    key = f"search_reference/{project_id}/{uuid4()}/source.wav"
    payload = b"0123456789"
    storage.write_bytes(key, payload)

    class _SessionService:
        async def get_session(self, requested_id: object, requested_project: object):
            assert requested_id == session_id
            assert requested_project == project_id
            return SimpleNamespace(reference_audio_keys=[key])

    async def _allow(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(_search, "gate_action", _allow)
    monkeypatch.setattr("echoroo.core.permissions.gate_action", _allow)

    app = FastAPI()
    app.include_router(_search.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    app.dependency_overrides[search_deps.get_authorized_session_service] = (
        lambda: _SessionService()
    )

    url = (
        f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        "/reference-audio/0"
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        whole = await client.get(url)
        partial = await client.get(url, headers={"Range": "bytes=2-5"})
        suffix = await client.get(url, headers={"Range": "bytes=-3"})
        unsatisfiable = await client.get(url, headers={"Range": "bytes=10-"})

    assert whole.status_code == 200
    assert whole.content == payload
    assert whole.headers["content-length"] == "10"
    assert whole.headers["accept-ranges"] == "bytes"

    assert partial.status_code == 206
    assert partial.content == b"2345"
    assert partial.headers["content-range"] == "bytes 2-5/10"
    assert partial.headers["content-length"] == "4"

    assert suffix.status_code == 206
    assert suffix.content == b"789"
    assert suffix.headers["content-range"] == "bytes 7-9/10"

    assert unsatisfiable.status_code == 416
    assert unsatisfiable.headers["content-range"] == "bytes */10"
