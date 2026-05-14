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
import re
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

API_KEY_NAMESPACE: Final[str] = "echoroo_"
"""Wire namespace for Echoroo-issued API keys; mirrors api_key_verification."""

# Phase 15 T155b legacy-fallback sentinel. Returned by
# ``_authenticate_api_key`` when ``allow_legacy_session_fallback`` is
# set and the request has no Bearer header — signals the dispatcher to
# leave ``request.state.principal = None`` so the legacy
# ``Depends(get_current_user)`` cookie chain owns authentication.
_LEGACY_FALLBACK_SENTINEL: Final[object] = object()


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
    # Phase 15 R3 NO-GO new-Major fix: when the API key has a non-NULL
    # ``api_keys.project_id`` value the key is constrained to that
    # project. The gate compares this against ``gate_action(project_id=)``
    # and returns 403 ``api_key_project_scope_mismatch`` on any mismatch.
    # ``None`` for session principals and for API keys without a project
    # binding (i.e. inherit the user's full visibility).
    api_key_project_id: UUID | None = None

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
        project_id: UUID | None = None,
    ) -> Principal:
        return cls(
            user_id=user_id,
            security_stamp=None,
            api_key_id=api_key_id,
            scopes=scopes,
            auth_kind="api_key",
            api_key_project_id=project_id,
        )


# ---------------------------------------------------------------------------
# Verifier protocols (Phase 3 supplies real implementations)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApiKeyRecord:
    """Persisted state of an API key after secret-hash matching.

    Phase 15 R3 NO-GO new-Major fix: ``project_id`` is now part of the
    record so the optional per-key project scope (``api_keys.project_id``)
    propagates through to the gate. ``None`` means the key is not bound
    to any specific project — it follows the owning user's full
    visibility. When ``project_id`` is set, every gate call MUST verify
    that ``gate_action(project_id=...)`` matches; mismatches return 403
    ``api_key_project_scope_mismatch``.

    Phase 17 A-3: ``allowed_ip_cidrs`` now flows through so the outer
    IP enforcement middleware (:mod:`echoroo.middleware.api_key_ip_enforcement`)
    can compare the caller's IP against the persisted CIDR allowlist
    without re-loading the row. ``None`` and ``[]`` both mean "no
    restriction" (allow all source IPs); a non-empty list narrows the
    set to those CIDRs.
    """

    api_key_id: UUID
    user_id: UUID
    granted_permissions: tuple[str, ...]
    project_id: UUID | None = None
    allowed_ip_cidrs: tuple[str, ...] | None = None


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


