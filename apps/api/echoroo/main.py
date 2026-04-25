"""FastAPI application factory and configuration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from echoroo.api.v1 import api_router
from echoroo.api.web_v1 import web_v1_router
from echoroo.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from echoroo.core.redis import close_redis_connection, get_redis_connection
from echoroo.core.settings import get_settings
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
