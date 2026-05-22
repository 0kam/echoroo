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


# spec/011 Step 10 (T128/T129) — ``password_reset_rate_limiter`` was
# removed alongside the deleted self-service ``/auth/password-reset/*``
# endpoints (T119). The admin-mediated replacement
# (``services/admin_password_reset.py``) runs behind the admin step-up
# gate and does not need a separate per-IP limiter; its abuse surface
# is bounded by the operator allowlist + audit chain.


def upload_session_create_rate_limiter() -> Any:
    """Rate limiter for upload session creation endpoint.

    Returns:
        Rate limiter dependency (10 attempts per hour)

    Example:
        ```python
        @router.post("/upload-sessions")
        async def create_upload_session(
            request: Request,
            _: None = Depends(upload_session_create_rate_limiter())
        ):
            pass
        ```
    """
    return RateLimiterDependency(
        times=settings.RATE_LIMIT_UPLOAD_SESSION_CREATE_ATTEMPTS,
        seconds=settings.RATE_LIMIT_UPLOAD_SESSION_CREATE_WINDOW_SECONDS,
    )


def upload_session_complete_rate_limiter() -> Any:
    """Rate limiter for upload session completion endpoint.

    Returns:
        Rate limiter dependency (20 attempts per hour)

    Example:
        ```python
        @router.post("/upload-sessions/{id}/complete")
        async def complete_upload_session(
            request: Request,
            _: None = Depends(upload_session_complete_rate_limiter())
        ):
            pass
        ```
    """
    return RateLimiterDependency(
        times=settings.RATE_LIMIT_UPLOAD_SESSION_COMPLETE_ATTEMPTS,
        seconds=settings.RATE_LIMIT_UPLOAD_SESSION_COMPLETE_WINDOW_SECONDS,
    )
