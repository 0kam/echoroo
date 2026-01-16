"""Security headers middleware for HTTP response hardening.

This middleware adds security headers to all HTTP responses to protect against
common web vulnerabilities including XSS, clickjacking, and MIME-type sniffing.

Security Headers Applied:
- Content-Security-Policy (CSP)
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection: 1; mode=block
- Strict-Transport-Security (HSTS) - production only
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy

References:
- OWASP Secure Headers Project: https://owasp.org/www-project-secure-headers/
- MDN Web Docs: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


@dataclass
class SecurityHeadersConfig:
    """Configuration for security headers middleware.

    Attributes:
        environment: Current environment (development, staging, production)
        enable_hsts: Whether to enable HSTS (forced for production)
        hsts_max_age: Max age for HSTS header in seconds (default: 1 year)
        hsts_include_subdomains: Include subdomains in HSTS
        hsts_preload: Enable HSTS preload
        frame_options: X-Frame-Options value (DENY or SAMEORIGIN)
        content_type_nosniff: Enable X-Content-Type-Options: nosniff
        xss_protection: Enable X-XSS-Protection header
        referrer_policy: Referrer-Policy header value
        csp_directives: Content-Security-Policy directives
        permissions_policy: Permissions-Policy directives
    """

    environment: Literal["development", "staging", "production"] = "development"
    enable_hsts: bool = False
    hsts_max_age: int = 31536000  # 1 year in seconds
    hsts_include_subdomains: bool = True
    hsts_preload: bool = False
    frame_options: Literal["DENY", "SAMEORIGIN"] = "DENY"
    content_type_nosniff: bool = True
    xss_protection: bool = True
    referrer_policy: str = "strict-origin-when-cross-origin"
    csp_directives: dict[str, list[str]] = field(default_factory=dict)
    permissions_policy: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set default CSP and permissions policy if not provided."""
        if not self.csp_directives:
            self.csp_directives = self._get_default_csp()
        if not self.permissions_policy:
            self.permissions_policy = self._get_default_permissions_policy()
        # Force HSTS in production
        if self.environment == "production":
            self.enable_hsts = True

    def _get_default_csp(self) -> dict[str, list[str]]:
        """Get default Content-Security-Policy directives."""
        # API-focused CSP - restrictive since we don't serve HTML content
        base_csp: dict[str, list[str]] = {
            "default-src": ["'none'"],
            "frame-ancestors": ["'none'"],
            "base-uri": ["'none'"],
            "form-action": ["'none'"],
        }

        # In development, allow more for debugging tools
        if self.environment == "development":
            base_csp["script-src"] = ["'self'"]
            base_csp["style-src"] = ["'self'", "'unsafe-inline'"]
            base_csp["img-src"] = ["'self'", "data:"]
            base_csp["connect-src"] = ["'self'"]

        return base_csp

    def _get_default_permissions_policy(self) -> dict[str, list[str]]:
        """Get default Permissions-Policy directives."""
        # Disable all sensitive browser features for API
        return {
            "accelerometer": [],
            "camera": [],
            "geolocation": [],
            "gyroscope": [],
            "magnetometer": [],
            "microphone": [],
            "payment": [],
            "usb": [],
        }


def build_csp_header(directives: dict[str, list[str]]) -> str:
    """Build Content-Security-Policy header string from directives."""
    parts = []
    for directive, values in directives.items():
        if values:
            parts.append(f"{directive} {' '.join(values)}")
        else:
            parts.append(directive)
    return "; ".join(parts)


def build_permissions_policy_header(policies: dict[str, list[str]]) -> str:
    """Build Permissions-Policy header string from policies."""
    parts = []
    for policy, origins in policies.items():
        if origins:
            origins_str = " ".join(origins)
            parts.append(f"{policy}=({origins_str})")
        else:
            parts.append(f"{policy}=()")
    return ", ".join(parts)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all HTTP responses."""

    def __init__(
        self,
        app: ASGIApp,
        config: SecurityHeadersConfig | None = None,
    ) -> None:
        """Initialize security headers middleware."""
        super().__init__(app)
        self.config = config or SecurityHeadersConfig()
        self._security_headers = self._build_security_headers()

    def _build_security_headers(self) -> dict[str, str]:
        """Build security headers dictionary based on configuration."""
        headers: dict[str, str] = {}

        # X-Content-Type-Options
        if self.config.content_type_nosniff:
            headers["X-Content-Type-Options"] = "nosniff"

        # X-Frame-Options
        headers["X-Frame-Options"] = self.config.frame_options

        # X-XSS-Protection (legacy but still useful for older browsers)
        if self.config.xss_protection:
            headers["X-XSS-Protection"] = "1; mode=block"

        # Referrer-Policy
        headers["Referrer-Policy"] = self.config.referrer_policy

        # Strict-Transport-Security (HSTS)
        if self.config.enable_hsts:
            hsts_value = f"max-age={self.config.hsts_max_age}"
            if self.config.hsts_include_subdomains:
                hsts_value += "; includeSubDomains"
            if self.config.hsts_preload:
                hsts_value += "; preload"
            headers["Strict-Transport-Security"] = hsts_value

        # Content-Security-Policy
        if self.config.csp_directives:
            headers["Content-Security-Policy"] = build_csp_header(
                self.config.csp_directives
            )

        # Permissions-Policy
        if self.config.permissions_policy:
            headers["Permissions-Policy"] = build_permissions_policy_header(
                self.config.permissions_policy
            )

        # Cache-Control for API responses
        headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"

        # Prevent MIME type sniffing
        headers["X-Download-Options"] = "noopen"

        # Cross-Origin policies
        headers["Cross-Origin-Opener-Policy"] = "same-origin"
        headers["Cross-Origin-Resource-Policy"] = "same-origin"

        return headers

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Process request and add security headers to response."""
        response = await call_next(request)

        # Add all security headers to response
        for header_name, header_value in self._security_headers.items():
            response.headers[header_name] = header_value

        return response


def get_security_config_for_environment(
    environment: Literal["development", "staging", "production"],
) -> SecurityHeadersConfig:
    """Get appropriate security configuration for the given environment."""
    if environment == "production":
        return SecurityHeadersConfig(
            environment="production",
            enable_hsts=True,
            hsts_max_age=31536000,  # 1 year
            hsts_include_subdomains=True,
            hsts_preload=True,
            frame_options="DENY",
            referrer_policy="strict-origin-when-cross-origin",
        )
    elif environment == "staging":
        return SecurityHeadersConfig(
            environment="staging",
            enable_hsts=True,
            hsts_max_age=86400,  # 1 day for staging
            hsts_include_subdomains=True,
            hsts_preload=False,
            frame_options="DENY",
            referrer_policy="strict-origin-when-cross-origin",
        )
    else:
        # Development - more relaxed but still secure defaults
        return SecurityHeadersConfig(
            environment="development",
            enable_hsts=False,  # Don't enable HSTS in development
            frame_options="DENY",
            referrer_policy="strict-origin-when-cross-origin",
        )


def get_production_cors_config(allowed_origins: list[str]) -> dict[str, object]:
    """Get restrictive CORS configuration for production."""
    return {
        "allow_origins": allowed_origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Accept",
            "Accept-Language",
            "Authorization",
            "Content-Language",
            "Content-Type",
            "X-Requested-With",
            "X-CSRF-Token",
        ],
        "expose_headers": [
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
        "max_age": 600,  # 10 minutes preflight cache
    }


def get_development_cors_config(allowed_origins: list[str]) -> dict[str, object]:
    """Get permissive CORS configuration for development."""
    return {
        "allow_origins": allowed_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "max_age": 600,
    }
