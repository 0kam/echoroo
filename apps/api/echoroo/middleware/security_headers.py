"""Per-request security headers with CSP nonce (FR-102, T071).

This middleware is the 006-permissions-redesign successor to the
legacy :mod:`echoroo.middleware.security` module. The legacy module
sets static headers; FR-102 requires a **per-request CSP nonce** so
that inline scripts / styles can be allowed via ``'nonce-<n>'`` without
opening up ``'unsafe-inline'``.

Headers emitted on every response:

* ``Content-Security-Policy`` — restrictive baseline plus the freshly
  generated nonce; nonce is also exposed on ``request.state.csp_nonce``
  so route handlers can include it in templated HTML.
* ``Strict-Transport-Security`` — 2 years, includeSubDomains, preload.
* ``X-Frame-Options: DENY``.
* ``X-Content-Type-Options: nosniff``.
* ``Referrer-Policy: strict-origin-when-cross-origin``.
* ``Permissions-Policy`` — disables geolocation, microphone, camera.

The middleware exposes a config object so deployment-specific overrides
(e.g. allowing additional ``script-src`` hosts in dev) live in one
place. Phase 3 wires this into ``main.py``; for now it is unwired.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_HSTS_MAX_AGE: Final[int] = 63072000  # 2 years
"""FR-102: HSTS lifetime is 2 years to qualify for HSTS preload list."""

NONCE_BYTES: Final[int] = 16
"""Nonce strength. 128 bits of entropy is overkill but cheap."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class SecurityHeadersConfig:
    """Configuration for :class:`SecurityHeadersMiddleware`.

    Attributes:
        enable_hsts: When False (e.g. local dev over HTTP), HSTS is
            omitted entirely so browsers don't cache an HTTPS upgrade
            for ``localhost``.
        hsts_max_age: HSTS lifetime in seconds.
        hsts_include_subdomains: Whether to add ``includeSubDomains``.
        hsts_preload: Whether to add ``preload``.
        frame_ancestors: Value for the CSP ``frame-ancestors`` directive.
        extra_script_src: Additional hosts allowed in ``script-src``
            beyond ``'self'`` and the per-request nonce.
        extra_style_src: Additional hosts allowed in ``style-src``.
        extra_img_src: Additional hosts allowed in ``img-src``.
        extra_connect_src: Additional hosts allowed in ``connect-src``.
        permissions_policy: Map of feature → empty (=disable) / allow list.
    """

    enable_hsts: bool = True
    hsts_max_age: int = DEFAULT_HSTS_MAX_AGE
    hsts_include_subdomains: bool = True
    hsts_preload: bool = True
    frame_ancestors: str = "'none'"
    extra_script_src: tuple[str, ...] = ()
    extra_style_src: tuple[str, ...] = ()
    extra_img_src: tuple[str, ...] = ("data:",)
    extra_connect_src: tuple[str, ...] = ()
    permissions_policy: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "geolocation": (),
            "microphone": (),
            "camera": (),
        }
    )


# ---------------------------------------------------------------------------
# Header builders
# ---------------------------------------------------------------------------


def _build_csp(nonce: str, config: SecurityHeadersConfig) -> str:
    script_src = " ".join(("'self'", f"'nonce-{nonce}'", *config.extra_script_src))
    style_src = " ".join(("'self'", f"'nonce-{nonce}'", *config.extra_style_src))
    img_src = " ".join(("'self'", *config.extra_img_src))
    connect_src = " ".join(("'self'", *config.extra_connect_src))
    directives = [
        "default-src 'self'",
        f"script-src {script_src}",
        f"style-src {style_src}",
        f"img-src {img_src}",
        f"connect-src {connect_src}",
        f"frame-ancestors {config.frame_ancestors}",
        "base-uri 'self'",
        "form-action 'self'",
        "object-src 'none'",
    ]
    return "; ".join(directives)


def _build_hsts(config: SecurityHeadersConfig) -> str:
    parts = [f"max-age={config.hsts_max_age}"]
    if config.hsts_include_subdomains:
        parts.append("includeSubDomains")
    if config.hsts_preload:
        parts.append("preload")
    return "; ".join(parts)


def _build_permissions_policy(config: SecurityHeadersConfig) -> str:
    parts = []
    for feature, allow_list in config.permissions_policy.items():
        if allow_list:
            allow = " ".join(allow_list)
            parts.append(f"{feature}=({allow})")
        else:
            parts.append(f"{feature}=()")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add per-request security headers including CSP nonce."""

    def __init__(
        self,
        app: ASGIApp,
        config: SecurityHeadersConfig | None = None,
    ) -> None:
        super().__init__(app)
        self.config = config or SecurityHeadersConfig()

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        nonce = secrets.token_urlsafe(NONCE_BYTES)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        response.headers["Content-Security-Policy"] = _build_csp(nonce, self.config)
        if self.config.enable_hsts:
            response.headers["Strict-Transport-Security"] = _build_hsts(self.config)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if self.config.permissions_policy:
            response.headers["Permissions-Policy"] = _build_permissions_policy(
                self.config
            )

        return response


__all__ = [
    "DEFAULT_HSTS_MAX_AGE",
    "NONCE_BYTES",
    "SecurityHeadersConfig",
    "SecurityHeadersMiddleware",
]
