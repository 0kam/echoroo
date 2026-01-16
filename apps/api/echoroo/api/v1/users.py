"""User profile endpoints."""

from uuid import UUID

from fastapi import APIRouter, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.token import (
    APITokenCreateRequest,
    APITokenCreateResponse,
    APITokenResponse,
)
from echoroo.schemas.user import (
    PasswordChangeRequest,
    PasswordChangeResponse,
    UserResponse,
    UserUpdateRequest,
)
from echoroo.services.token import TokenService
from echoroo.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
    description="Get the profile of the currently authenticated user",
)
async def get_current_user(
    current_user: CurrentUser,
) -> UserResponse:
    """Get current user profile.

    Args:
        current_user: Current authenticated user

    Returns:
        Current user profile

    Raises:
        401: Not authenticated
    """
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile",
    description="Update display name and/or organization of the current user",
)
async def update_current_user(
    request: UserUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> UserResponse:
    """Update current user profile.

    Args:
        request: Profile update data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Updated user profile

    Raises:
        401: Not authenticated
        422: Validation error
    """
    user_service = UserService(db)
    updated_user = await user_service.update_user(current_user.id, request)
    return UserResponse.model_validate(updated_user)


@router.put(
    "/me/password",
    response_model=PasswordChangeResponse,
    summary="Change password",
    description="Change the password of the current user",
)
async def change_password(
    request: PasswordChangeRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> PasswordChangeResponse:
    """Change current user password.

    Args:
        request: Password change data
        current_user: Current authenticated user
        db: Database session

    Returns:
        Success message

    Raises:
        400: Invalid current password or weak new password
        401: Not authenticated
        422: Validation error
    """
    user_service = UserService(db)
    await user_service.change_password(current_user.id, request)
    return PasswordChangeResponse()


# =============================================================================
# API Token Management Endpoints
# =============================================================================


@router.get(
    "/me/api-tokens",
    response_model=list[APITokenResponse],
    summary="List API tokens",
    description="List all active API tokens for the current user",
)
async def list_api_tokens(
    db: DbSession,
    current_user: CurrentUser,
) -> list[APITokenResponse]:
    """List all active API tokens for the current user.

    Args:
        db: Database session
        current_user: Current authenticated user

    Returns:
        List of API tokens (without token values)

    Raises:
        401: Not authenticated
    """
    token_service = TokenService(db)
    tokens = await token_service.list_tokens(current_user.id)
    return [APITokenResponse.model_validate(t) for t in tokens]


@router.post(
    "/me/api-tokens",
    response_model=APITokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API token",
    description="Create a new API token. The token value is shown only once.",
)
async def create_api_token(
    db: DbSession,
    current_user: CurrentUser,
    request: APITokenCreateRequest,
) -> APITokenCreateResponse:
    """Create a new API token.

    The token value is returned only once in this response.
    Store it securely as it cannot be retrieved again.

    Args:
        db: Database session
        current_user: Current authenticated user
        request: Token creation request

    Returns:
        Created token with plain text value (shown only once)

    Raises:
        401: Not authenticated
        422: Validation error
    """
    token_service = TokenService(db)
    api_token, plain_token = await token_service.create_token(
        current_user.id, request
    )
    await db.commit()

    # Create response with token value
    response_data = APITokenResponse.model_validate(api_token).model_dump()
    response_data["token"] = plain_token
    return APITokenCreateResponse(**response_data)


@router.delete(
    "/me/api-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API token",
    description="Revoke an API token. The token will no longer be valid.",
)
async def revoke_api_token(
    db: DbSession,
    current_user: CurrentUser,
    token_id: UUID,
) -> None:
    """Revoke an API token.

    Args:
        db: Database session
        current_user: Current authenticated user
        token_id: Token ID to revoke

    Raises:
        401: Not authenticated
        404: Token not found
    """
    token_service = TokenService(db)
    await token_service.revoke_token(current_user.id, token_id)
    await db.commit()
