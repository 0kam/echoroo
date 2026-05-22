"""Forced password change enforcement middleware.

spec/011 §FR-011-204 / §NFR-011-007 / §R8
-----------------------------------------
This middleware is the **atomic swap** replacement for the now-removed
:class:`EmailVerificationEnforcementMiddleware`. Both middlewares are
gates that read ``request.state.principal`` (populated by
:class:`AuthRouterMiddleware`), look up the authenticated user, and
short-circuit the request when a user-state flag is set. We swap them
in a single commit at the same topological position so the LIFO
middleware ordering invariants the rest of the stack relies on are not
perturbed (NFR-011-007).

Behaviour
~~~~~~~~~
When the authenticated principal's underlying ``users`` row has
``must_change_password = true`` the middleware returns ``423 Locked``
with a ``Location: /change-password`` header and JSON body
``{"code": "ERR_PASSWORD_CHANGE_REQUIRED"}`` for every request **other
than** the allowlist below. The allowlist is method-aware (a tuple of
``(METHOD, path)``) to match the spec's precise wording — e.g.
``POST /web-api/v1/auth/change-password`` is allowlisted but ``GET`` on
the same URL is not, so the gate fires before the route handler can
return a 405.

Allowlist (per spec.md FR-011-204):

* ``POST /web-api/v1/auth/change-password`` — the change endpoint itself.
* ``POST /api/v1/auth/change-password`` — v1 mirror.
* ``POST /web-api/v1/auth/logout`` / ``POST /api/v1/auth/logout`` —
  idempotent session termination so the user can escape the gate by
  signing out.
* ``GET /health`` / ``GET /metrics`` — operational liveness probes.
* ``GET /favicon.ico`` — browser-driven asset request that would
  otherwise generate spurious 423s in the network panel.
* ``OPTIONS`` on **any** path — CORS preflight (the gate runs before CORS
  middleware in the LIFO chain, so blocking preflight would break every
  cross-origin XHR including the change-password POST itself).
* ``/static/*`` prefix on **any** method — static assets.

``/web-api/v1/auth/change-password`` is intentionally **not** added to
``PUBLIC_AUTH_PATHS``. The endpoint is fully authenticated (session +
CSRF); the gate lets it through because the user is already
authenticated and being routed to the only screen they may reach
(security review M7).

``/api/v1`` cookie-session bypass closure (Codex R1 NO-GO fix)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
:class:`AuthRouterMiddleware` is configured with
``allow_legacy_session_fallback=True`` so the transitional SvelteKit
frontend can still hit ``/api/v1/*`` with a session cookie (no Bearer
header). On that path the router leaves ``request.state.principal =
None`` and the downstream FastAPI ``Depends(get_current_user)`` chain
takes over identity resolution. **This middleware runs upstream of that
``Depends`` chain**, so an authenticated cookie-only ``/api/v1/*``
caller would arrive here with ``principal=None`` and silently bypass
the 423 gate — that is the bug FR-011-204 ("both ``/web-api/v1`` and
``/api/v1`` mirrors") forbids.

The fix mirrors :class:`JwtSessionVerifier`'s session→user resolution
locally for the ``/api/v1`` cookie-only path:

* Read the session-cookie value (``settings.web_session_cookie_name``),
  treat the value as the refresh-token family UUID, and resolve it via
  the same SQL the router uses (``token_families`` JOIN ``users``
  filtered to ``deleted_at IS NULL``).
* Apply the same 423 short-circuit when ``must_change_password=true``.
* On any failure (missing cookie, invalid UUID, vanished family, soft-
  deleted user) fall through to ``call_next`` so the downstream
  ``Depends`` chain owns the natural 401 — adding a 423 here would leak
  a different error code for a different failure mode.

``/web-api/v1/*`` callers always have their principal resolved by the
router upstream, so we skip the extra session lookup there to avoid
duplicate work.

WebSocket scope
~~~~~~~~~~~~~~~
The application does not currently expose WebSocket routes, but the
middleware future-proofs that surface by closing any incoming WebSocket
connection with code ``1011`` (Internal Error) when the resolved user
carries ``must_change_password = true``. The WebSocket scope is handled
directly via :meth:`__call__` (the parent
:class:`BaseHTTPMiddleware.dispatch` only sees HTTP scopes). For the
WebSocket path :class:`AuthRouterMiddleware` is a
:class:`BaseHTTPMiddleware`, so it does NOT see WebSocket scopes and
does NOT attach a principal. The gate therefore performs the same
extra session-cookie resolution for WebSocket connections as for the
``/api/v1`` HTTP path — closing 1011 only if the resolved user has
``must_change_password=true``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from echoroo.core.database import AsyncSessionLocal
from echoroo.core.settings import get_settings
from echoroo.models.user import User


@dataclass(frozen=True)
class _CookieUserShim:
    """Lightweight stand-in returned by the cookie-fallback path.

    The gate only consults ``must_change_password`` on the resolved
    object; the cookie-fallback query pulls just that column (plus the
    user id and ``deleted_at``) so we avoid a redundant ``SELECT * FROM
    users``. Production callers therefore see two cheap round-trips
    (one cookie → user-state row, one optional 423 emit) instead of
    one full row hydration.
    """

    id: UUID
    must_change_password: bool

ERROR_CODE_PASSWORD_CHANGE_REQUIRED: Final[str] = "ERR_PASSWORD_CHANGE_REQUIRED"

#: Path that the ``Location`` header points at on a 423 response. The
#: SvelteKit route guard (T343) resolves this to the change-password
#: screen on either locale prefix; we do not include the locale here so
#: the header value is locale-agnostic and clients render the redirect
#: into their current locale.
LOCATION_CHANGE_PASSWORD: Final[str] = "/change-password"

#: Method-aware exact-match allowlist. Every other ``(method, path)``
#: combination falls through to the 423 short-circuit when the resolved
#: user has ``must_change_password = true``. Lifted from FR-011-204's
#: spec wording — ``GET /web-api/v1/auth/change-password`` is NOT on the
#: list, so it 423's like any other path.
DEFAULT_ALLOWLIST_METHOD_PATHS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("POST", "/web-api/v1/auth/change-password"),
        ("POST", "/api/v1/auth/change-password"),
        ("POST", "/web-api/v1/auth/logout"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("GET", "/favicon.ico"),
    }
)

#: Backwards-compatible path-only export used by the call-site smoke
#: test (:func:`tests.integration.test_must_change_password_middleware.
#: test_v1_mirrors_present_in_default_allowlist`). Mirrors the second
#: tuple component of :data:`DEFAULT_ALLOWLIST_METHOD_PATHS`. New
#: production callers MUST use the method-aware structure above.
DEFAULT_ALLOWLIST_PATHS: Final[tuple[str, ...]] = tuple(
    sorted({path for _method, path in DEFAULT_ALLOWLIST_METHOD_PATHS})
)

#: Prefix-match allowlist. Any request path that *starts with* one of
#: these strings bypasses the gate regardless of method (matches
#: static-asset routing).
DEFAULT_ALLOWLIST_PREFIXES: Final[tuple[str, ...]] = ("/static/",)

#: URL prefix carved out for the legacy programmatic surface. Requests
#: under this prefix that arrive without a Bearer header (the SvelteKit
#: legacy cookie path) bypass :class:`AuthRouterMiddleware`'s principal
#: resolution and rely on the downstream ``Depends`` chain — which runs
#: AFTER this middleware. The gate therefore performs its own session-
#: cookie resolution for paths under this prefix.
_API_V1_PREFIX: Final[str] = "/api/v1/"


class ForcedPasswordChangeMiddleware(BaseHTTPMiddleware):
    """Block authenticated traffic for users that must change password.

    spec/011 §FR-011-204. Replaces
    :class:`EmailVerificationEnforcementMiddleware` via the atomic swap
    described in §R8 — both middlewares MUST NOT be registered
    simultaneously, and the topological slot in the LIFO middleware
    stack is preserved by the swap.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        session_factory: Any | None = None,
        allowlist_method_paths: Sequence[tuple[str, str]] = tuple(
            DEFAULT_ALLOWLIST_METHOD_PATHS
        ),
        allowlist_prefixes: Sequence[str] = DEFAULT_ALLOWLIST_PREFIXES,
        user_resolver: Callable[[UUID], Awaitable[User | None]] | None = None,
        session_cookie_name: str | None = None,
        session_to_user_resolver: Callable[[str], Awaitable[User | None]] | None = None,
    ) -> None:
        super().__init__(app)
        self.session_factory = session_factory or AsyncSessionLocal
        self.allowlist_method_paths = frozenset(
            (method.upper(), path) for method, path in allowlist_method_paths
        )
        self.allowlist_prefixes = tuple(allowlist_prefixes)
        # ``user_resolver`` is pluggable so fast unit / integration tests
        # can supply an in-memory user lookup without spinning up a real
        # session factory. Production defaults to the session_factory
        # path via :meth:`_default_load_user`.
        self._user_resolver = user_resolver
        # Cookie-session resolution path closes the /api/v1 cookie-only
        # bypass (Codex R1 NO-GO). Cookie name defaults to the value the
        # production settings advertise; tests can supply their own.
        self._session_cookie_name = session_cookie_name or get_settings().web_session_cookie_name
        # Injection seam for tests — the production default reuses the
        # same SQL :class:`JwtSessionVerifier` runs against
        # ``token_families`` JOIN ``users``.
        self._session_to_user_resolver = session_to_user_resolver

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Dispatch HTTP and WebSocket scopes.

        :class:`BaseHTTPMiddleware.__call__` only delegates to
        :meth:`dispatch` for HTTP scopes; WebSocket / lifespan scopes
        fall through to the wrapped app untouched. We intercept the
        WebSocket scope here so a future WebSocket route is protected
        by the same forced-change semantics (FR-011-204 future-proofing).
        """
        if scope["type"] == "websocket":
            await self._dispatch_websocket(scope, receive, send)
            return
        await super().__call__(scope, receive, send)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        method = request.method.upper()
        path = request.url.path

        # OPTIONS preflight always passes — CORS middleware sits outside
        # this one in the LIFO chain and the browser would never reach
        # the change-password POST if preflight 423'd.
        if method == "OPTIONS":
            return await call_next(request)

        if self._is_allowlisted(method, path):
            return await call_next(request)

        principal = getattr(request.state, "principal", None)
        user_id = getattr(principal, "user_id", None) if principal is not None else None

        # Codex R1 NO-GO fix: ``/api/v1/*`` cookie-only callers arrive here
        # with ``principal=None`` because :class:`AuthRouterMiddleware`
        # leaves identity resolution to the downstream ``Depends`` chain
        # via ``allow_legacy_session_fallback=True``. Resolve the session
        # cookie ourselves to close the bypass — FR-011-204 requires the
        # gate cover BOTH ``/web-api/v1`` and ``/api/v1`` mirrors.
        if user_id is None and path.startswith(_API_V1_PREFIX):
            user = await self._resolve_user_from_session_cookie(request)
            if user is not None and bool(getattr(user, "must_change_password", False)):
                return _password_change_required_response()
            # Cookie missing / invalid / soft-deleted user / no
            # must_change_password flag → fall through to ``call_next``
            # so the downstream ``Depends`` chain emits its natural 401
            # (or 200 for a user that simply doesn't need to change).
            return await call_next(request)

        if user_id is None:
            # Anonymous / legacy callers (no principal attached and no
            # session cookie on a programmatic-prefix path) are not the
            # gate's concern — fall through.
            return await call_next(request)

        user = await self._load_user(user_id)
        if user is None:
            # User row vanished between auth router and this hop. We do
            # NOT fail closed here: the auth router already accepted the
            # session, and the downstream handlers will surface their
            # own 401 / 404 in the natural flow. Adding a 423 here would
            # leak a different error code for the same race condition.
            return await call_next(request)

        if not bool(getattr(user, "must_change_password", False)):
            return await call_next(request)

        return _password_change_required_response()

    async def _dispatch_websocket(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Close WebSocket connections with code 1011 for must-change users.

        :class:`AuthRouterMiddleware` is a :class:`BaseHTTPMiddleware`
        and therefore does NOT attach a principal to WebSocket scopes.
        We resolve the caller identity locally — first via
        ``scope["state"]["principal"]`` (tests can inject one) and then
        by falling back to the session-cookie path used by the
        ``/api/v1/*`` HTTP branch. This closes the same bypass on the
        WebSocket surface that the HTTP path closes.

        On any unresolved scope (no principal, no session cookie, soft-
        deleted user, ``must_change_password=false``) we hand control to
        the downstream ASGI app so its own auth logic can run.
        """
        state = scope.get("state") or {}
        principal: Any = None
        if isinstance(state, dict):
            principal = state.get("principal")
        else:  # pragma: no cover — Starlette uses a dict today
            principal = getattr(state, "principal", None)
        user_id = getattr(principal, "user_id", None) if principal is not None else None

        if user_id is None:
            user = await self._resolve_user_from_session_cookie_scope(scope)
            if user is not None and bool(getattr(user, "must_change_password", False)):
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.close", "code": 1011})
                return
            await self.app(scope, receive, send)
            return

        user = await self._load_user(user_id)
        if user is not None and bool(getattr(user, "must_change_password", False)):
            # Per ASGI / RFC 6455: send close frame with code 1011
            # (Internal Error). We accept the handshake first so the
            # close frame carries a status code the client can read.
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1011})
            return
        await self.app(scope, receive, send)

    def _is_allowlisted(self, method: str, path: str) -> bool:
        if (method, path) in self.allowlist_method_paths:
            return True
        return any(path.startswith(prefix) for prefix in self.allowlist_prefixes)

    async def _load_user(self, user_id: UUID) -> User | None:
        if self._user_resolver is not None:
            return await self._user_resolver(user_id)
        return await self._default_load_user(user_id)

    async def _default_load_user(self, user_id: UUID) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(sa.select(User).where(User.id == user_id))
            return result.scalar_one_or_none()

    async def _resolve_user_from_session_cookie(
        self, request: Request
    ) -> User | _CookieUserShim | None:
        """Resolve the session cookie value to a User-like row.

        Mirrors :class:`echoroo.services.session_verification.
        JwtSessionVerifier` so the gate stays in lockstep with the
        production session-decode contract: the cookie value is the
        ``token_families.family_id`` UUID, the join goes through
        ``users``, and soft-deleted users yield ``None``.

        Returns ``None`` on any malformed input — the caller falls
        through to ``call_next`` so the downstream chain emits the
        natural 401 instead of a spurious 423. The production return
        type is :class:`_CookieUserShim` (the column-only stand-in);
        tests can override the resolver and return a real :class:`User`.
        """
        cookie_value = request.cookies.get(self._session_cookie_name)
        return await self._resolve_user_from_session_cookie_value(cookie_value)

    async def _resolve_user_from_session_cookie_scope(
        self, scope: Scope
    ) -> User | _CookieUserShim | None:
        """Resolve the session cookie out of a raw ASGI scope.

        Used by the WebSocket dispatch path where we do not have a
        Starlette :class:`Request` to read the cookie jar from. The
        ASGI cookie header is parsed with :mod:`http.cookies`, matching
        Starlette's own implementation.
        """
        headers = scope.get("headers") or []
        cookie_header: str | None = None
        for raw_name, raw_value in headers:
            try:
                name = raw_name.decode("latin-1").lower()
            except (AttributeError, UnicodeDecodeError):  # pragma: no cover
                continue
            if name == "cookie":
                try:
                    cookie_header = raw_value.decode("latin-1")
                except (AttributeError, UnicodeDecodeError):  # pragma: no cover
                    cookie_header = None
                break
        if not cookie_header:
            return None
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(cookie_header)
        except Exception:  # pragma: no cover — defensive against malformed cookies
            return None
        morsel = jar.get(self._session_cookie_name)
        if morsel is None:
            return None
        return await self._resolve_user_from_session_cookie_value(morsel.value)

    async def _resolve_user_from_session_cookie_value(
        self, cookie_value: str | None
    ) -> User | _CookieUserShim | None:
        """Resolve a session cookie value to a :class:`User`-like row.

        The production path returns a lightweight stand-in carrying just
        the columns the gate needs (``id`` + ``must_change_password``
        plus ``deleted_at``). We deliberately avoid issuing a second
        ``SELECT * FROM users`` here — the cookie→user lookup already
        joins ``users`` to validate the soft-delete state, so pulling
        ``must_change_password`` in the same round-trip saves one DB
        hop per ``/api/v1`` cookie-only request and matches the Codex
        R1 NO-GO ``nit`` recommendation (column-only query).
        """
        if not cookie_value:
            return None
        if self._session_to_user_resolver is not None:
            return await self._session_to_user_resolver(cookie_value)
        try:
            family_uuid = UUID(cookie_value)
        except (TypeError, ValueError):
            return None
        async with self.session_factory() as session:
            row = await session.execute(
                sa.text(
                    "SELECT u.id AS user_id, "
                    "u.must_change_password AS must_change_password, "
                    "u.deleted_at AS deleted_at "
                    "FROM token_families tf "
                    "JOIN users u ON u.id = tf.user_id "
                    # Codex R2 finding: revoked session families must NOT
                    # resolve a user here. Without this clause a
                    # logged-out / rotated cookie could still produce a
                    # 423 ``ERR_PASSWORD_CHANGE_REQUIRED`` response,
                    # contradicting :class:`JwtSessionVerifier.verify`
                    # (services/session_verification.py) which rejects
                    # revoked families with a 401. Keep this WHERE
                    # clause aligned with the verifier so revoked
                    # cookies fall through to the downstream
                    # ``Depends(get_current_user)`` 401 path instead
                    # of being upgraded to 423.
                    "WHERE tf.family_id = :family_id "
                    "AND tf.revoked_at IS NULL"
                ),
                {"family_id": family_uuid},
            )
            mapping = row.mappings().first()
            if mapping is None:
                return None
            if mapping["deleted_at"] is not None:
                # Soft-deleted users get no live session — match the
                # JwtSessionVerifier contract.
                return None
            raw_user_id = mapping["user_id"]
            if isinstance(raw_user_id, UUID):
                user_id = raw_user_id
            else:
                try:
                    user_id = UUID(str(raw_user_id))
                except (TypeError, ValueError):
                    return None
            # Build a transient stand-in so the gate's downstream
            # ``getattr(user, "must_change_password", False)`` check
            # works without a second ``SELECT``. We do NOT instantiate
            # the real :class:`User` ORM model because attaching a
            # detached User to no session can confuse callers that
            # later expect SQLAlchemy state — a duck-typed shim is the
            # narrowest contract.
            return _CookieUserShim(
                id=user_id,
                must_change_password=bool(mapping["must_change_password"]),
            )


def _password_change_required_response() -> JSONResponse:
    """Build the 423 Locked response per FR-011-204."""
    return JSONResponse(
        status_code=423,
        headers={"Location": LOCATION_CHANGE_PASSWORD},
        content={
            "code": ERROR_CODE_PASSWORD_CHANGE_REQUIRED,
            "detail": "Password change required",
        },
    )


__all__ = [
    "DEFAULT_ALLOWLIST_METHOD_PATHS",
    "DEFAULT_ALLOWLIST_PATHS",
    "DEFAULT_ALLOWLIST_PREFIXES",
    "ERROR_CODE_PASSWORD_CHANGE_REQUIRED",
    "ForcedPasswordChangeMiddleware",
    "LOCATION_CHANGE_PASSWORD",
]
