"""Smoke coverage for spec/009 PR 4 recorder BFF adapter.

PR 4 moves the public ``GET /api/v1/recorders`` surface to
``/web-api/v1/recorders``. The single BFF handler is a thin adapter
that re-uses the legacy ``RecorderServiceDep`` and delegates to the
legacy ``list_recorders`` handler. Tests assert:

* delegation: legacy handler is called with the right kwargs (page,
  limit, current_user, service).
* surface separation: the path rejects ``Authorization: Bearer
  echoroo_*`` (D-2a #3 / FR-006 mirror).
* OpenAPI: the path is declared on the router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import recorders as legacy_recorders
from echoroo.api.web_v1 import _recorders as bff_recorders
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.schemas.recorder import RecorderListResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _build_app(*, user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_recorders.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_recorders.get_recorder_service] = (
        lambda: service
    )
    return app


@pytest.mark.asyncio
async def test_list_recorders_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_list_recorders(**kwargs: object) -> RecorderListResponse:
        captured.update(kwargs)
        return RecorderListResponse(items=[], total=0, page=1, limit=100)

    monkeypatch.setattr(legacy_recorders, "list_recorders", fake_list_recorders)

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/recorders?page=2&limit=50")

    assert response.status_code == 200, response.text
    assert captured["current_user"] is user
    assert captured["service"] is service
    assert captured["page"] == 2
    assert captured["limit"] == 50


def test_recorders_bff_path_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]
    assert "get" in paths["/web-api/v1/recorders"]


@pytest.mark.asyncio
async def test_recorders_bff_path_rejects_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(client, "GET", "/web-api/v1/recorders")
