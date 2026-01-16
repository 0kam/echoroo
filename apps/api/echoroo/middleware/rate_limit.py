"""Rate limiting middleware using fastapi-limiter."""

from typing import Any

from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter as RateLimiterDependency

from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings

settings = get_settings()


async def init_rate_limiter() -> None:
    """Initialize FastAPI rate limiter with Redis backend.

    Should be called during application startup.

    Example:
        ```python
        @app.on_event("startup")
        async def startup():
            await init_rate_limiter()
        ```
    """
    redis = await get_redis_connection()
    await FastAPILimiter.init(redis)


async def close_rate_limiter() -> None:
    """Close rate limiter.

    Should be called during application shutdown.

    Example:
        ```python
        @app.on_event("shutdown")
        async def shutdown():
            await close_rate_limiter()
        ```
    """
    await FastAPILimiter.close()


# Pre-configured rate limiters for common endpoints


def login_rate_limiter() -> Any:
    """Rate limiter for login endpoint.

    Returns:
        Rate limiter dependency (5 attempts per minute)

    Example:
        ```python
        @router.post("/auth/login")
        async def login(
            request: Request,
            _: None = Depends(login_rate_limiter())
        ):
            pass
        ```
    """
    return RateLimiterDependency(
        times=settings.RATE_LIMIT_LOGIN_ATTEMPTS,
        seconds=settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
    )


def register_rate_limiter() -> Any:
    """Rate limiter for registration endpoint.

    Returns:
        Rate limiter dependency (3 attempts per hour)

    Example:
        ```python
        @router.post("/auth/register")
        async def register(
            request: Request,
            _: None = Depends(register_rate_limiter())
        ):
            pass
        ```
    """
    return RateLimiterDependency(
        times=settings.RATE_LIMIT_REGISTER_ATTEMPTS,
        seconds=settings.RATE_LIMIT_REGISTER_WINDOW_SECONDS,
    )


def password_reset_rate_limiter() -> Any:
    """Rate limiter for password reset endpoint.

    Returns:
        Rate limiter dependency (3 attempts per hour)

    Example:
        ```python
        @router.post("/auth/password-reset")
        async def password_reset(
            request: Request,
            _: None = Depends(password_reset_rate_limiter())
        ):
            pass
        ```
    """
    return RateLimiterDependency(
        times=settings.RATE_LIMIT_PASSWORD_RESET_ATTEMPTS,
        seconds=settings.RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS,
    )