class IpEnforcer(Protocol):
    """Per-request IP allowlist enforcement plug-in (Phase 17 A-3).

    Implementations inspect the caller's source IP against the persisted
    ``allowed_ip_cidrs`` list, increment ``ip_violation_count`` on
    mismatch, and auto-revoke the key after the third violation
    (FR-077, FR-081). The :class:`AuthRouterMiddleware` invokes the
    enforcer **after** the API-key verifier resolves the row but
    **before** the principal is attached to ``request.state`` so a
    rejected request never reaches the downstream handler.

    Returns ``True`` to allow the request, ``False`` to reject with 403.
    """

    async def enforce(
        self,
        *,
        api_key_id: UUID,
        user_id: UUID,
        allowed_cidrs: tuple[str, ...] | None,
        client_ip: str,
        request_id: str,
        user_agent: str,
    ) -> bool: ...


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
    # Phase 17 A-3 Codex Major 1: trusted reverse-proxy CIDRs. The
    # middleware only honours ``X-Forwarded-For`` when the socket peer
    # falls in one of these CIDRs — empty (the default) means XFF is
    # never trusted. See :func:`select_client_ip` for the right-strip
    # walk. This belongs to the auth router rather than the IP
    # enforcer because the same caller-IP resolution logic is needed
    # whether or not a CIDR allowlist is configured for the key.
    trusted_proxy_cidrs: tuple[str, ...] = ()
    # Phase 17 A-3: optional per-request CIDR allowlist enforcer. When
    # ``None`` the middleware skips IP enforcement entirely (legacy
    # behaviour). The production wiring in :mod:`echoroo.main` injects a
    # :class:`DbIpEnforcer` so the canonical FR-077 / FR-081 contract is
    # always active in deployed environments.
    ip_enforcer: IpEnforcer | None = None
    programmatic_prefix: str = PROGRAMMATIC_PREFIX
    session_prefix: str = SESSION_PREFIX
    session_cookie_name: str = DEFAULT_SESSION_COOKIE
    access_cookie_name: str = DEFAULT_ACCESS_COOKIE
    # Phase 2.10 #6: source the allowlist from the shared
    # ``core.auth_paths.PUBLIC_AUTH_PATHS`` constant so the auth router
    # and the CSRF middleware cannot drift apart. Adding a new public
    # auth endpoint must update the constant in one place.
    public_path_allowlist: tuple[str, ...] = field(default_factory=lambda: PUBLIC_AUTH_PATHS)
    # Phase 5 (FR-016 / US1): Guest-readable prefix + method tuples. When the
    # request path starts with any prefix and the method matches, the
    # middleware sets ``principal=None`` and passes through. Used for the
    # Public-readable Web UI surface (``GET /web-api/v1/projects`` and
    # ``GET /web-api/v1/projects/{id}``) so Guests can resolve Public
    # metadata without a session cookie. The Stage-1 permission gate
    # (:func:`echoroo.core.permissions.is_allowed`) then enforces that the
    # underlying project is actually Public + Active.
    public_path_prefix_allowlist: tuple[tuple[str, frozenset[str]], ...] = field(
        default_factory=tuple
    )
    # Phase 5 polish round 4 (致命 1): explicit nested-suffix allowlist for
    # Guest-readable paths beneath an authenticated prefix. Each tuple is
    # ``(prefix, suffix, methods)`` where ``prefix`` is the collection root
    # (no trailing slash), ``suffix`` is the literal nested segment after
    # ``{id}`` (with leading slash, e.g. ``/recordings``), and ``methods`` is
    # the set of HTTP methods that may pass through anonymously. Matching is
    # strict: ``{prefix}/{[^/]+}{suffix}`` and ``{prefix}/{[^/]+}{suffix}/``.
    # Anything deeper (``/recordings/{id}/audio``) MUST go through the
    # session authenticator path. The companion FlexibleCurrentUser dependency
    # on ``/api/v1/projects/.../audio`` already accepts bearer-less calls for
    # Public + Active projects, so deep audio streams keep working without
    # widening this allowlist.
    public_path_nested_allowlist: tuple[tuple[str, str, frozenset[str]], ...] = field(
        default_factory=tuple
    )
    # Phase 15 T155b: when ``True`` and the request hits the
    # ``programmatic_prefix`` WITHOUT an ``Authorization: Bearer`` header,
    # the middleware leaves ``request.state.principal = None`` and lets
    # the request fall through to the legacy
    # :func:`echoroo.middleware.auth.get_current_user` Depends-based
    # cookie auth path. This preserves the transitional period where the
    # SvelteKit frontend still calls ``/api/v1/*`` with a session cookie:
    # without this flag every cookie-only call would 401 the moment the
    # programmatic prefix is flipped back to ``/api/v1`` and the legacy
    # UI surface would shatter wholesale.
    #
    # When a Bearer header IS present, the request still goes through
    # the API-key verifier — invalid / revoked keys produce the usual
    # 401 ``auth_invalid`` response (no silent downgrade to anonymous).
    #
    # The fallback is intentionally narrow: it only applies to the
    # programmatic prefix and only when the Authorization header is
    # absent / does not start with ``bearer ``. Any malformed Bearer
    # value continues to return 401, matching the strict path used by
    # the session prefix.
    allow_legacy_session_fallback: bool = False


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

        # Surface isolation: an API key-shaped Bearer credential must never be
        # silently downgraded to Guest on the first-party BFF surface, including
        # public-readable GETs such as /web-api/v1/projects.
        if path.startswith(self.config.session_prefix):
            bearer = self._extract_bearer(request)
            if bearer is not None and bearer.startswith(API_KEY_NAMESPACE):
                return _auth_failure(401, "auth_invalid", "API key invalid or revoked")

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

        # Phase 5 / FR-016: prefix + method match for Guest-readable paths.
        # A best-effort soft auth attempt happens INSIDE the gate via the
        # ``OptionalCurrentUser`` Depends — here we only short-circuit the
        # hard cookie-required check when the call is anonymous.
        #
        # IMPORTANT (polish round 3, 重要 2): the Guest allowlist intentionally
        # admits ONLY the collection root (e.g. ``/web-api/v1/projects``) and
        # single-segment detail paths (``/web-api/v1/projects/<id>``). Deeper
        # paths such as ``/web-api/v1/projects/<id>/members`` MUST NOT be
        # auto-allowed, even on GET — every nested resource has its own
        # authorisation surface (members, license-history, etc.) and Guest
        # access for those is decided per-endpoint, not by the router. A
        # naive ``startswith`` check would let those slip through the
        # cookie-required guard the moment such an endpoint is added.
        #
        # Polish round 2 already tightened ``startswith`` against typo paths
        # like ``/web-api/v1/projectsXYZ``; this round narrows the structural
        # match to keep nested routes off the Guest fast-path.
        for allowed_prefix, allowed_methods in self.config.public_path_prefix_allowlist:
            prefix_match = (
                path == allowed_prefix
                or path == f"{allowed_prefix}/"
                or re.fullmatch(rf"{re.escape(allowed_prefix)}/[^/]+/?", path) is not None
            )
            if prefix_match and request.method in allowed_methods:
                # When the caller DID send a session cookie, fall through
                # the normal ``_authenticate_session`` path so they get a
                # proper Principal. Otherwise treat as Guest.
                if path.startswith(self.config.session_prefix) and request.cookies.get(
                    self.config.session_cookie_name
                ):
                    break
                if path.startswith(self.config.session_prefix):
                    request.state.skip_bearer_fallback = True
                request.state.principal = None
                return await call_next(request)

        # Phase 5 polish round 4 (致命 1): explicit nested-suffix allowlist.
        # The structural prefix matcher above intentionally rejects anything
        # deeper than ``{prefix}/{id}``. A tightly-scoped opt-in lives here so
        # the project recording list (``/web-api/v1/projects/{id}/recordings``)
        # can pass through to the OptionalCurrentUser dependency without
        # widening the matcher to allow arbitrary nested paths like
        # ``/members`` or ``/license-history``.
        for (
            nested_prefix,
            nested_suffix,
            nested_methods,
        ) in self.config.public_path_nested_allowlist:
            nested_pattern = rf"{re.escape(nested_prefix)}/[^/]+{re.escape(nested_suffix)}/?"
            if request.method in nested_methods and re.fullmatch(nested_pattern, path) is not None:
                if path.startswith(self.config.session_prefix) and request.cookies.get(
                    self.config.session_cookie_name
                ):
                    break
                if path.startswith(self.config.session_prefix):
                    request.state.skip_bearer_fallback = True
                request.state.principal = None
                return await call_next(request)

        result: Principal | Response | object
        if path.startswith(self.config.programmatic_prefix):
            result = await self._authenticate_api_key(request)
        elif path.startswith(self.config.session_prefix):
            result = await self._authenticate_session(request)
        else:
            request.state.principal = None
            return await call_next(request)

        if isinstance(result, Response):
            return result

        if result is _LEGACY_FALLBACK_SENTINEL:
            # Phase 15 T155b: cookie-only ``/api/v1/*`` request — leave
            # ``principal`` empty so the downstream ``Depends`` chain
            # owns authentication.
            request.state.principal = None
            return await call_next(request)

        assert isinstance(result, Principal)
        request.state.principal = result
        return await call_next(request)

    # -- API key (programmatic) -------------------------------------------

    async def _authenticate_api_key(self, request: Request) -> Principal | Response | object:
        verifier = self.config.api_key_verifier
        if verifier is None:
            return _auth_failure(401, "auth_unavailable", "API key verifier not configured")

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            # Phase 15 T155b transition: when the legacy SvelteKit
            # frontend still calls ``/api/v1/*`` with a session cookie
            # (no Bearer header), let the request fall through to the
            # legacy ``Depends(get_current_user)`` cookie-auth path
            # instead of 401-ing it. The flag is opt-in via
            # :attr:`AuthRouterConfig.allow_legacy_session_fallback` so
            # tests / non-transitional deployments retain the strict
            # Bearer-required behaviour.
            if self.config.allow_legacy_session_fallback:
                # Sentinel: signal the dispatcher to leave
                # ``request.state.principal = None`` so the legacy
                # ``Depends(get_current_user)`` chain runs. Using a
                # ``Principal`` value with ``user_id=None`` would set
                # ``request.state.principal`` to a truthy object and
                # leak the half-resolved identity into downstream
                # middlewares that distinguish ``None`` from
                # "anonymous principal".
                return _LEGACY_FALLBACK_SENTINEL
            return _auth_failure(401, "auth_required", "Bearer API key required for /api/v1/*")
        raw_key = auth_header.split(" ", 1)[1].strip()
        if not raw_key:
            return _auth_failure(401, "auth_required", "Empty bearer credentials")

        record = await verifier.verify(raw_key)
        if record is None:
            return _auth_failure(401, "auth_invalid", "API key invalid or revoked")

        # Phase 17 A-3 (FR-077, FR-081): when a CIDR allowlist is
        # configured AND an IP enforcer is wired, gate the request on
        # source IP before issuing a Principal. Mismatches:
        #   * Increment ``api_keys.ip_violation_count`` (a counter
        #     independent from ``scope_violation_count_10min``).
        #   * After the third violation auto-revoke the key.
        #   * Append a ``platform_audit_log`` row.
        # All three side-effects are owned by the enforcer; the
        # middleware just translates the boolean outcome into a 403.
        enforcer = self.config.ip_enforcer
        if enforcer is not None:
            client_ip = _resolve_client_ip(
                request, trusted_proxy_cidrs=self.config.trusted_proxy_cidrs
            )
            request_id = (
                request.headers.get("X-Request-Id") or request.headers.get("X-Correlation-Id") or ""
            )
            user_agent = request.headers.get("User-Agent", "")
            allowed = await enforcer.enforce(
                api_key_id=record.api_key_id,
                user_id=record.user_id,
                allowed_cidrs=record.allowed_ip_cidrs,
                client_ip=client_ip,
                request_id=request_id,
                user_agent=user_agent,
            )
            if not allowed:
                return _auth_failure(
                    403,
                    "err_ip_not_allowed",
                    "Source IP not in API key allowlist",
                )

        return Principal.for_api_key(
            user_id=record.user_id,
            api_key_id=record.api_key_id,
            scopes=tuple(record.granted_permissions),
            project_id=record.project_id,
        )

    # -- Session (first-party) --------------------------------------------

    async def _authenticate_session(self, request: Request) -> Principal | Response:
        verifier = self.config.session_verifier
        if verifier is None:
            return _auth_failure(401, "auth_unavailable", "Session verifier not configured")

        session_id = request.cookies.get(self.config.session_cookie_name)
        access_token = request.cookies.get(self.config.access_cookie_name) or self._extract_bearer(
            request
        ) or self._extract_media_query_token(request)
        if not session_id or not access_token:
            return _auth_failure(401, "auth_required", "Session cookie + access token required")

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
            return _auth_failure(401, "auth_mismatch", "Session and token user mismatch")

        return Principal.for_session(user_id=claims.user_id, security_stamp=claims.security_stamp)

    @staticmethod
    def _extract_bearer(request: Request) -> str | None:
        """Fallback: some browser clients send the JWT as Bearer too."""
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header.split(" ", 1)[1].strip() or None
        return None

    @staticmethod
    def _extract_media_query_token(request: Request) -> str | None:
        """Allow native media/image elements to authenticate BFF media GETs."""
        if request.method != "GET":
            return None
        if (
            re.fullmatch(
                r"/web-api/v1/projects/[^/]+/recordings/[^/]+/(audio|playback|spectrogram)",
                request.url.path,
            )
            is None
        ):
            return None
        token = request.query_params.get("token")
        return token.strip() if token else None


