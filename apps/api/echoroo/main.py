"""FastAPI application factory and configuration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

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
from echoroo.middleware.auth_router import AuthRouterConfig, AuthRouterMiddleware
from echoroo.middleware.csrf import CsrfConfig, CsrfMiddleware
from echoroo.middleware.logging import RequestLoggingMiddleware
from echoroo.middleware.rate_limit import close_rate_limiter, init_rate_limiter
from echoroo.middleware.security import (
    SecurityHeadersMiddleware,
    get_development_cors_config,
    get_production_cors_config,
    get_security_config_for_environment,
)
from echoroo.middleware.two_factor_enforcement import TwoFactorEnforcementMiddleware
from echoroo.services.session_verification import (
    JwtSessionVerifier,
    StubApiKeyVerifier,
)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:  # noqa: ARG001
    """Application lifespan events.

    Handles startup and shutdown tasks like Redis initialization.

    Args:
        app: FastAPI application instance (required by FastAPI signature)
    """
    # Startup
    await get_redis_connection()
    await init_rate_limiter()
    yield
    # Shutdown
    await close_rate_limiter()
    await close_redis_connection()


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI application instance

    Example:
        ```python
        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=8000)
        ```
    """
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
        ),
    )
    app.add_middleware(TwoFactorEnforcementMiddleware)
    # NOTE: ``TwoFactorEnforcementMiddleware`` only enforces on the
    # ``/web-api/v1/*`` first-party session surface (its
    # ``DEFAULT_ENFORCEMENT_PREFIX``). The ``/api/v1/*`` programmatic
    # surface is deliberately left out until Phase 15 task **T155b**
    # wires the real :class:`ApiKeyVerifier` and switches the auth
    # router's ``programmatic_prefix`` back to ``/api/v1``. See the
    # module docstring of ``two_factor_enforcement`` for the full
    # rationale.

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
    # ``/web-api/v1/auth/logout`` is added to the auth-router allowlist
    # because it is the one session-management endpoint that operates
    # purely off the session cookie + CSRF token — it intentionally
    # does NOT carry an access JWT (the user is logging out, after
    # all). It is *not* in ``PUBLIC_AUTH_PATHS`` so CSRF enforcement
    # still applies.
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
    )
    app.add_middleware(
        AuthRouterMiddleware,
        config=AuthRouterConfig(
            api_key_verifier=StubApiKeyVerifier(),
            session_verifier=JwtSessionVerifier(AsyncSessionLocal),
            programmatic_prefix="/__auth_router_disabled_until_phase15__",
            session_cookie_name=settings.web_session_cookie_name,
            public_path_allowlist=auth_router_allowlist,
            public_path_prefix_allowlist=auth_router_public_prefixes,
            public_path_nested_allowlist=auth_router_public_nested,
        ),
    )

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
