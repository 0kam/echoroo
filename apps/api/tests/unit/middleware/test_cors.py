"""Smoke tests for :mod:`echoroo.middleware.cors` (T075)."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from echoroo.middleware.cors import (
    CorsPolicy,
    PrefixCorsConfig,
    PrefixCorsMiddleware,
    policy_for_request,
)


def _client_with(config: PrefixCorsConfig) -> TestClient:
    async def echo(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[
            Route("/api/v1/ping", echo),
            Route("/web-api/v1/ping", echo),
            Route("/health", echo),
        ]
    )
    wrapped = PrefixCorsMiddleware(app, config)
    return TestClient(wrapped)


def test_policy_for_request_picks_programmatic_for_api_v1() -> None:
    config = PrefixCorsConfig()
    request = Request({"type": "http", "path": "/api/v1/projects", "headers": []})
    policy = policy_for_request(config, request)
    assert policy is config.programmatic


def test_policy_for_request_picks_session_for_web_api_v1() -> None:
    config = PrefixCorsConfig()
    request = Request(
        {"type": "http", "path": "/web-api/v1/projects", "headers": []}
    )
    policy = policy_for_request(config, request)
    assert policy is config.session


def test_policy_for_request_returns_none_outside_prefixes() -> None:
    config = PrefixCorsConfig()
    request = Request({"type": "http", "path": "/health", "headers": []})
    assert policy_for_request(config, request) is None


def test_cors_per_prefix_policy_programmatic_allows_wildcard() -> None:
    """Public programmatic API mirrors ``Origin`` for ``*`` policy without credentials."""
    config = PrefixCorsConfig(
        programmatic=CorsPolicy(allow_origins=("*",), allow_credentials=False),
        session=CorsPolicy(
            allow_origins=("https://echoroo.app",), allow_credentials=True
        ),
    )
    client = _client_with(config)
    resp = client.options(
        "/api/v1/ping",
        headers={
            "Origin": "https://random-site.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORSMiddleware returns 200 for accepted preflights.
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"
    # Wildcard origins must NOT carry credentials.
    assert resp.headers.get("access-control-allow-credentials") != "true"


def test_cors_per_prefix_policy_session_strict_allowlist() -> None:
    """First-party session API only allows the configured origin and sends credentials."""
    config = PrefixCorsConfig(
        programmatic=CorsPolicy(allow_origins=("*",), allow_credentials=False),
        session=CorsPolicy(
            allow_origins=("https://echoroo.app",), allow_credentials=True
        ),
    )
    client = _client_with(config)

    # Allowed origin
    ok = client.options(
        "/web-api/v1/ping",
        headers={
            "Origin": "https://echoroo.app",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert ok.status_code == 200
    assert ok.headers.get("access-control-allow-origin") == "https://echoroo.app"
    assert ok.headers.get("access-control-allow-credentials") == "true"

    # Forbidden origin — Starlette's CORSMiddleware returns 400 for disallowed origins.
    bad = client.options(
        "/web-api/v1/ping",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert bad.status_code != 200 or bad.headers.get(
        "access-control-allow-origin"
    ) != "https://attacker.example"
