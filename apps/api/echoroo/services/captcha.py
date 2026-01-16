"""CAPTCHA verification service using Cloudflare Turnstile."""

import httpx

from echoroo.core.settings import get_settings

settings = get_settings()


async def verify_turnstile(token: str, client_ip: str) -> bool:
    """Verify Cloudflare Turnstile CAPTCHA token.

    Args:
        token: Turnstile response token from client
        client_ip: Client IP address

    Returns:
        True if CAPTCHA is valid, False otherwise

    Example:
        ```python
        is_valid = await verify_turnstile(captcha_token, request.client.host)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid CAPTCHA")
        ```
    """
    # If Turnstile is not configured, skip verification (development mode)
    if not settings.TURNSTILE_SECRET_KEY:
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
        # If verification fails due to network error, allow through
        # (but log the error in production)
        return True
