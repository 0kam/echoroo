"""Authentication middleware and dependencies."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

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


async def get_current_user_optional(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User | None:
    """Resolve the current user OR return ``None`` for unauthenticated callers.

    Mirrors :func:`get_current_user` but never raises 401 when credentials
    are missing or invalid — instead returns ``None``. This is the dependency
    used by Public-visible endpoints (FR-016 Phase 5 US1) where Guest reads
    are explicitly part of the contract: the Stage-1 permission gate
    (:func:`echoroo.core.permissions.is_allowed`) will decide whether the
    Guest principal is allowed via the Canonical Matrix.

    Resolution priority (Phase 5 polish round 2):

        1. ``request.state.principal`` — set by
           :class:`echoroo.middleware.auth_router.AuthRouterMiddleware` when
           the caller arrives with a session cookie. Loading the User by id
           here ensures cookie-authenticated owners see *their own*
           Restricted projects on the Guest-aware list/detail surface.
        2. ``Authorization: Bearer <token>`` — programmatic / scripted
           callers and tests that pass a JWT directly.
        3. ``None`` — Guest. The downstream permission gate decides whether
           the project is reachable (Public + Active only for Guests).

    Args:
        request: Incoming HTTP request — used to read ``state.principal``
            populated by :class:`AuthRouterMiddleware`.
        db: Database session.
        credentials: HTTP Bearer credentials (may be absent).

    Returns:
        Authenticated :class:`User` or ``None`` for Guest.
    """
    # 1. Cookie-session fast path — AuthRouterMiddleware has already verified
    # the cookie + JWT and stashed the resolved Principal on request.state.
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        user_id = getattr(principal, "user_id", None)
        if isinstance(user_id, UUID):
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is not None:
                return user
            # Fall through: a Principal without a backing User row is
            # treated as Guest rather than 401 to preserve the Public-read
            # contract.

    # 2. Bearer header fallback (programmatic surface / direct API callers).
    if credentials is None:
        return None

    token = credentials.credentials
    if not token:
        return None

    try:
        if token.startswith(API_TOKEN_PREFIX):
            token_service = TokenService(db)
            return await token_service.authenticate_by_token(token)

        auth_service = AuthService(db)
        return await auth_service.get_current_user(token)
    except HTTPException:
        # FR-016 Phase 5: a *bad* token on a Public endpoint must still allow
        # Guest fall-through rather than 401-ing the response. Production
        # security is enforced by the central permission gate downstream.
        return None


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
    if not bool(getattr(current_user, "is_superuser", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


# Type aliases for dependency injection
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSuperuser = Annotated[User, Depends(get_current_active_superuser)]
OptionalCurrentUser = Annotated[User | None, Depends(get_current_user_optional)]
