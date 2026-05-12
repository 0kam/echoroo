"""First-party session ``/web-api/v1/users/*`` router.

Cookie + CSRF mirror of the legacy Bearer-JWT
:mod:`echoroo.api.v1.users` profile endpoints. The browser shell
migrated to BFF cookie auth in spec/006 (Phase 4) but five frontend
call sites were still issuing ``GET /api/v1/users/me`` with no Bearer
token, which 401-ed after a successful 2FA login and triggered the
auto-logout regression. This router adds the BFF-shaped equivalent
so those callers stop crossing the auth boundary.

Scope (intentionally narrow)
----------------------------

Only the read paths used by the post-2FA "hydrate auth store" flow
land here:

* ``GET /me`` — return the authenticated user's profile.

Profile mutations (``PATCH /me``, ``PUT /me/password``) and API-token
management (``/me/api-tokens/...``) intentionally stay on the legacy
:mod:`echoroo.api.v1.users` surface for now. Migrating them is a
follow-up: the regression we are fixing is the 401-on-hydrate loop,
not the entire profile surface.

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

from fastapi import APIRouter

from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.user import UserResponse

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


__all__ = ["router"]
