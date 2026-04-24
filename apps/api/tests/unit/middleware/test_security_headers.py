"""Smoke tests for :mod:`echoroo.middleware.security_headers` (T071)."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from echoroo.middleware.security_headers import (
    SecurityHeadersConfig,
    SecurityHeadersMiddleware,
)


def _build_app() -> Starlette:
    async def hello(request: Request) -> JSONResponse:
        nonce = getattr(request.state, "csp_nonce", None)
        return JSONResponse({"nonce": nonce})

    app = Starlette(routes=[Route("/", hello)])
    app.add_middleware(SecurityHeadersMiddleware)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


def test_security_headers_sets_required_headers(client: TestClient) -> None:
    """All baseline headers MUST be present on every response."""
    resp = client.get("/")
    assert resp.status_code == 200

    headers = resp.headers
    assert "Content-Security-Policy" in headers
    assert "Strict-Transport-Security" in headers
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in headers


def test_csp_includes_per_request_nonce() -> None:
    """The CSP header must contain a nonce that matches request.state."""
    app = _build_app()
    client = TestClient(app)
    resp = client.get("/")
    body: dict[str, Any] = resp.json()
    nonce = body["nonce"]
    assert nonce, "request.state.csp_nonce must be populated"
    assert f"'nonce-{nonce}'" in resp.headers["Content-Security-Policy"]


def test_security_headers_disable_hsts_when_configured() -> None:
    """Setting enable_hsts=False omits the HSTS header (dev over plain HTTP)."""
    config = SecurityHeadersConfig(enable_hsts=False)

    async def hello(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", hello)])
    app.add_middleware(SecurityHeadersMiddleware, config=config)
    client = TestClient(app)
    resp = client.get("/")
    assert "Strict-Transport-Security" not in resp.headers
