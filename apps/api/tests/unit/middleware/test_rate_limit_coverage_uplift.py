"""spec/011 Step 7c coverage uplift — ``echoroo.middleware.rate_limit``.

The module dropped from ~85% to ~84.2% in spec/011 Step 10 when
``password_reset_rate_limiter`` was deleted alongside the removed
self-service password-reset endpoints (T128/T129). The remaining
factory functions (``login_rate_limiter``, ``register_rate_limiter``,
``upload_session_create_rate_limiter``, ``upload_session_complete_rate_limiter``)
plus ``init_rate_limiter`` / ``close_rate_limiter`` need direct exercise
to push back above 85%.

These are simple factory tests: each factory must return a non-None
dependency object, confirming the FastAPI-Limiter wire-up is intact.
``init_rate_limiter`` / ``close_rate_limiter`` are tested via mocks so
no live Redis is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from echoroo.middleware.rate_limit import (
    close_rate_limiter,
    init_rate_limiter,
    login_rate_limiter,
    register_rate_limiter,
    upload_session_complete_rate_limiter,
    upload_session_create_rate_limiter,
)

# ---------------------------------------------------------------------------
# Rate-limiter factory functions — return a non-None dependency
# ---------------------------------------------------------------------------


def test_login_rate_limiter_returns_dependency() -> None:
    """login_rate_limiter() must return a non-None callable/dependency."""
    dep = login_rate_limiter()
    assert dep is not None


def test_register_rate_limiter_returns_dependency() -> None:
    """register_rate_limiter() must return a non-None callable/dependency."""
    dep = register_rate_limiter()
    assert dep is not None


def test_upload_session_create_rate_limiter_returns_dependency() -> None:
    """upload_session_create_rate_limiter() must return a non-None callable/dependency."""
    dep = upload_session_create_rate_limiter()
    assert dep is not None


def test_upload_session_complete_rate_limiter_returns_dependency() -> None:
    """upload_session_complete_rate_limiter() must return a non-None callable/dependency."""
    dep = upload_session_complete_rate_limiter()
    assert dep is not None


# ---------------------------------------------------------------------------
# init_rate_limiter / close_rate_limiter lifecycle (mocked Redis)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_init_rate_limiter_calls_fastapi_limiter_init() -> None:
    """init_rate_limiter sets up FastAPILimiter with the Redis connection."""
    mock_redis = MagicMock()
    mock_init = AsyncMock()

    with (
        patch(
            "echoroo.middleware.rate_limit.get_redis_connection",
            new=AsyncMock(return_value=mock_redis),
        ),
        patch(
            "echoroo.middleware.rate_limit.FastAPILimiter.init",
            new=mock_init,
        ),
    ):
        await init_rate_limiter()

    mock_init.assert_awaited_once_with(mock_redis)


@pytest.mark.asyncio
async def test_close_rate_limiter_calls_fastapi_limiter_close() -> None:
    """close_rate_limiter delegates to FastAPILimiter.close()."""
    mock_close = AsyncMock()

    with patch(
        "echoroo.middleware.rate_limit.FastAPILimiter.close",
        new=mock_close,
    ):
        await close_rate_limiter()

    mock_close.assert_awaited_once()
