"""FastAPI application factory and configuration."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from echoroo.api.v1 import api_router
from echoroo.api.web_v1 import web_v1_router
from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS
from echoroo.core.database import AsyncSessionLocal
from echoroo.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from echoroo.core.redis import close_redis_connection, get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.middleware.api_key_ip_enforcement import DbIpEnforcer
from echoroo.middleware.auth_router import AuthRouterConfig, AuthRouterMiddleware
from echoroo.middleware.csrf import CsrfConfig, CsrfMiddleware
from echoroo.middleware.forced_password_change import (
    ForcedPasswordChangeMiddleware,
)
from echoroo.middleware.logging import RequestLoggingMiddleware
from echoroo.middleware.no_store_setup import NoStoreSetupMiddleware
from echoroo.middleware.rate_limit import close_rate_limiter, init_rate_limiter
from echoroo.middleware.redaction import RedactionMiddleware
from echoroo.middleware.security import (
    SecurityHeadersMiddleware,
    get_development_cors_config,
    get_production_cors_config,
    get_security_config_for_environment,
)
from echoroo.middleware.two_factor_enforcement import TwoFactorEnforcementMiddleware
from echoroo.observability.sentry import init_sentry
from echoroo.services.api_key_verification import DbApiKeyVerifier
from echoroo.services.session_verification import (
    JwtSessionVerifier,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# spec/011 T710 — initialise Sentry telemetry redaction hook BEFORE
# ``create_app`` runs so any exception raised during app construction
# is captured + scrubbed. ``init_sentry`` is a no-op when ``SENTRY_DSN``
# is unset or ``sentry-sdk`` is not installed (the zero-email
# deployment persona's default), so the import is always safe.
init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Application lifespan events.

    Handles startup and shutdown tasks like Redis initialization.

    Args:
        app: FastAPI application instance (required by FastAPI signature)
    """
    # Startup
    if settings.TEST_MODE:
        logger.warning(
            "TEST_MODE is enabled, 2FA shared-secret bypass is ACTIVE. "
            "DO NOT use in production. ENVIRONMENT=%s",
            settings.ENVIRONMENT,
        )
    await get_redis_connection()
    await init_rate_limiter()
    yield
    # Shutdown
    await close_rate_limiter()
    await close_redis_connection()