def _resolve_client_ip(
    request: Request,
    *,
    trusted_proxy_cidrs: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Pick the canonical caller IP from a Starlette request.

    Phase 17 A-3 Codex Major 1: defers to
    :func:`echoroo.middleware.api_key_ip_enforcement.select_client_ip`
    so the trusted-proxy logic is shared between the auth-router shell
    and direct unit tests of the helper. ``X-Forwarded-For`` is only
    honoured when the socket peer (``request.client.host``) is itself
    in ``trusted_proxy_cidrs``; otherwise we use the peer directly.
    This blocks the spoof bypass where an attacker reaches the API
    without going through the proxy and forges
    ``X-Forwarded-For: <allowlisted IP>``.

    Returns an empty string when no source resolves — the IP enforcer
    treats that as "unknown" and fails closed against any non-empty
    allowlist.
    """
    from echoroo.middleware.api_key_ip_enforcement import select_client_ip

    forwarded = request.headers.get("X-Forwarded-For")
    peer = request.client.host if request.client is not None else None
    cidrs = list(trusted_proxy_cidrs) if trusted_proxy_cidrs else []
    return select_client_ip(
        forwarded_for=forwarded,
        remote_addr=peer,
        trusted_proxy_cidrs=cidrs,
    )


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
    "IpEnforcer",
    "PROGRAMMATIC_PREFIX",
    "Principal",
    "SESSION_PREFIX",
    "SessionVerifier",
    "STATUS_SESSION_STALE",
    "constant_time_eq",
    "hash_api_key_secret",
]
