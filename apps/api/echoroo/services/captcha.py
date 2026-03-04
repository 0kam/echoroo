"""CAPTCHA verification service using Cloudflare Turnstile."""

import logging

import httpx

from echoroo.core.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def verify_turnstile(token: str, client_ip: str) -> bool:
    """Verify Cloudflare Turnstile CAPTCHA token.

    Args:
        token: Turnstile response token from client
        client_ip: Client IP address

    Returns:
        True if CAPTCHA is valid, False otherwise

    Raises:
        RuntimeError: If TURNSTILE_SECRET_KEY is not configured in production

    Example:
        ```python
        is_valid = await verify_turnstile(captcha_token, request.client.host)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid CAPTCHA")
        ```
    """
    # If Turnstile is not configured, fail-closed in production
    if not settings.TURNSTILE_SECRET_KEY:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(
                "TURNSTILE_SECRET_KEY must be configured in production environment"
            )
        # Development mode: skip verification
        return True

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                json={
                    "secret": settings.TURNSTILE_SECRET_KEY,
                    "response": token,
                    "remoteip": client_ip,
                },
                timeout=5.0,
            )
            result = response.json()
            success: bool = result.get("success", False)
            return success
    except Exception:
        # Fail-closed in production: network errors block access
        if settings.ENVIRONMENT == "production":
            logger.exception("Turnstile verification failed due to network error; failing closed")
            return False
        # Development/staging: allow through on network error
        logger.warning("Turnstile verification failed due to network error; allowing through (non-production)")
        return True
