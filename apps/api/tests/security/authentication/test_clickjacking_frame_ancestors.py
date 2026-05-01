"""FR-102: Clickjacking prevention via frame-ancestors CSP directive (T979).

Verifies that every response from the FastAPI application carries:

* ``Content-Security-Policy`` header containing ``frame-ancestors 'none'``
  (or at minimum a restrictive ``frame-ancestors`` directive).
* ``X-Frame-Options: DENY`` for legacy browser compatibility.

Both headers are emitted by :class:`echoroo.middleware.security_headers.SecurityHeadersMiddleware`
which is wired unconditionally in :func:`echoroo.main.create_app`. The tests
build a minimal Starlette/FastAPI application with the real middleware to
avoid dependency on the full application stack while still testing the
production-wired configuration.

Endpoints tested:
  - GET  /web-api/v1/projects/{id}      (authenticated project read)
  - POST /web-api/v1/auth/login          (unauthenticated login)
  - GET  /api/v1/projects/{id}           (programmatic / Bearer API key)
  - GET  /web-api/v1/public/{slug}       (public read endpoint)
  - Any synthetic path (header must be on ALL responses)
"""

from __future__ import annotations

import re

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

# ---------------------------------------------------------------------------
# Test application helpers
# ---------------------------------------------------------------------------


def _build_app(config: SecurityHeadersConfig | None = None) -> Starlette:
    """Build a minimal Starlette app wired with SecurityHeadersMiddleware.

    All routes return 200 JSON so we can focus exclusively on the headers.
    """

    async def stub_endpoint(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    routes = [
        Route("/web-api/v1/auth/login", stub_endpoint, methods=["GET", "POST"]),
        Route("/web-api/v1/projects/{project_id}", stub_endpoint),
        Route("/api/v1/projects/{project_id}", stub_endpoint),
        Route("/web-api/v1/public/{slug}", stub_endpoint),
        Route("/health", stub_endpoint),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware, config=config)
    return app


@pytest.fixture(scope="module")
def default_client() -> TestClient:
    """Test client with the default (production-like) SecurityHeadersConfig."""
    return TestClient(_build_app())


@pytest.fixture(scope="module")
def strict_none_client() -> TestClient:
    """Test client explicitly configured with frame-ancestors 'none'."""
    config = SecurityHeadersConfig(frame_ancestors="'none'", enable_hsts=False)
    return TestClient(_build_app(config=config))


# ---------------------------------------------------------------------------
# 1. Default config sets frame-ancestors 'none' in CSP.
# ---------------------------------------------------------------------------


def test_default_config_frame_ancestors_none_in_csp(default_client: TestClient) -> None:
    """The default SecurityHeadersConfig MUST produce ``frame-ancestors 'none'``."""
    resp = default_client.get("/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp, "CSP header must contain frame-ancestors directive"
    assert "'none'" in csp or "none" in csp, (
        f"frame-ancestors must be 'none' by default, got CSP={csp!r}"
    )


# ---------------------------------------------------------------------------
# 2. X-Frame-Options: DENY on all responses (legacy browser compat).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,method",
    [
        ("/web-api/v1/auth/login", "GET"),
        ("/web-api/v1/projects/00000000-0000-0000-0000-000000000001", "GET"),
        ("/api/v1/projects/00000000-0000-0000-0000-000000000001", "GET"),
        ("/web-api/v1/public/some-slug", "GET"),
        ("/health", "GET"),
    ],
)
def test_x_frame_options_deny_on_all_endpoints(
    default_client: TestClient,
    path: str,
    method: str,
) -> None:
    """``X-Frame-Options: DENY`` MUST be present on every response path."""
    resp = default_client.request(method, path)
    xfo = resp.headers.get("X-Frame-Options", "")
    assert xfo.upper() == "DENY", (
        f"Expected X-Frame-Options: DENY on {method} {path}, got {xfo!r}"
    )


# ---------------------------------------------------------------------------
# 3. frame-ancestors present on all tested endpoints.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/web-api/v1/auth/login",
        "/web-api/v1/projects/00000000-0000-0000-0000-000000000002",
        "/api/v1/projects/00000000-0000-0000-0000-000000000002",
        "/health",
    ],
)
def test_csp_frame_ancestors_present_on_all_endpoints(
    default_client: TestClient,
    path: str,
) -> None:
    """``Content-Security-Policy`` MUST include ``frame-ancestors`` on every endpoint."""
    resp = default_client.get(path)
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp, (
        f"Missing frame-ancestors in CSP on GET {path}: csp={csp!r}"
    )


