"""Smoke coverage for the users-profile BFF adapters (W2-2 B).

W2-2 routes the self-scoped ``/users/me*`` endpoints through the
``/web-api/v1`` BFF surface (cookie + CSRF), each delegating verbatim to
the legacy :mod:`echoroo.api.v1.users` handler. This module covers the
two profile-mutation paths:

* ``PATCH /web-api/v1/users/me``          → ``update_current_user``
* ``PUT   /web-api/v1/users/me/password`` → ``change_password``

HONESTY NOTE: the ``*_bff_delegates_to_legacy`` tests **monkeypatch** the
legacy handler and assert on the kwargs the BFF forwards. They verify the
transport wiring (route → correct legacy callable with the right kwargs +
status code), NOT real DB-backed delegation. The legacy handler's own DB
semantics (persistence, validation, error mapping) are covered by the
legacy ``/api/v1`` handler's own tests and are intentionally out of scope
here (W2-2 is transport-only). These routes are self-scoped (no
``project_id``) so there is no ``gate_action`` to assert.
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
from echoroo.schemas.user import (
    PasswordChangeRequest,
    PasswordChangeResponse,
    UserResponse,
    UserUpdateRequest,
)
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _fake_user_response(*, display_name: str) -> UserResponse:
    now = datetime.now(UTC)
    return UserResponse(
        id=uuid4(),
        email="user@example.com",
        display_name=display_name,
        created_at=now,
        updated_at=now,
        last_login_at=None,
        two_factor_enabled=False,
    )


def _build_app(*, user: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_users.router, prefix="/web-api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_update_profile_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> UserResponse:
        captured.update(kwargs)
        return _fake_user_response(display_name="Updated Name")

    monkeypatch.setattr(legacy_users, "update_current_user", fake_update)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            "/web-api/v1/users/me",
            json={"display_name": "Updated Name"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["display_name"] == "Updated Name"
    assert captured["current_user"] is user
    payload = captured["request"]
    assert isinstance(payload, UserUpdateRequest)
    assert payload.display_name == "Updated Name"
    # db is forwarded verbatim (the fake get_db yields a sentinel object).
    assert "db" in captured


@pytest.mark.asyncio
async def test_change_password_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}

    async def fake_change(**kwargs: object) -> PasswordChangeResponse:
        captured.update(kwargs)
        return PasswordChangeResponse()

    monkeypatch.setattr(legacy_users, "change_password", fake_change)

    app = _build_app(user=user)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.put(
            "/web-api/v1/users/me/password",
            json={
                "current_password": "OldPassw0rd",
                "new_password": "NewPassw0rd1",
            },
        )

    assert response.status_code == 200, response.text
    assert captured["current_user"] is user
    payload = captured["request"]
    assert isinstance(payload, PasswordChangeRequest)
    assert payload.current_password == "OldPassw0rd"
    assert payload.new_password == "NewPassw0rd1"
    assert "db" in captured


def test_users_profile_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()))
    paths = app.openapi()["paths"]

    assert "patch" in paths["/web-api/v1/users/me"]
    assert "put" in paths["/web-api/v1/users/me/password"]


@pytest.mark.asyncio
async def test_users_profile_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        "/web-api/v1/users/me",
        body={"display_name": "x"},
    )
    await assert_api_key_cross_rejected(
        client,
        "PUT",
        "/web-api/v1/users/me/password",
        body={
            "current_password": "OldPassw0rd",
            "new_password": "NewPassw0rd1",
        },
    )
