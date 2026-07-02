"""Authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.middleware.rate_limit import (
    login_rate_limiter,
    register_rate_limiter,
)
from echoroo.schemas.auth import (
    LogoutResponse,
    TokenResponse,
    UserRegisterRequest,
    UserResponse,
)
from echoroo.schemas.web_v1.change_password import (
    ChangePasswordRequest,
    ChangePasswordResponse,
)
from echoroo.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account. Requires CAPTCHA after 3 failed attempts.",
)
async def register(
    request: UserRegisterRequest,
    http_request: Request,
    db: DbSession,
    _rate_limit: None = Depends(register_rate_limiter()),
) -> UserResponse:
    """Register a new user account.

    Args:
        request: User registration data
        http_request: FastAPI request object
        db: Database session

    Returns:
        Created user response

    Raises:
        400: Email already exists or validation error
        403: Registration disabled or invitation required
        429: Rate limit exceeded
    """
    auth_service = AuthService(db)
    client_ip = http_request.client.host if http_request.client else "unknown"

    user = await auth_service.register(request, client_ip)

    return UserResponse.model_validate(user)


# W2-3 login PR (Option C): the legacy ``POST /auth/login`` route and its
# handler were deleted outright. Unlike the function-as-helper unmounts,
# nothing imported the handler — it only reached the Phase-4
# ``AuthService.login()`` stub, which always raised HTTP 501. The sole
# login surface is now ``POST /web-api/v1/auth/login`` (401 invalid
# credentials / 429 lockout+rate-limit; contracts/auth.yaml updated
# 423 -> 429 in the same change).


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="User logout",
    description="Invalidate current session and clear refresh token cookie",
    responses={
        # Phase 17 contract drift cleanup: contracts/auth.yaml declares
        # 204 No Content for logout. The legacy /api/v1 surface still
        # returns 200 with a LogoutResponse body for backward compat;
        # only the contract declaration is widened here. Wire behaviour
        # is unchanged.
        204: {"description": "Logout successful (no content)"},
    },
)
async def logout(
    response: Response,
    current_user: CurrentUser,
    db: DbSession,
) -> LogoutResponse:
    """Logout current user.

    Args:
        response: FastAPI response object (for clearing cookie)
        current_user: Current authenticated user
        db: Database session

    Returns:
        Logout success message

    Raises:
        401: Not authenticated
    """
    auth_service = AuthService(db)
    await auth_service.logout(current_user.id)

    # Clear refresh token cookie with matching security attributes
    response.delete_cookie(
        key="refresh_token",
        path="/",
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
    )

    return LogoutResponse()


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description="Get new access token using refresh token from cookie",
    responses={
        # Phase 17 contract drift cleanup: 401 is raised at runtime when
        # the refresh cookie is missing/invalid; declaration was absent.
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie()] = None,
    _rate_limit: None = Depends(login_rate_limiter()),
) -> TokenResponse:
    """Refresh access token using refresh token.

    Args:
        response: FastAPI response object (for setting new cookie)
        db: Database session
        refresh_token: Refresh token from HttpOnly cookie

    Returns:
        New access token response

    Raises:
        401: Invalid or expired refresh token
    """
    from fastapi import HTTPException

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )

    auth_service = AuthService(db)
    token_response, new_refresh_token = await auth_service.refresh_token(refresh_token)

    # Set new refresh token in HttpOnly cookie (token rotation)
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )

    return token_response


# spec/011 §FR-011-005 — the legacy ``/api/v1/auth/password-reset/{request,confirm}``
# and ``/api/v1/auth/verify-email`` endpoints were removed in Step 10
# (T120). Self-service password recovery is replaced by the
# admin-mediated reset flow exposed via ``/web-api/v1/admin/users/
# {user_id}/password/reset``; email verification is removed wholesale
# (FR-011-002).


@router.post(
    "/change-password",
    response_model=ChangePasswordResponse,
    summary="Change own password (v1 mirror of the BFF change-password endpoint)",
    description=(
        "spec/011 §FR-011-204 / T320. v1 mirror of "
        "``POST /web-api/v1/auth/change-password``. Delegates to the "
        "identical shared handler so both surfaces behave the same: "
        "accepts the live password OR an in-window admin-issued "
        "temporary password, clears ``must_change_password`` on success, "
        "rotates the security stamp, invalidates other sessions, and "
        "revokes trusted devices."
    ),
    responses={
        400: {"description": "New password is identical to the current password"},
        401: {"description": "Current password / temporary password mismatch"},
        422: {"description": "New password fails the password policy"},
    },
)
async def change_password(
    payload: ChangePasswordRequest,
    http_request: Request,
    db: DbSession,
    current_user: CurrentUser,
) -> ChangePasswordResponse:
    """v1 mirror of the BFF self-service change-password endpoint.

    Reuses :func:`echoroo.api.web_v1.auth._handle_change_password` so the
    credential verification, forced-change clearing, security-stamp
    rotation, session invalidation, trusted-device revocation, audit
    emission, and HTTP error envelopes are identical to the
    ``/web-api/v1`` surface. Imported lazily to avoid a router-level
    import cycle between the two ``auth`` modules.

    Current-session survival (FR-011-205): the stamp rotation invalidates
    the caller's existing access token, so the response carries a FRESH
    ``access_token`` (+ ``expires_in``) bound to the new stamp — mirroring
    the v1 login token body. Bearer clients MUST replace their stored
    token with this value to keep the current session working; all OTHER
    tokens for the user remain invalidated. This surface issues NO cookies
    (``issue_session_cookies`` defaults to False) — it is the Bearer
    parity path only.
    """
    from echoroo.api.web_v1.auth import _handle_change_password  # noqa: PLC0415

    return await _handle_change_password(
        payload=payload,
        request=http_request,
        db=db,
        current_user=current_user,
    )
