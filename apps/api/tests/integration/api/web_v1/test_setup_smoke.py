"""Smoke coverage for the first-run setup BFF adapters (W2-2-A).

W2-2-A routes the browser setup wizard off the direct ``/api/v1/setup/*``
path onto the ``/web-api/v1/setup/*`` BFF mirror, which delegates verbatim
to the legacy ``echoroo.api.v1.setup`` handlers. These two endpoints run
before any user/session/CSRF token exists (their job is to create the
first admin), so they are auth- and CSRF-exempt
(``PUBLIC_AUTH_PATHS``) and classified ``SETUP_BOOTSTRAP`` (no
``gate_action``).

HONESTY NOTE: the ``*_bff_delegates_to_legacy`` tests **monkeypatch** the
legacy handler and assert on the kwargs the BFF forwards. They verify the
transport wiring (route → correct legacy callable with the right kwargs)
plus the contract surface (201 status + no-store response headers), NOT
real DB-backed delegation. The 403 already-setup guard and the DB-backed
setup semantics are owned and tested by the legacy ``/api/v1/setup``
handlers (W2-2-A is transport-only).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import setup as legacy_setup
from echoroo.api.web_v1 import setup as bff_setup
from echoroo.core.database import get_db
from echoroo.schemas.setup import (
    SetupCompleteResponse,
    SetupStatusResponse,
    UserResponse,
)


def _fake_status_response() -> SetupStatusResponse:
    return SetupStatusResponse(setup_required=True, setup_completed=False)


def _fake_complete_response() -> SetupCompleteResponse:
    now = datetime.now(UTC)
    return SetupCompleteResponse(
        user=UserResponse(
            id=uuid4(),
            email="admin@example.com",
            display_name="System Administrator",
            two_factor_enabled=False,
            created_at=now,
            updated_at=now,
        ),
        totp_secret_base32="JBSWY3DPEHPK3PXP",
        totp_provisioning_uri="otpauth://totp/Echoroo:admin@example.com?secret=JBSWY3DPEHPK3PXP",
        bootstrap_token="bootstrap-token",
        bootstrap_token_expires_at=now,
        webauthn_registration_url="/setup/webauthn",
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(bff_setup.router, prefix="/web-api/v1")
    app.dependency_overrides[get_db] = _fake_db
    return app


@pytest.mark.asyncio
async def test_setup_status_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_get_setup_status(**kwargs: object) -> SetupStatusResponse:
        captured.update(kwargs)
        return _fake_status_response()

    monkeypatch.setattr(legacy_setup, "get_setup_status", fake_get_setup_status)

    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/web-api/v1/setup/status")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["setup_required"] is True
    assert body["setup_completed"] is False
    # Transport wiring: the BFF forwards the injected db session verbatim.
    assert "db" in captured


@pytest.mark.asyncio
async def test_setup_initialize_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_initialize_setup(**kwargs: object) -> SetupCompleteResponse:
        captured.update(kwargs)
        # Mirror the legacy handler: set the no-store headers on the
        # forwarded Response so the BFF response carries them too.
        response = kwargs["response"]
        response.headers["Cache-Control"] = "no-store, no-cache, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return _fake_complete_response()

    monkeypatch.setattr(legacy_setup, "initialize_setup", fake_initialize_setup)

    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/web-api/v1/setup/initialize",
            json={
                "email": "admin@example.com",
                "password": "SuperSecurePass123!",
                "display_name": "System Administrator",
            },
        )

    assert response.status_code == 201, response.text
    # Contract: the no-store headers set by the legacy handler on the
    # forwarded Response object must survive on the BFF response.
    assert response.headers["Cache-Control"] == "no-store, no-cache, max-age=0"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    # Transport wiring: the BFF forwards the request/response/payload/db
    # verbatim to the legacy handler.
    assert "request" in captured
    assert "response" in captured
    assert "db" in captured
    payload = captured["payload"]
    assert isinstance(payload, legacy_setup.SetupInitializeRequest)
    assert payload.email == "admin@example.com"


def test_setup_bff_paths_declared_in_openapi() -> None:
    app = _build_app()
    paths = app.openapi()["paths"]

    assert "get" in paths["/web-api/v1/setup/status"]
    assert "post" in paths["/web-api/v1/setup/initialize"]
    # Contract surface: the initialize adapter declares the 201 status code.
    assert "201" in paths["/web-api/v1/setup/initialize"]["post"]["responses"]
