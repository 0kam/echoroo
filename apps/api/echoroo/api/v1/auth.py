"""Authentication endpoints."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.middleware.rate_limit import (
    login_rate_limiter,
    password_reset_rate_limiter,
    register_rate_limiter,
)
from echoroo.schemas.auth import (
    EmailVerifyRequest,
    LoginRequest,
    LogoutResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    TokenResponse,
    UserRegisterRequest,
    UserResponse,
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


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="User login",
    description="Authenticate user and return access token (refresh token in HttpOnly cookie)",
    responses={
        # Phase 17 contract drift cleanup: declarations only — the legacy
        # v1 ``AuthService.login()`` is a Phase 4 stub that always raises
        # HTTP 501, so neither 401 (Invalid credentials) nor 423 (Account
        # locked) is currently reachable on this surface. They are pinned
        # here to keep contracts/auth.yaml in sync with the live OpenAPI
        # so contract clients see the planned post-Phase-4 shape.
        401: {"description": "Invalid credentials"},
        423: {"description": "Account locked (too many failed attempts)"},
    },
)
async def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
    db: DbSession,
    _rate_limit: None = Depends(login_rate_limiter()),
) -> TokenResponse:
    """Authenticate user and generate tokens.

    Args:
        request: Login credentials
        response: FastAPI response object (for setting cookie)
        http_request: FastAPI request object
        db: Database session

    Returns:
        Access token response

    Raises:
        401: Invalid credentials
        403: Account disabled or email not verified
        423: Account locked (too many failed attempts)
        429: Rate limit exceeded
    """
    auth_service = AuthService(db)
    client_ip = http_request.client.host if http_request.client else "unknown"
    user_agent = http_request.headers.get("user-agent")

    token_response, refresh_token = await auth_service.login(request, client_ip, user_agent)

    # Set refresh token in HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )

    return token_response


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


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_200_OK,
    summary="Request password reset",
    description="Send password reset email (always returns success for security)",
    responses={
        # Phase 17 contract drift cleanup: contracts/auth.yaml declares
        # 204 No Content. The legacy /api/v1 surface still returns 200
        # with a JSON body for backward compat; only the contract
        # declaration is widened. Wire behaviour is unchanged.
        204: {"description": "Reset request accepted (no content)"},
    },
)
async def request_password_reset(
    request: PasswordResetRequest,
    db: DbSession,
    _rate_limit: None = Depends(password_reset_rate_limiter()),
) -> dict[str, str]:
    """Request password reset email.

    Args:
        request: Password reset request data
        db: Database session

    Returns:
        Success message

    Note:
        Always returns success even if email doesn't exist (security best practice)
    """
    auth_service = AuthService(db)
    await auth_service.request_password_reset(request.email)

    return {"message": "If the email exists, a password reset link has been sent"}


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_200_OK,
    summary="Confirm password reset",
    description="Reset password using token from email",
    responses={
        # Phase 17 contract drift cleanup: contracts/auth.yaml declares
        # 204 No Content. The legacy /api/v1 surface still returns 200
        # with a JSON body for backward compat; only the contract
        # declaration is widened. Wire behaviour is unchanged.
        204: {"description": "Reset confirmed (no content)"},
    },
)
async def confirm_password_reset(
    request: PasswordResetConfirm,
    db: DbSession,
) -> dict[str, str]:
    """Confirm password reset with token.

    Args:
        request: Password reset confirmation data
        db: Database session

    Returns:
        Success message

    Raises:
        400: Invalid or expired token
    """
    auth_service = AuthService(db)
    await auth_service.confirm_password_reset(request)

    return {"message": "Password reset successful"}


@router.post(
    "/verify-email",
    response_model=UserResponse,
    summary="Verify email address",
    description="Verify email using token from registration email",
)
async def verify_email(
    request: EmailVerifyRequest,
    db: DbSession,
) -> UserResponse:
    """Verify user email with token.

    Args:
        request: Email verification request data
        db: Database session

    Returns:
        Updated user response

    Raises:
        400: Invalid or expired token
    """
    auth_service = AuthService(db)
    user = await auth_service.verify_email(request.token)

    return UserResponse.model_validate(user)