def create_app(*, session_factory: Any | None = None) -> FastAPI:
    """Create and configure FastAPI application.

    Args:
        session_factory: Optional async session factory used by the
            middleware-level verifiers (:class:`DbApiKeyVerifier`,
            :class:`JwtSessionVerifier`, :class:`DbIpEnforcer`). When
            ``None`` (production default) the module-global
            :data:`echoroo.core.database.AsyncSessionLocal` is used,
            which is bound to the production engine. Tests inject their
            own NullPool-backed factory so the middleware verifiers run
            on the same event loop / engine as the test ``get_db``
            override — without this, asyncpg surfaces a
            ``RuntimeError: ... attached to a different loop`` whenever
            a positive-path API-key request reaches the middleware.

    Returns:
        Configured FastAPI application instance

    Example:
        ```python
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=8000)
        ```
    """
    middleware_session_factory = (
        session_factory if session_factory is not None else AsyncSessionLocal
    )
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Bird sound recognition and analysis platform API",
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # Request logging middleware - structured logging with correlation IDs
    app.add_middleware(RequestLoggingMiddleware)

    # Security headers middleware
    security_config = get_security_config_for_environment(settings.ENVIRONMENT)
    app.add_middleware(SecurityHeadersMiddleware, config=security_config)

    # CORS middleware - use environment-specific configuration
    if settings.ENVIRONMENT in ("production", "staging"):
        cors_config = get_production_cors_config(settings.ALLOWED_ORIGINS)
    else:
        cors_config = get_development_cors_config(settings.ALLOWED_ORIGINS)

    app.add_middleware(
        CORSMiddleware,
        **cors_config,
    )

    app.add_middleware(
        CsrfMiddleware,
        config=CsrfConfig(
            session_secret=settings.web_session_secret,
            protected_prefix="/web-api/v1",
            cookie_name=settings.web_session_cookie_name,
            ttl_seconds=settings.web_csrf_ttl_seconds,
        ),
    )
    # Phase 15 T155b: 2FA enforcement now covers BOTH the first-party
    # session surface (``/web-api/v1/*``) AND the programmatic surface
    # (``/api/v1/*``). API key verification (wired below via
    # :class:`DbApiKeyVerifier`) populates ``request.state.principal``
    # with the API key's owner ``user_id``; the enrollment / cooldown
    # gates then read the same ``users`` row used by session callers.
    # Anonymous fall-through (cookie-only legacy callers — see
    # ``allow_legacy_session_fallback``) is unaffected because the
    # middleware short-circuits when ``principal is None``.
    app.add_middleware(
        TwoFactorEnforcementMiddleware,
        enforcement_prefixes=("/web-api/v1/", "/api/v1/"),
    )

    # spec/011 §FR-011-204 / §NFR-011-007 / §R8 — atomic swap.
    # ``ForcedPasswordChangeMiddleware`` replaces the now-removed
    # ``EmailVerificationEnforcementMiddleware`` at the SAME topological
    # position so the existing LIFO ordering invariants are preserved:
    # this hop runs after :class:`AuthRouterMiddleware` (so
    # ``request.state.principal`` is populated) and before
    # :class:`TwoFactorEnforcementMiddleware`. The two middlewares MUST
    # NOT both be live gates simultaneously — this commit registers the
    # new one and removes the old registration in a single atomic step.
    app.add_middleware(
        ForcedPasswordChangeMiddleware,
        session_factory=middleware_session_factory,
    )

    # AuthRouter must run BEFORE TwoFactorEnforcement so the latter can
    # read ``request.state.principal``. Starlette's ``add_middleware``
    # is LIFO — the last call wraps the chain outermost — so add the
    # auth router AFTER the 2FA enforcement middleware here.
    #
    # ``programmatic_prefix`` is set to a sentinel that does not match
    # any real path so ``/api/v1/*`` continues to authenticate via the
    # legacy :mod:`echoroo.middleware.auth` Depends helpers (Phase 15
    # T950+ / T155b swaps in the real KMS-backed API key verifier and
    # flips this prefix back to ``/api/v1``).
    #
    # ``/web-api/v1/auth/logout`` is a CSRF-exempt session-management
    # endpoint: it lives in :data:`PUBLIC_AUTH_PATHS` (so the CSRF
    # middleware skips it — see the OWASP-aligned rationale documented
    # in ``echoroo/core/auth_paths.py``) AND in this auth-router
    # allowlist (so the cookie-required guard does not block calls made
    # without a live session, which is required for idempotent client
    # recovery from partial cookie eviction). The two allowlists are
    # intentionally kept in sync so logout is uniformly exempt across
    # both middlewares; any future tightening must update both sides at
    # once.
    auth_router_allowlist = (
        *PUBLIC_AUTH_PATHS,
        "/web-api/v1/auth/logout",
    )
    # Phase 5 (US1, FR-016): allow Guest GET on the project read surface so a
    # signed-out visitor can browse Public + Active projects. The Stage-1
    # permission gate then enforces visibility/status — Restricted projects
    # respond 404 to Guests (FR-018, anti-enumeration).
    auth_router_public_prefixes: tuple[tuple[str, frozenset[str]], ...] = (
        ("/web-api/v1/projects", frozenset({"GET"})),
        # spec/011 FR-011-105 — TOKEN_AUTH_ONLY resolver. The {token}
        # segment is matched as a single segment after the prefix
        # ``/web-api/v1/auth/invitations``. The structural matcher
        # accepts only the bare ``{prefix}/{single-segment}`` shape so
        # ``/accept`` (deeper) is intentionally handled by the nested
        # allowlist below.
        ("/web-api/v1/auth/invitations", frozenset({"GET"})),
    )
    # Phase 5 polish round 4 (致命 1): allow Guest GET on the project recording
    # list ``GET /web-api/v1/projects/{id}/recordings`` so signed-out visitors
    # can wire ``<audio>`` elements on the public detail page. The existing
    # Stage-1 gate inside ``list_public_recordings`` enforces visibility/status
    # — Restricted projects respond 404 (FR-018) and matrix-denied authenticated
    # callers respond 403. Other nested paths (``/members``,
    # ``/license-history``, future endpoints) are intentionally NOT added here
    # so they keep falling through to the cookie-required session
    # authenticator.
    auth_router_public_nested: tuple[
        tuple[str, str, frozenset[str]], ...
    ] = (
        ("/web-api/v1/projects", "/recordings", frozenset({"GET"})),
        # spec/011 FR-011-105..107 — TOKEN_AUTH_ONLY public-token surface.
        # ``GET /web-api/v1/auth/invitations/{token}`` (resolver) and
        # ``POST /web-api/v1/auth/invitations/{token}/accept`` (accept).
        # Both endpoints honour an OPTIONAL session cookie — when present
        # the handler reads ``current_user`` to populate the existing-user
        # branch; when absent the request passes through anonymously and
        # the signup branch fires. The auth router needs to admit BOTH
        # paths under the same allowlist (one via the bare-token GET, one
        # via the ``/accept`` suffix POST). The structural matcher already
        # allows the prefix matcher to handle the bare token; the nested
        # entry below picks up the ``/accept`` suffix.
        (
            "/web-api/v1/auth/invitations",
            "/accept",
            frozenset({"POST"}),
        ),
    )
    # Phase 15 T155b: programmatic prefix flipped back to ``/api/v1``.
    # ``DbApiKeyVerifier`` (wired below) resolves Bearer credentials
    # against the ``api_keys`` table. The ``allow_legacy_session_fallback``
    # flag preserves the transitional period where the SvelteKit frontend
    # still issues cookie-authenticated calls against ``/api/v1/*``: when
    # no Bearer header is present the auth router leaves ``principal``
    # empty and the legacy ``Depends(get_current_user)`` chain remains
    # responsible for authentication.
    app.add_middleware(
        AuthRouterMiddleware,
        config=AuthRouterConfig(
            api_key_verifier=DbApiKeyVerifier(middleware_session_factory),
            session_verifier=JwtSessionVerifier(middleware_session_factory),
            # Phase 17 A-3 (FR-077, FR-081): enforce per-key
            # ``allowed_ip_cidrs`` against the caller's source IP and
            # auto-revoke after the third violation. ``DbIpEnforcer``
            # opens a fresh session per request so the audit write can
            # upgrade to SERIALIZABLE isolation cleanly.
            ip_enforcer=DbIpEnforcer(middleware_session_factory),
            # Phase 17 A-3 Codex Major 1: trusted reverse-proxy CIDRs
            # control which socket peers are allowed to inject XFF
            # headers. Empty by default → XFF never trusted; set
            # ``ECHOROO_TRUSTED_PROXY_CIDRS=`` to a CIDR list when
            # deploying behind a reverse proxy (nginx, ALB, Cloudflare).
            trusted_proxy_cidrs=tuple(settings.TRUSTED_PROXY_CIDRS),
            programmatic_prefix="/api/v1",
            session_cookie_name=settings.web_session_cookie_name,
            public_path_allowlist=auth_router_allowlist,
            public_path_prefix_allowlist=auth_router_public_prefixes,
            public_path_nested_allowlist=auth_router_public_nested,
            allow_legacy_session_fallback=True,
        ),
    )
    app.add_middleware(NoStoreSetupMiddleware)

    # spec/011 T711 — RedactionMiddleware MUST be the outermost
    # middleware (registered LAST per Starlette LIFO) so it sees the
    # FINAL response payload, including any handler-emitted JSON that
    # carries an ``invitation_url`` / ``temporary_password`` /
    # ``step_up_token`` / ``signed_token_envelope`` field. Scrubbing
    # the body after this point would happen too late for the
    # structured-log layer; scrubbing it earlier (before all auth /
    # CSRF / business handlers run) would miss handler-emitted
    # responses. See ``echoroo/middleware/redaction.py`` for the
    # full rationale.
    app.add_middleware(RedactionMiddleware)

    # Exception handlers
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]

    # Include API routers
    app.include_router(api_router)
    app.include_router(web_v1_router)

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            Health status
        """
        return {"status": "healthy"}

    return app


# Create application instance
app = create_app()
