"""Authentication middleware and dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from echoroo.core.database import DbSession
from echoroo.models.user import User
from echoroo.services.auth import AuthService
from echoroo.services.token import TokenService

security = HTTPBearer(auto_error=False)

# Token prefix for API tokens
API_TOKEN_PREFIX = "ecr_"


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User:
    """Get current authenticated user from JWT token or API token.

    Supports two authentication methods:
    1. JWT access token (standard)
    2. API token (prefixed with 'ecr_')

    Args:
        db: Database session
        credentials: HTTP Bearer credentials

    Returns:
        Current user instance

    Raises:
        HTTPException: If token is missing, invalid, or user not found

    Example:
        ```python
        @router.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"user_id": user.id}
        ```
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # Check if it's an API token (starts with ecr_)
    if token.startswith(API_TOKEN_PREFIX):
        token_service = TokenService(db)
        user = await token_service.authenticate_by_token(token)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired API token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return user

    # Otherwise, treat as JWT token
    auth_service = AuthService(db)
    return await auth_service.get_current_user(token)


async def get_current_active_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Get current user and verify superuser status.

    Args:
        current_user: Current authenticated user

    Returns:
        Current user instance

    Raises:
        HTTPException: If user is not a superuser

    Example:
        ```python
        @router.get("/admin")
        async def admin_route(user: User = Depends(get_current_active_superuser)):
            return {"message": "Admin access granted"}
        ```
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


# Type aliases for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSuperuser = Annotated[User, Depends(get_current_active_superuser)]
