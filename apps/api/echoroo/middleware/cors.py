"""URL-prefix-aware CORS middleware (plan §CORS, FR-099, T075).

The 006-permissions-redesign splits the API into two URL prefixes
with very different security profiles:

* ``/api/v1/*`` — Programmatic API. Authentication is via Bearer API
  key, never cookies. CORS may therefore be permissive
  (``Allow-Origin: *``, ``Allow-Credentials: false``) because no
  ambient browser credential can be replayed by a hostile origin.
* ``/web-api/v1/*`` — First-party session API. Authentication is via
  HttpOnly session cookie. CORS MUST be strict same-origin
  (``Allow-Origin: https://echoroo.app`` only,
  ``Allow-Credentials: true``).

Starlette's stock :class:`CORSMiddleware` cannot easily switch policy
based on the request path. This module implements a thin dispatcher
that owns two underlying :class:`CORSMiddleware` instances and routes
the request to the right one based on the URL prefix. Anything that
matches neither prefix passes through with no CORS headers (those
endpoints — ``/health``, ``/metrics`` — are not browser-reachable).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

PROGRAMMATIC_PREFIX: Final[str] = "/api/v1"
SESSION_PREFIX: Final[str] = "/web-api/v1"


@dataclass
class CorsPolicy:
    """Per-prefix CORS policy.

    Attributes:
        allow_origins: Origins allowed to issue cross-origin requests.
            Use ``["*"]`` for the public programmatic API (combined
            with ``allow_credentials=False``). Use a literal allowlist
            for the first-party API.
        allow_credentials: Whether to send ``Allow-Credentials: true``.
            MUST be False when ``allow_origins == ["*"]`` per the CORS
            spec; the stock :class:`CORSMiddleware` enforces this.
        allow_methods: Allowed methods.
        allow_headers: Allowed request headers.
        expose_headers: Headers to expose to the JS layer.
        max_age: Preflight cache lifetime in seconds.
    """

    allow_origins: tuple[str, ...] = ()
    allow_credentials: bool = False
    allow_methods: tuple[str, ...] = (
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS",
    )
    allow_headers: tuple[str, ...] = (
        "Authorization",
        "Content-Type",
        "Accept",
        "X-Requested-With",
        "X-CSRF-Token",
    )
    expose_headers: tuple[str, ...] = (
        "X-Request-ID",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
    )
    max_age: int = 600


@dataclass
class PrefixCorsConfig:
    """Configuration for :class:`PrefixCorsMiddleware`.

    Attributes:
        programmatic: Policy applied under :data:`PROGRAMMATIC_PREFIX`.
        session: Policy applied under :data:`SESSION_PREFIX`.
        programmatic_prefix: Override path prefix.
        session_prefix: Override path prefix.
    """

    programmatic: CorsPolicy = field(
        default_factory=lambda: CorsPolicy(
            allow_origins=("*",),
            allow_credentials=False,
        )
    )
    session: CorsPolicy = field(
        default_factory=lambda: CorsPolicy(
            allow_origins=(),
            allow_credentials=True,
        )
    )
    programmatic_prefix: str = PROGRAMMATIC_PREFIX
    session_prefix: str = SESSION_PREFIX


def _build_starlette_cors(app: ASGIApp, policy: CorsPolicy) -> CORSMiddleware:
    return CORSMiddleware(
        app,
        allow_origins=list(policy.allow_origins),
        allow_credentials=policy.allow_credentials,
        allow_methods=list(policy.allow_methods),
        allow_headers=list(policy.allow_headers),
        expose_headers=list(policy.expose_headers),
        max_age=policy.max_age,
    )


class PrefixCorsMiddleware:
    """Route a request to one of two underlying CORS middlewares.

    This is an ASGI middleware (``__call__``) rather than a
    :class:`BaseHTTPMiddleware` subclass because the upstream
    :class:`CORSMiddleware` is itself an ASGI middleware and we want to
    delegate to it without an extra response materialisation step.
    """

    def __init__(self, app: ASGIApp, config: PrefixCorsConfig) -> None:
        self._inner_app = app
        self._programmatic_prefix = config.programmatic_prefix
        self._session_prefix = config.session_prefix
        self._programmatic = _build_starlette_cors(app, config.programmatic)
        self._session = _build_starlette_cors(app, config.session)

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope.get("type") != "http":
            await self._inner_app(scope, receive, send)
            return

        path: str = scope.get("path", "") or ""
        if path.startswith(self._programmatic_prefix):
            await self._programmatic(scope, receive, send)
            return
        if path.startswith(self._session_prefix):
            await self._session(scope, receive, send)
            return
        await self._inner_app(scope, receive, send)


# Convenience helper for tests / Phase 3 wiring -----------------------------


def policy_for_request(config: PrefixCorsConfig, request: Request) -> CorsPolicy | None:
    """Return the policy that would apply to ``request``, or ``None``.

    Useful for unit tests asserting that the right policy is selected
    for a given path without exercising the full ASGI stack.
    """
    path = request.url.path
    if path.startswith(config.programmatic_prefix):
        return config.programmatic
    if path.startswith(config.session_prefix):
        return config.session
    return None


def build_prefix_cors_middleware(
    app: ASGIApp,
    *,
    session_origins: tuple[str, ...],
    programmatic_origins: tuple[str, ...] = ("*",),
) -> PrefixCorsMiddleware:
    """Factory that produces the production-default policy combination.

    Args:
        app: Inner ASGI app.
        session_origins: Origins allowed for ``/web-api/v1/*``. Pass
            the SvelteKit deploy origin (e.g. ``"https://echoroo.app"``).
        programmatic_origins: Origins for ``/api/v1/*``. Defaults to
            ``("*",)`` because the programmatic API rejects all ambient
            credentials.
    """
    config = PrefixCorsConfig(
        programmatic=CorsPolicy(
            allow_origins=programmatic_origins,
            allow_credentials=False,
        ),
        session=CorsPolicy(
            allow_origins=session_origins,
            allow_credentials=True,
        ),
    )
    return PrefixCorsMiddleware(app, config)


__all__ = [
    "PROGRAMMATIC_PREFIX",
    "SESSION_PREFIX",
    "CorsPolicy",
    "PrefixCorsConfig",
    "PrefixCorsMiddleware",
    "build_prefix_cors_middleware",
    "policy_for_request",
]
