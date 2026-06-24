"""Smoke coverage for the users API-token BFF adapters (W2-2 C).

W2-2 routes the self-scoped API-token endpoints through the
``/web-api/v1`` BFF surface (cookie + CSRF), each delegating verbatim to
the legacy :mod:`echoroo.api.v1.users` handler:

* ``GET    /web-api/v1/users/me/api-tokens``             → ``list_api_tokens``
* ``POST   /web-api/v1/users/me/api-tokens``             → ``create_api_token`` (201)
* ``DELETE /web-api/v1/users/me/api-tokens/{token_id}``  → ``revoke_api_token`` (204)

HONESTY NOTE: the ``*_bff_delegates_to_legacy`` tests **monkeypatch** the
legacy handler and assert on the kwargs the BFF forwards + the status code
the adapter declares. They verify the transport wiring, NOT real DB-backed
delegation — in particular the legacy handler owns its own ``db.commit``
(on create / revoke), the one-time plain-token reveal, and the 404 on a
missing token; the BFF adds NO extra ``db.commit`` and no response
translation. These routes are self-scoped (no ``project_id``) so there is
no ``gate_action`` to assert.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import users as legacy_users
from echoroo.api.web_v1 import users as bff_users
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.schemas.token import (
    APITokenCreateRequest,
    APITokenCreateResponse,
    APITokenResponse,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _fake_token_response(*, name: str) -> APITokenResponse:
    return APITokenResponse(
        id=uuid4(),
        name=name,
        last_used_at=None,
        expires_at=None,
        is_active=True,
        created_at=datetime.now(UTC),
    )


def _fake_token_create_response(*, name: str, token: str) -> APITokenCreateResponse:
    base = _fake_token_response(name=name).model_dump()
    return APITokenCreateResponse(**base, token=token)


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_users.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_list_api_tokens_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}

    async def fake_list(**kwargs: object) -> list[APITokenResponse]:
        captured.update(kwargs)
        return [_fake_token_response(name="token-a")]

    monkeypatch.setattr(legacy_users, "list_api_tokens", fake_list)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/users/me/api-tokens")

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "token-a"
    assert captured["current_user"] is user
    assert "db" in captured


@pytest.mark.asyncio
async def test_create_api_token_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}

    async def fake_create(**kwargs: object) -> APITokenCreateResponse:
        captured.update(kwargs)
        return _fake_token_create_response(name="ci-token", token="plain-secret")

    monkeypatch.setattr(legacy_users, "create_api_token", fake_create)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/web-api/v1/users/me/api-tokens",
            json={"name": "ci-token"},
        )

    assert response.status_code == 201, response.text
    # The one-time plain token is preserved through the adapter unchanged.
    assert response.json()["token"] == "plain-secret"
    assert captured["current_user"] is user
    payload = captured["request"]
    assert isinstance(payload, APITokenCreateRequest)
    assert payload.name == "ci-token"
    assert "db" in captured


@pytest.mark.asyncio
async def test_revoke_api_token_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    token_id = uuid4()
    captured: dict[str, object] = {}

    async def fake_revoke(**kwargs: object) -> None:
        captured.update(kwargs)
        return None

    monkeypatch.setattr(legacy_users, "revoke_api_token", fake_revoke)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/users/me/api-tokens/{token_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["current_user"] is user
    # The path param is forwarded as a UUID (matching the legacy signature).
    assert captured["token_id"] == token_id
    assert "db" in captured


def test_users_api_tokens_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()))
    paths = app.openapi()["paths"]

    list_create = paths["/web-api/v1/users/me/api-tokens"]
    assert "get" in list_create
    assert "post" in list_create
    assert "delete" in paths["/web-api/v1/users/me/api-tokens/{token_id}"]


@pytest.mark.asyncio
async def test_users_api_tokens_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    token_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/users/me/api-tokens",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        "/web-api/v1/users/me/api-tokens",
        body={"name": "ci-token"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/users/me/api-tokens/{token_id}",
    )
