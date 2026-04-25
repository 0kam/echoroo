"""URL-prefix-aware authentication middleware (FR-077, FR-099, T070).

This middleware sits in front of every request and resolves the caller
into a :class:`Principal` dropped onto ``request.state.principal``. It
deliberately splits work by URL prefix:

* ``/api/v1/*`` — Programmatic API. Requires
  ``Authorization: Bearer <api-key>``. The API key is hashed and looked
  up in the configured :class:`ApiKeyVerifier`. No cookies, no CSRF.
* ``/web-api/v1/*`` — First-party session API. Requires the session
  cookie. CSRF token enforcement happens in
  :class:`echoroo.middleware.csrf.CsrfMiddleware` (mounted separately).
  The Bearer JWT access token is read from the cookie value.
* Anything else (``/health``, ``/metrics``, ``/docs``, ...) passes
  through with no principal attached.

The middleware does not perform authorisation checks — those belong to
:func:`echoroo.core.permissions.is_allowed`. It only resolves identity.

Failure modes return JSON shaped like every other Echoroo error
response (``error_code`` + ``message``). HTTP status codes:

* **401** — credential missing or invalid.
* **419** — credential signature ok, but ``security_stamp`` was
  rotated (session revocation, FR-055). 419 is the conventional
  "session expired" code used by Echoroo per plan.
* **403** — caller authenticated but blocked at the auth layer (e.g.
  API key revoked, IP not in allowlist).

Dependency injection: the middleware accepts plug-points
(:class:`ApiKeyVerifier`, :class:`SessionVerifier`) so tests can stub
them out without touching the real DB / Redis. The Phase 3 wiring
provides production implementations.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, Protocol
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from echoroo.core.auth import (
    AccessTokenClaims,
    InvalidTokenError,
    StaleTokenError,
    verify_access_token,
)
from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROGRAMMATIC_PREFIX: Final[str] = "/api/v1"
SESSION_PREFIX: Final[str] = "/web-api/v1"

DEFAULT_SESSION_COOKIE: Final[str] = "session_id"
DEFAULT_ACCESS_COOKIE: Final[str] = "access_token"

STATUS_SESSION_STALE: Final[int] = 419
"""Echoroo convention: 419 means session was revoked (security_stamp rotated)."""


# ---------------------------------------------------------------------------
# Principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """Resolved caller identity, attached to ``request.state.principal``.

    Attributes:
        user_id: Authenticated user's UUID. ``None`` only on anonymous
            requests against public endpoints.
        security_stamp: The user's stamp, copied from the token. Phase 3
            permission checks compare it against the live DB value.
        api_key_id: Set only when the caller authenticated with an API
            key. ``None`` for first-party session callers.
        scopes: Granted permission scopes — for API keys, the persisted
            ``granted_permissions`` list. For session callers, an empty
            tuple (full session permissions are computed downstream).
        auth_kind: ``"api_key"`` or ``"session"``.
    """

    user_id: UUID | None
    security_stamp: str | None
    api_key_id: UUID | None
    scopes: tuple[str, ...]
    auth_kind: str

    @classmethod
    def for_session(
        cls,
        *,
        user_id: UUID,
        security_stamp: str,
    ) -> Principal:
        return cls(
            user_id=user_id,
            security_stamp=security_stamp,
            api_key_id=None,
            scopes=(),
            auth_kind="session",
        )

    @classmethod
    def for_api_key(
        cls,
        *,
        user_id: UUID,
        api_key_id: UUID,
        scopes: tuple[str, ...],
    ) -> Principal:
        return cls(
            user_id=user_id,
            security_stamp=None,
            api_key_id=api_key_id,
            scopes=scopes,
            auth_kind="api_key",
        )


# ---------------------------------------------------------------------------
# Verifier protocols (Phase 3 supplies real implementations)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiKeyRecord:
    """Persisted state of an API key after secret-hash matching."""

    api_key_id: UUID
    user_id: UUID
    granted_permissions: tuple[str, ...]


class ApiKeyVerifier(Protocol):
    """Lookup interface for API key verification.

    The implementation MUST:

    * Look up the key prefix to find the row.
    * Constant-time compare the hashed secret against
      :attr:`ApiKeyRecord.api_key_id`'s persisted hash.
    * Return ``None`` if the key is unknown, expired, or revoked.
    """

    async def verify(self, raw_key: str) -> ApiKeyRecord | None: ...


class SessionVerifier(Protocol):
    """Lookup interface for first-party session verification.

    Returns the live ``security_stamp`` for the user the session belongs
    to, or ``None`` if the session is unknown / expired. The middleware
    cross-checks that stamp against the JWT's ``ss`` claim.
    """

    async def verify(self, session_id: str) -> tuple[UUID, str] | None: ...


# ---------------------------------------------------------------------------
# API key hashing (TODO: KMS HMAC in Phase 3)
# ---------------------------------------------------------------------------


def hash_api_key_secret(raw_secret: str) -> str:
    """Return the canonical hash of an API key secret.

    NOTE(Phase 3): switch to KMS-backed HMAC (FR-091b). For Phase 2.6
    smoke tests we use SHA-256 with a per-deployment salt added by the
    caller. Returning hex keeps storage stable and readable.
    """
    return hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string equality used by API key verifiers."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class AuthRouterConfig:
    """Configuration for :class:`AuthRouterMiddleware`.

    Attributes:
        api_key_verifier: Protocol implementation for ``/api/v1/*``.
        session_verifier: Protocol implementation for ``/web-api/v1/*``.
        programmatic_prefix: URL prefix that triggers Bearer API key auth.
        session_prefix: URL prefix that triggers cookie / JWT auth.
        session_cookie_name: Cookie carrying the session id.
        access_cookie_name: Cookie carrying the JWT access token.
        require_auth_paths: Extra prefixes that MUST be authenticated.
            Outside these, missing credentials pass through (anonymous).
        public_path_allowlist: Tuple of prefixes that are always public,
            even if they fall under one of the protected prefixes.
    """

    api_key_verifier: ApiKeyVerifier | None = None
    session_verifier: SessionVerifier | None = None
    programmatic_prefix: str = PROGRAMMATIC_PREFIX
    session_prefix: str = SESSION_PREFIX
    session_cookie_name: str = DEFAULT_SESSION_COOKIE
    access_cookie_name: str = DEFAULT_ACCESS_COOKIE
    # Phase 2.10 #6: source the allowlist from the shared
    # ``core.auth_paths.PUBLIC_AUTH_PATHS`` constant so the auth router
    # and the CSRF middleware cannot drift apart. Adding a new public
    # auth endpoint must update the constant in one place.
    public_path_allowlist: tuple[str, ...] = field(
        default_factory=lambda: PUBLIC_AUTH_PATHS
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuthRouterMiddleware(BaseHTTPMiddleware):
    """Resolve caller identity by URL prefix and attach to request.state."""

    def __init__(self, app: ASGIApp, config: AuthRouterConfig) -> None:
        super().__init__(app)
        self.config = config

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        # Public allowlist: skip credential checks altogether.
        # Phase 2.11 P0-b: match exactly (no startswith). The previous
        # prefix match would let an attacker (or a future maintainer who
        # adds e.g. ``/web-api/v1/auth/login-history``) bypass auth
        # because the new path startswith the allowlisted ``/login``.
        # Exact match is also the convention used by CsrfMiddleware via
        # ``is_public_auth_path``; keeping the two middlewares in sync
        # closes the door on auth-vs-CSRF drift bugs.
        if path in self.config.public_path_allowlist:
            request.state.principal = None
            return await call_next(request)

        if path.startswith(self.config.programmatic_prefix):
            result = await self._authenticate_api_key(request)
        elif path.startswith(self.config.session_prefix):
            result = await self._authenticate_session(request)
        else:
            request.state.principal = None
            return await call_next(request)

        if isinstance(result, Response):
            return result

        request.state.principal = result
        return await call_next(request)

    # -- API key (programmatic) -------------------------------------------

    async def _authenticate_api_key(
        self, request: Request
    ) -> Principal | Response:
        verifier = self.config.api_key_verifier
        if verifier is None:
            return _auth_failure(401, "auth_unavailable", "API key verifier not configured")

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return _auth_failure(
                401, "auth_required", "Bearer API key required for /api/v1/*"
            )
        raw_key = auth_header.split(" ", 1)[1].strip()
        if not raw_key:
            return _auth_failure(401, "auth_required", "Empty bearer credentials")

        record = await verifier.verify(raw_key)
        if record is None:
            return _auth_failure(401, "auth_invalid", "API key invalid or revoked")

        return Principal.for_api_key(
            user_id=record.user_id,
            api_key_id=record.api_key_id,
            scopes=tuple(record.granted_permissions),
        )

    # -- Session (first-party) --------------------------------------------

    async def _authenticate_session(
        self, request: Request
    ) -> Principal | Response:
        verifier = self.config.session_verifier
        if verifier is None:
            return _auth_failure(
                401, "auth_unavailable", "Session verifier not configured"
            )

        session_id = request.cookies.get(self.config.session_cookie_name)
        access_token = request.cookies.get(
            self.config.access_cookie_name
        ) or self._extract_bearer(request)
        if not session_id or not access_token:
            return _auth_failure(
                401, "auth_required", "Session cookie + access token required"
            )

        live = await verifier.verify(session_id)
        if live is None:
            return _auth_failure(401, "auth_invalid", "Session unknown or expired")
        live_user_id, live_stamp = live

        try:
            claims: AccessTokenClaims = verify_access_token(
                access_token, current_security_stamp=live_stamp
            )
        except StaleTokenError:
            return _auth_failure(
                STATUS_SESSION_STALE,
                "session_revoked",
                "Session has been revoked; please log in again",
            )
        except InvalidTokenError:
            return _auth_failure(401, "auth_invalid", "Access token invalid")

        if claims.user_id != live_user_id:
            return _auth_failure(
                401, "auth_mismatch", "Session and token user mismatch"
            )

        return Principal.for_session(
            user_id=claims.user_id, security_stamp=claims.security_stamp
        )

    @staticmethod
    def _extract_bearer(request: Request) -> str | None:
        """Fallback: some browser clients send the JWT as Bearer too."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header.split(" ", 1)[1].strip() or None
        return None


def _auth_failure(status: int, code: str, message: str) -> JSONResponse:
    headers: dict[str, str] = {}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={"error_code": code, "message": message},
    )


__all__ = [
    "ApiKeyRecord",
    "ApiKeyVerifier",
    "AuthRouterConfig",
    "AuthRouterMiddleware",
    "DEFAULT_ACCESS_COOKIE",
    "DEFAULT_SESSION_COOKIE",
    "PROGRAMMATIC_PREFIX",
    "Principal",
    "SESSION_PREFIX",
    "SessionVerifier",
    "STATUS_SESSION_STALE",
    "constant_time_eq",
    "hash_api_key_secret",
]
