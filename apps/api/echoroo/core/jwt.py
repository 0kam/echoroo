"""JWT token service using PyJWT."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from echoroo.core.settings import get_settings

settings = get_settings()


def create_access_token(data: dict[str, Any]) -> str:
    """Create JWT access token.

    Args:
        data: Payload data to encode in the token (e.g., {"sub": user_id})

    Returns:
        Encoded JWT access token string

    Example:
        ```python
        token = create_access_token({"sub": str(user.id), "email": user.email})
        # Token expires in 15 minutes
        ```
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict[str, Any]) -> str:
    """Create JWT refresh token with token family tracking.

    Args:
        data: Payload data to encode in the token

    Returns:
        Encoded JWT refresh token string with family ID

    Example:
        ```python
        refresh_token = create_refresh_token({"sub": str(user.id)})
        # Token expires in 14 days and includes a unique family ID
        ```
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    family_id = str(uuid.uuid4())
    to_encode.update({"exp": expire, "type": "refresh", "family": family_id})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate JWT token.

    Args:
        token: JWT token string to decode

    Returns:
        Decoded token payload

    Raises:
        jwt.ExpiredSignatureError: Token has expired
        jwt.InvalidTokenError: Token is invalid

    Example:
        ```python
        try:
            payload = decode_token(token)
            user_id = payload["sub"]
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        ```
    """
    decoded: dict[str, Any] = jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    return decoded
