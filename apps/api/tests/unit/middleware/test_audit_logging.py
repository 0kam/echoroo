"""Smoke tests for :mod:`echoroo.middleware.audit_logging` (T073)."""

from __future__ import annotations

import json
import logging

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from echoroo.middleware.audit_logging import (
    REDACTED,
    AccessLogConfig,
    AccessLogMiddleware,
)


def _build_app() -> TestClient:
    async def echo(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/api/v1/echo", echo)])
    app.add_middleware(AccessLogMiddleware, config=AccessLogConfig())
    return TestClient(app)


@pytest.fixture
def caplog_access(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="echoroo.access")
    return caplog


def _structured_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for record in caplog.records:
        data = getattr(record, "data", None)
        if isinstance(data, str):
            out.append(json.loads(data))
    return out


def test_audit_logging_redacts_authorization_header(
    caplog_access: pytest.LogCaptureFixture,
) -> None:
    """Sensitive headers must be replaced with the redaction marker."""
    client = _build_app()
    resp = client.get(
        "/api/v1/echo",
        headers={
            "Authorization": "Bearer super-secret-key",
            "Cookie": "session_id=abcd1234",
            "X-CSRF-Token": "csrf-token",
            "User-Agent": "pytest",
        },
    )
    assert resp.status_code == 200

    records = _structured_records(caplog_access)
    assert records, "expected at least one structured access log entry"
    headers = records[-1]["headers"]
    assert isinstance(headers, dict)
    # Header lookup is case-insensitive; check both cases.
    auth_value = headers.get("Authorization") or headers.get("authorization")
    assert auth_value == REDACTED
    cookie_value = headers.get("Cookie") or headers.get("cookie")
    assert cookie_value == REDACTED
    csrf_value = headers.get("X-CSRF-Token") or headers.get("x-csrf-token")
    assert csrf_value == REDACTED
    # Non-sensitive header passes through.
    ua_value = headers.get("User-Agent") or headers.get("user-agent")
    assert ua_value == "pytest"


def test_audit_logging_redacts_query_credentials(
    caplog_access: pytest.LogCaptureFixture,
) -> None:
    """Sensitive query string keys must be redacted regardless of value shape."""
    client = _build_app()
    client.get("/api/v1/echo?token=plain-token-not-pii&media_token=media-secret&page=2")
    records = _structured_records(caplog_access)
    last = records[-1]
    query = last["query"]
    assert isinstance(query, str)
    assert "token=" in query
    assert "plain-token-not-pii" not in query
    assert "media_token=" in query
    assert "media-secret" not in query
    assert "page=2" in query


def test_audit_logging_skips_excluded_paths(
    caplog_access: pytest.LogCaptureFixture,
) -> None:
    """Health checks should not pollute access logs."""

    async def healthy(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/health", healthy)])
    app.add_middleware(
        AccessLogMiddleware,
        config=AccessLogConfig(excluded_paths=("/health",)),
    )
    client = TestClient(app)
    client.get("/health")
    records = _structured_records(caplog_access)
    assert all(record.get("path") != "/health" for record in records)
