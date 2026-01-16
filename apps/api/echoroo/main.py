"""FastAPI application factory and configuration."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from echoroo.api.v1 import api_router
from echoroo.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from echoroo.core.redis import close_redis_connection, get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.middleware.rate_limit import close_rate_limiter, init_rate_limiter

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

    # Request logging middleware
    # TODO: Add RequestLoggingMiddleware here
    # from echoroo.middleware.logging import RequestLoggingMiddleware
    # app.add_middleware(RequestLoggingMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Exception handlers
    app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]

    # Include API routers
    app.include_router(api_router)

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
