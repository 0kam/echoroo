"""First-party session ``/web-api/v1/users/*`` router.

Cookie + CSRF mirror of the legacy Bearer-JWT
:mod:`echoroo.api.v1.users` profile endpoints. The browser shell
migrated to BFF cookie auth in spec/006 (Phase 4) but five frontend
call sites were still issuing ``GET /api/v1/users/me`` with no Bearer
token, which 401-ed after a successful 2FA login and triggered the
auto-logout regression. This router adds the BFF-shaped equivalent
so those callers stop crossing the auth boundary.

Scope
-----

The self-scoped profile + API-token surface used by the browser shell:

* ``GET    /me``                       — return the authenticated user's profile.
* ``PATCH  /me``                       — update display name.
* ``PUT    /me/password``              — change password (the simple path; no
  cookie re-issue, unlike the spec/011 forced-change flow).
* ``GET    /me/api-tokens``            — list the caller's API tokens.
* ``POST   /me/api-tokens``            — create an API token (201, one-time value).
* ``DELETE /me/api-tokens/{token_id}`` — revoke an API token (204).

HONESTY NOTE: every handler below is a **transport-only delegator**. It
mirrors the legacy decorator (path / method / status_code / response_model)
exactly and forwards verbatim to the matching
:mod:`echoroo.api.v1.users` handler, which owns ALL DB semantics
(persistence, the per-handler ``db.commit`` on create/revoke, the 404 on a
missing token, the one-time plain-token reveal). The BFF layer adds only the
cookie + CSRF auth transport and performs NO business logic, NO response
translation, and NO additional ``db.commit``. These routes are self-scoped
(no ``project_id``) so they carry NO ``gate_action`` — they are classified
``USER_SCOPED_ONLY`` in the endpoint allowlist instead.

Auth transport
--------------

The router relies on the production middleware chain:

* :class:`echoroo.middleware.auth_router.AuthRouterMiddleware`
  resolves the session cookie into ``request.state.principal``.
* :data:`echoroo.middleware.auth.CurrentUser` rehydrates the
  matching :class:`User` row via the principal fast-path (it accepts
  both cookie-only and Bearer callers, see ``get_current_user`` in
  ``echoroo/middleware/auth.py``).
* :class:`echoroo.middleware.csrf.CsrfMiddleware` exempts GET (only
  unsafe methods need a token).

A caller hitting this endpoint with a valid session cookie therefore
succeeds without sending an ``Authorization: Bearer`` header, which
is exactly the failure mode the BFF migration left behind.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status

from echoroo.api.v1 import users as legacy_users
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

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile (BFF cookie auth)",
    description=(
        "Return the profile of the user resolved from the first-party "
        "session cookie. Cookie + CSRF mirror of "
        "``GET /api/v1/users/me``."
    ),
)
async def get_current_user_me(
    current_user: CurrentUser,
) -> UserResponse:
    """Return the BFF caller's profile.

    Args:
        current_user: User resolved by
            :class:`echoroo.middleware.auth_router.AuthRouterMiddleware`
            from the session cookie (or, transparently, from a Bearer
            token — :func:`get_current_user` accepts both).

    Returns:
        :class:`UserResponse` snapshot of the authenticated user.

    Raises:
        HTTPException 401: when no session cookie / Bearer credential
            resolves to a user. The middleware chain enforces this
            uniformly across the ``/web-api/v1/*`` surface.
    """
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update current user profile (BFF cookie auth)",
    description=(
        "Update the display name of the user resolved from the first-party "
        "session cookie. Cookie + CSRF mirror of ``PATCH /api/v1/users/me``."
    ),
)
async def update_current_user(
    request: UserUpdateRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> UserResponse:
    """Delegate the profile update to the legacy v1 handler.

    HONESTY NOTE: transport-only. The legacy handler owns all DB
    semantics; this adapter forwards the same deps verbatim and adds no
    business logic, no response translation, and no extra ``db.commit``.

    Args:
        request: Profile update data.
        current_user: User resolved from the session cookie.
        db: Database session.

    Returns:
        Updated :class:`UserResponse`.

    Raises:
        401: Not authenticated.
        422: Validation error.
    """
    return await legacy_users.update_current_user(
        request=request,
        current_user=current_user,
        db=db,
    )


@router.put(
    "/me/password",
    response_model=PasswordChangeResponse,
    summary="Change password (BFF cookie auth)",
    description=(
        "Change the password of the user resolved from the first-party "
        "session cookie. Cookie + CSRF mirror of "
        "``PUT /api/v1/users/me/password``. This is the simple voluntary "
        "change-password path (no cookie re-issue), distinct from the "
        "spec/011 forced-change flow on ``/web-api/v1/auth/change-password``."
    ),
)
async def change_password(
    request: PasswordChangeRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> PasswordChangeResponse:
    """Delegate the password change to the legacy v1 handler.

    HONESTY NOTE: transport-only. The legacy handler owns all DB
    semantics; this adapter forwards the same deps verbatim and adds no
    business logic, no response translation, and no extra ``db.commit``.

    Args:
        request: Password change data.
        current_user: User resolved from the session cookie.
        db: Database session.

    Returns:
        :class:`PasswordChangeResponse` success envelope.

    Raises:
        400: Invalid current password or weak new password.
        401: Not authenticated.
        422: Validation error.
    """
    return await legacy_users.change_password(
        request=request,
        current_user=current_user,
        db=db,
    )


# =============================================================================
# API Token Management Endpoints (BFF mirror)
# =============================================================================


@router.get(
    "/me/api-tokens",
    response_model=list[APITokenResponse],
    summary="List API tokens (BFF cookie auth)",
    description=(
        "List the active API tokens for the user resolved from the "
        "first-party session cookie. Cookie + CSRF mirror of "
        "``GET /api/v1/users/me/api-tokens``."
    ),
)
async def list_api_tokens(
    db: DbSession,
    current_user: CurrentUser,
) -> list[APITokenResponse]:
    """Delegate the API-token list to the legacy v1 handler.

    HONESTY NOTE: transport-only. The legacy handler owns all DB
    semantics; this adapter forwards the same deps verbatim and adds no
    business logic and no response translation.

    Args:
        db: Database session.
        current_user: User resolved from the session cookie.

    Returns:
        List of :class:`APITokenResponse` (without token values).

    Raises:
        401: Not authenticated.
    """
    return await legacy_users.list_api_tokens(
        db=db,
        current_user=current_user,
    )


@router.post(
    "/me/api-tokens",
    response_model=APITokenCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create API token (BFF cookie auth)",
    description=(
        "Create a new API token for the user resolved from the first-party "
        "session cookie. The token value is shown only once. Cookie + CSRF "
        "mirror of ``POST /api/v1/users/me/api-tokens``."
    ),
)
async def create_api_token(
    db: DbSession,
    current_user: CurrentUser,
    request: APITokenCreateRequest,
) -> APITokenCreateResponse:
    """Delegate API-token creation to the legacy v1 handler.

    HONESTY NOTE: transport-only. The legacy handler owns all DB
    semantics — including its own ``db.commit`` and the one-time plain
    token reveal — so this adapter forwards the same deps verbatim and
    performs NO additional ``db.commit`` and no response translation.

    Args:
        db: Database session.
        current_user: User resolved from the session cookie.
        request: Token creation request.

    Returns:
        :class:`APITokenCreateResponse` with the plain token (shown once).

    Raises:
        401: Not authenticated.
        422: Validation error.
    """
    return await legacy_users.create_api_token(
        db=db,
        current_user=current_user,
        request=request,
    )


@router.delete(
    "/me/api-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke API token (BFF cookie auth)",
    description=(
        "Revoke an API token owned by the user resolved from the "
        "first-party session cookie. Cookie + CSRF mirror of "
        "``DELETE /api/v1/users/me/api-tokens/{token_id}``."
    ),
)
async def revoke_api_token(
    db: DbSession,
    current_user: CurrentUser,
    token_id: UUID,
) -> None:
    """Delegate API-token revocation to the legacy v1 handler.

    HONESTY NOTE: transport-only. The legacy handler owns all DB
    semantics — including its own ``db.commit`` and the 404 on a missing
    token — so this adapter forwards the same deps verbatim and performs
    NO additional ``db.commit``.

    Args:
        db: Database session.
        current_user: User resolved from the session cookie.
        token_id: Token ID to revoke.

    Raises:
        401: Not authenticated.
        404: Token not found.
    """
    await legacy_users.revoke_api_token(
        db=db,
        current_user=current_user,
        token_id=token_id,
    )


__all__ = ["router"]
