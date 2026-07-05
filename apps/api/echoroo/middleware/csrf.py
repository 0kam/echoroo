"""CSRF middleware for first-party session API (FR-098, T072).

The CSRF token is an HMAC-SHA256 over ``session_id || issued_at`` keyed
with the per-deployment ``session_secret``. The token body embeds the
``issued_at`` epoch seconds so the verifier can recompute the expected
HMAC without round-tripping to a server-side store, and so we can apply
a TTL.

Token wire format:

    base64url(payload) "." base64url(hmac)

where ``payload`` is ``"<session_id>:<issued_at>"`` UTF-8 encoded. We
use base64url without padding so the value can ride in a header / form
field without escaping.

Security properties:

* HMAC verification uses :func:`hmac.compare_digest` for constant-time
  comparison (FR-098, defends against signature timing oracles).
* Tokens are bound to a session id so a token issued for user A cannot
  be replayed against user B. Verification cross-checks the embedded
  session id against the live session cookie.
* Tokens have a 24h TTL. Older tokens fail verification even if their
  HMAC is correct.

The middleware enforces CSRF on **non-GET / non-HEAD / non-OPTIONS**
requests under ``/web-api/v1/*``, EXCEPT for the public pre-session
endpoints listed in :data:`echoroo.core.auth_paths.PUBLIC_AUTH_PATHS`
(login, register, 2FA challenge / verify, refresh, forgot-password,
reset-password). Those endpoints cannot present a CSRF token by
construction — the user has not yet established the session that
issues the token.

Refresh CSRF decision (Phase 2.10 #6)
-------------------------------------
``/web-api/v1/auth/refresh`` is intentionally exempt from CSRF: the
refresh token itself is the proof of the request, and adding a CSRF
layer on top would require a steady-state session cookie that doesn't
exist yet during refresh. See ``core/auth_paths.py`` for the full
decision rationale.

Programmatic API (``/api/v1/*``) relies on Bearer API keys and is
exempt globally — a CSRF token would only add ceremony for clients
that already include a strong credential.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from echoroo.core.auth_paths import (
    ANON_MEDIA_TOKEN_ISSUE_PATTERN,
    PUBLIC_AUTH_PATHS,
    is_public_auth_path,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CSRF_TTL_SECONDS: Final[int] = 24 * 60 * 60  # 24h
"""TTL for issued CSRF tokens. Tokens older than this fail verification."""

CSRF_HEADER_NAME: Final[str] = "X-CSRF-Token"
"""Default header name CSRF tokens are submitted under."""

WEB_API_PREFIX: Final[str] = "/web-api/v1"
"""URL prefix for first-party session API where CSRF enforcement applies."""

SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})
"""HTTP methods exempt from CSRF enforcement (read-only / preflight)."""

EXEMPT_PATHS: Final[tuple[str, ...]] = PUBLIC_AUTH_PATHS
"""Path-exact CSRF exemption list (Phase 2.10 #6).

Synced with ``echoroo.core.auth_paths.PUBLIC_AUTH_PATHS`` so the CSRF
exemption and the auth router's public allowlist cannot drift apart.
Match is exact (no prefix wildcarding).
"""

# spec/011 FR-011-105..106 — TOKEN_AUTH_ONLY paths whose ``{token}``
# segment IS the credential. The endpoint accepts an OPTIONAL session
# cookie; when none is present the caller has no CSRF token to issue,
# so the standard double-submit pattern cannot apply. The signed token
# (HMAC-SHA-256, constant-time compare) substitutes for CSRF here: an
# attacker forging a cross-site request would also need to know the
# single-shot token, which is delivered out-of-band and never leaks via
# referer (FR-011-102 cache directives). Pattern-based match because
# the variable ``{token}`` segment defeats exact-path enumeration.
_PATTERN_EXEMPT_PATHS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^/web-api/v1/auth/invitations/[^/]+/accept/?$"),
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CsrfError(Exception):
    """Raised when CSRF token verification fails."""


class CsrfTokenExpiredError(CsrfError):
    """Token signature is valid but the embedded issued_at is older than TTL."""


class CsrfTokenMalformedError(CsrfError):
    """Token shape (base64 / payload split) is wrong."""


class CsrfTokenMismatchError(CsrfError):
    """Token HMAC does not match the recomputed value or session_id mismatch."""


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# ---------------------------------------------------------------------------
# Issue / verify
# ---------------------------------------------------------------------------


def issue_csrf_token(
    session_id: str,
    *,
    session_secret: str,
    issued_at: int | None = None,
) -> str:
    """Mint a CSRF token bound to ``session_id``.

    Args:
        session_id: Server-side session identifier (must match the live
            session cookie value at verification time).
        session_secret: Deployment-wide HMAC key. MUST be the same value
            used in :func:`verify_csrf_token`.
        issued_at: Override clock for tests. Production callers pass
            ``None`` and we use :func:`time.time`.

    Returns:
        Token string of the form ``<payload_b64url>.<hmac_b64url>``.
    """
    if not session_id:
        raise ValueError("session_id must be non-empty")
    if not session_secret:
        raise ValueError("session_secret must be non-empty")

    issued = int(issued_at if issued_at is not None else time.time())
    payload = f"{session_id}:{issued}".encode()
    mac = hmac.new(session_secret.encode("utf-8"), payload, "sha256").digest()
    return f"{_b64url_encode(payload)}.{_b64url_encode(mac)}"


def verify_csrf_token(
    token: str,
    *,
    session_id: str,
    session_secret: str,
    ttl_seconds: int = DEFAULT_CSRF_TTL_SECONDS,
    now: int | None = None,
) -> None:
    """Verify a CSRF token issued by :func:`issue_csrf_token`.

    Raises:
        CsrfTokenMalformedError: Token shape is wrong.
        CsrfTokenMismatchError: HMAC does not match or session_id differs.
        CsrfTokenExpiredError: HMAC matches but token is older than TTL.
    """
    if not token or "." not in token:
        raise CsrfTokenMalformedError("missing or malformed token")

    payload_part, mac_part = token.split(".", 1)
    try:
        payload = _b64url_decode(payload_part)
        provided_mac = _b64url_decode(mac_part)
    except (ValueError, binascii.Error) as exc:
        raise CsrfTokenMalformedError("token base64 decode failed") from exc

    expected_mac = hmac.new(
        session_secret.encode("utf-8"), payload, "sha256"
    ).digest()
    if not hmac.compare_digest(expected_mac, provided_mac):
        raise CsrfTokenMismatchError("HMAC mismatch")

    try:
        decoded = payload.decode("utf-8")
        embedded_session_id, issued_str = decoded.rsplit(":", 1)
        issued_at = int(issued_str)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CsrfTokenMalformedError("payload structure invalid") from exc

    # Constant-time session_id check. Even though the HMAC binds the
    # payload, an attacker could still try to replay a token issued for
    # another session — comparing the embedded id against the live one
    # closes that path.
    if not hmac.compare_digest(embedded_session_id, session_id):
        raise CsrfTokenMismatchError("token session_id does not match request session")

    current = int(now if now is not None else time.time())
    if current - issued_at > ttl_seconds:
        raise CsrfTokenExpiredError("token expired")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CsrfConfig:
    """Configuration container for :class:`CsrfMiddleware`.

    Attributes:
        session_secret: Deployment HMAC key. MUST be at least 32 bytes
            of entropy in production.
        protected_prefix: URL prefix that triggers CSRF enforcement.
        header_name: Header CSRF tokens are read from.
        cookie_name: Session cookie name to bind the token against.
        ttl_seconds: Token lifetime.
    """

    session_secret: str
    protected_prefix: str = WEB_API_PREFIX
    header_name: str = CSRF_HEADER_NAME
    cookie_name: str = "session_id"
    ttl_seconds: int = DEFAULT_CSRF_TTL_SECONDS


class CsrfMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces CSRF on the first-party API.

    Behaviour:

    * Methods in :data:`SAFE_METHODS` pass through.
    * Requests outside ``protected_prefix`` pass through.
    * Requests inside ``protected_prefix`` MUST carry both the session
      cookie AND a header CSRF token. Either missing yields **403**.
    * Token signature / TTL / session-binding failures yield **403**.

    The middleware does not generate tokens — issuance is the auth
    flow's responsibility (login, 2FA verify) via
    :func:`issue_csrf_token`. The middleware only verifies.
    """

    def __init__(self, app: ASGIApp, config: CsrfConfig) -> None:
        super().__init__(app)
        self.config = config

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)
        if not request.url.path.startswith(self.config.protected_prefix):
            return await call_next(request)
        # Phase 2.10 #6: pre-session auth endpoints (login / register /
        # 2FA / refresh / forgot-password / reset-password) cannot
        # produce a CSRF token because no session cookie has been
        # issued yet. Bypass the check for those exact paths.
        if is_public_auth_path(request.url.path):
            return await call_next(request)

        # spec/011 FR-011-105..106: token-authenticated public paths
        # whose ``{token}`` segment IS the credential. The signed
        # envelope substitutes for the CSRF token here; pattern-based
        # match because the variable token defeats exact enumeration.
        for pattern in _PATTERN_EXEMPT_PATHS:
            if pattern.fullmatch(request.url.path):
                return await call_next(request)

        # W2-4 PR-C: a signed-out visitor may POST to the recording media-token
        # endpoint to mint an anonymous playback token. A guest has no session
        # cookie and therefore cannot present a CSRF token by construction —
        # and CSRF only defends against an attacker riding a victim's ambient
        # session cookie, which a cookie-less request has none of. The
        # exemption is scoped to the cookie-less case ONLY: an authenticated
        # caller (session cookie present) still requires a valid CSRF token.
        if (
            ANON_MEDIA_TOKEN_ISSUE_PATTERN.fullmatch(request.url.path) is not None
            and not request.cookies.get(self.config.cookie_name)
        ):
            return await call_next(request)

        session_id = request.cookies.get(self.config.cookie_name)
        token = request.headers.get(self.config.header_name)
        if not session_id or not token:
            return _csrf_failure("missing CSRF credentials")

        try:
            verify_csrf_token(
                token,
                session_id=session_id,
                session_secret=self.config.session_secret,
                ttl_seconds=self.config.ttl_seconds,
            )
        except CsrfTokenExpiredError:
            return _csrf_failure("CSRF token expired")
        except CsrfError:
            return _csrf_failure("CSRF verification failed")

        return await call_next(request)


def _csrf_failure(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error_code": "csrf_failed", "message": message},
    )


__all__ = [
    "CSRF_HEADER_NAME",
    "DEFAULT_CSRF_TTL_SECONDS",
    "EXEMPT_PATHS",
    "WEB_API_PREFIX",
    "CsrfConfig",
    "CsrfError",
    "CsrfMiddleware",
    "CsrfTokenExpiredError",
    "CsrfTokenMalformedError",
    "CsrfTokenMismatchError",
    "issue_csrf_token",
    "verify_csrf_token",
]
