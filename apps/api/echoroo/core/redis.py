"""Redis connection management for rate limiting and caching."""


from redis.asyncio import Redis

from echoroo.core.settings import get_settings

settings = get_settings()

# Global redis connection instance
_redis_client: Redis | None = None


async def get_redis_connection() -> Redis:
    """Get or create Redis connection.

    Returns:
        Redis client instance

    Example:
        ```python
        redis = await get_redis_connection()
        await redis.set("key", "value", ex=60)
        ```
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis_connection() -> None:
    """Close Redis connection.

    Should be called during application shutdown.

    Example:
        ```python
        @app.on_event("shutdown")
        async def shutdown():
            await close_redis_connection()
        ```
    """
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