# ---------------------------------------------------------------------------
# 4. Login endpoint (POST) has both anti-clickjacking headers.
# ---------------------------------------------------------------------------


def test_login_post_endpoint_has_both_clickjacking_headers(
    default_client: TestClient,
) -> None:
    """POST /web-api/v1/auth/login MUST carry both X-Frame-Options and CSP frame-ancestors."""
    resp = default_client.post("/web-api/v1/auth/login", json={"dummy": True})
    assert resp.headers.get("X-Frame-Options", "").upper() == "DENY"
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors" in csp


# ---------------------------------------------------------------------------
# 5. Explicit 'none' config: frame-ancestors 'none' is exact.
# ---------------------------------------------------------------------------


def test_explicit_none_config_sets_frame_ancestors_none(
    strict_none_client: TestClient,
) -> None:
    """Explicit ``frame_ancestors=\"'none'\"`` config MUST produce exactly
    ``frame-ancestors 'none'`` (single-quoted, per CSP Level 2 spec).
    """
    resp = strict_none_client.get("/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    # Extract frame-ancestors value.
    match = re.search(r"frame-ancestors\s+([^;]+)", csp)
    assert match is not None, f"frame-ancestors not found in CSP: {csp!r}"
    frame_ancestors_value = match.group(1).strip()
    assert frame_ancestors_value == "'none'", (
        f"Expected frame-ancestors 'none', got {frame_ancestors_value!r}"
    )


# ---------------------------------------------------------------------------
# 6. X-Frame-Options and CSP coexist — both must be present simultaneously.
# ---------------------------------------------------------------------------


def test_both_anti_clickjacking_headers_coexist(default_client: TestClient) -> None:
    """``X-Frame-Options`` and ``Content-Security-Policy`` with ``frame-ancestors``
    MUST coexist on the same response — one does not replace the other.

    Modern browsers prefer CSP ``frame-ancestors``; legacy browsers (IE11,
    older Safari) rely on ``X-Frame-Options``. Both are required.
    """
    resp = default_client.get("/health")
    assert "X-Frame-Options" in resp.headers
    assert "Content-Security-Policy" in resp.headers
    assert "frame-ancestors" in resp.headers["Content-Security-Policy"]


# ---------------------------------------------------------------------------
# 7. Config with frame_ancestors='self' is also valid (restrictive alternative).
# ---------------------------------------------------------------------------


def test_frame_ancestors_self_config_is_restrictive() -> None:
    """``frame_ancestors=\"'self'\"`` is a more permissive but still valid config
    that allows the same origin to frame the page. Verify it produces the
    correct directive (not 'none', but still protective against foreign origins).
    """
    config = SecurityHeadersConfig(frame_ancestors="'self'", enable_hsts=False)
    client = TestClient(_build_app(config=config))
    resp = client.get("/health")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "frame-ancestors 'self'" in csp, (
        f"Expected frame-ancestors 'self' in CSP: {csp!r}"
    )
    # X-Frame-Options is still DENY regardless of CSP frame-ancestors value —
    # the middleware hardcodes DENY (legacy compat).
    assert resp.headers.get("X-Frame-Options", "").upper() == "DENY"


__all__ = [
    "test_both_anti_clickjacking_headers_coexist",
    "test_csp_frame_ancestors_present_on_all_endpoints",
    "test_default_config_frame_ancestors_none_in_csp",
    "test_explicit_none_config_sets_frame_ancestors_none",
    "test_frame_ancestors_self_config_is_restrictive",
    "test_login_post_endpoint_has_both_clickjacking_headers",
    "test_x_frame_options_deny_on_all_endpoints",
]
