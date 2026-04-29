"""Authentication middleware and dependencies."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import DbSession
from echoroo.models.user import User
from echoroo.services.auth import AuthService
from echoroo.services.token import TokenService

security = HTTPBearer(auto_error=False)

# Token prefix for API tokens
API_TOKEN_PREFIX = "ecr_"


def _stamp_api_key_scopes(user: User, principal: object) -> None:
    """Stamp the API-key scopes onto a transient User instance.

    Phase 15 NO-GO C4 / Major 1 fix: when a request arrives via the
    Bearer API-key path,
    :class:`echoroo.middleware.auth_router.AuthRouterMiddleware` puts a
    :class:`Principal` carrying ``api_key_id`` + ``scopes`` onto
    ``request.state.principal``. The downstream permission gate
    (:func:`echoroo.core.permissions.gate_action`) needs the scopes to
    intersect them with the matrix's effective-permission bundle so an
    API key with ``scopes=("VIEW_DETECTION",)`` cannot exercise the
    full ``view_recording`` / ``vote`` / ``export`` bundle that its
    owning user happens to hold.

    The scopes flow as ``user._api_key_scopes`` — a transient attribute
    consumed by the gate. The User ORM model has no column for them,
    and the attribute lives only for the duration of the request.

    Note on Phase 13 cohabitation: ``user._superuser_id`` already uses
    the same single-underscore convention; both attributes coexist.
    """
    api_key_id = getattr(principal, "api_key_id", None)
    if api_key_id is None:
        return
    raw_scopes = getattr(principal, "scopes", ()) or ()
    user._api_key_id = api_key_id  # type: ignore[attr-defined]
    user._api_key_scopes = tuple(raw_scopes)  # type: ignore[attr-defined]


async def _stamp_superuser_status(db: AsyncSession, user: User | None) -> None:
    """Resolve and stamp ``user.is_superuser`` / ``user._superuser_id``.

    Phase 12 R2 致命 C1 fix: the User ORM model deliberately has NO
    ``is_superuser`` column — superuser status is the single source-of-
    truth held by the ``superusers`` table (``revoked_at IS NULL`` →
    active). Auth dependencies MUST stamp the resolved status onto the
    transient User instance so downstream gates
    (:func:`echoroo.core.permissions._is_superuser`,
    :func:`api.web_v1.admin._require_authenticated_superuser`) can consult
    a uniform attribute without re-issuing the same SQL.

    Phase 13 P1 R2 致命 #2 fix: in addition to the boolean flag, stamp the
    resolved ``superusers.id`` onto ``user._superuser_id`` so admin handlers
    that persist FK references to the ``superusers`` table (e.g.
    ``system_settings.updated_by_id``) can reach the correct id without
    re-issuing the same SQL. ``users.id`` is **not** a valid FK target for
    those columns and using it directly causes integrity violations.

    The probe matches the raw-SQL helper in
    :mod:`echoroo.api.web_v1.auth._is_superuser`, keeping every
    superuser-aware surface in lockstep.
    """
    if user is None:
        return
    probe = await db.execute(
        text(
            "SELECT id FROM superusers "
            "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
        ),
        {"uid": user.id},
    )
    superuser_id = probe.scalar_one_or_none()
    user.is_superuser = superuser_id is not None  # type: ignore[attr-defined]
    user._superuser_id = superuser_id  # type: ignore[attr-defined]


async def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> User:
    """Get current authenticated user from API key principal, JWT, or API token.

    Resolution priority (Phase 15 NO-GO C4 fix):

      1. ``request.state.principal`` — populated by
         :class:`AuthRouterMiddleware` after a successful API-key
         (``echoroo_<prefix>_<secret>``) verification on
         ``/api/v1/*``. The Bearer header has already been consumed
         and verified by :class:`DbApiKeyVerifier`; this dependency
         simply rehydrates the matching :class:`User` row and stamps
         the API-key scopes onto it so the downstream permission
         gate (:func:`echoroo.core.permissions.gate_action`) can
         intersect them with the matrix bundle.

      2. Bearer JWT — the long-standing programmatic / scripted path.

      3. Bearer API token (``ecr_*`` legacy prefix) — pre-Phase-15
         personal access tokens. Distinct from the new API keys: this
         path is owned by :class:`TokenService`, not the auth-router
         middleware.

    The principal-fast-path is a strict superset of behaviour: when
    no principal is attached (cookie-only, JWT, legacy token), every
    pre-Phase-15 code path is preserved bit-for-bit.

    Args:
        request: Incoming HTTP request — used to read
            ``state.principal`` populated by
            :class:`AuthRouterMiddleware`.
        db: Database session.
        credentials: HTTP Bearer credentials. May be ``None`` when an
            API key was already consumed by the middleware (the
            principal path does not need to re-read the header).

    Returns:
        Current user instance.

    Raises:
        HTTPException 401 when no credential resolves to a user.

    Example:
        ```python
        @router.get("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            return {"user_id": user.id}
        ```
    """
    # 1. API-key principal fast path (Phase 15 NO-GO C4).
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        api_key_id = getattr(principal, "api_key_id", None)
        principal_user_id = getattr(principal, "user_id", None)
        if api_key_id is not None and isinstance(principal_user_id, UUID):
            result = await db.execute(
                select(User).where(User.id == principal_user_id)
            )
            user = result.scalar_one_or_none()
            if user is not None:
                # Stamp the API-key scopes onto the User instance so
                # downstream gates can apply Major-1 intersection.
                _stamp_api_key_scopes(user, principal)
                await _stamp_superuser_status(db, user)
                return user
            # Principal points at a vanished user → fall through to
            # 401 below (do not silently downgrade to anonymous on a
            # protected endpoint).

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

        await _stamp_superuser_status(db, user)
        return user

    # Otherwise, treat as JWT token
    auth_service = AuthService(db)
    user = await auth_service.get_current_user(token)
    await _stamp_superuser_status(db, user)
    return user


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
    # 1. Cookie-session OR API-key fast path — AuthRouterMiddleware has
    # already verified the cookie + JWT, OR resolved an API key, and
    # stashed the resolved Principal on request.state. Phase 15 NO-GO
    # C4: API-key callers also flow through this dependency on the
    # public-read endpoints, so the scope stamping must happen here too
    # otherwise Major 1 (effective_permissions intersection) loses its
    # input on Public projects.
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        user_id = getattr(principal, "user_id", None)
        if isinstance(user_id, UUID):
            result = await db.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is not None:
                if getattr(principal, "api_key_id", None) is not None:
                    _stamp_api_key_scopes(user, principal)
                await _stamp_superuser_status(db, user)
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
            user = await token_service.authenticate_by_token(token)
            await _stamp_superuser_status(db, user)
            return user

        auth_service = AuthService(db)
        user = await auth_service.get_current_user(token)
        await _stamp_superuser_status(db, user)
        return user
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
