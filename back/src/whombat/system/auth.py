"""Authentication dependencies."""

import warnings

from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import (
    AccessTokenDatabase,
    DatabaseStrategy,
)
from fastapi_users_db_sqlalchemy.access_token import (
    SQLAlchemyAccessTokenDatabase,
)
from sqlalchemy.ext.asyncio import AsyncSession

from whombat import models
from whombat.system.settings import Settings

TokenDatabase = AccessTokenDatabase[models.AccessToken]  # type: ignore


def get_access_token_db(session: AsyncSession):
    """Get the access token database."""
    return SQLAlchemyAccessTokenDatabase(
        session,
        models.AccessToken,  # type: ignore
    )


def get_database_strategy(
    access_token_db: TokenDatabase,
) -> DatabaseStrategy:
    """Get the database strategy."""
    return DatabaseStrategy(
        access_token_db,  # type: ignore
        lifetime_seconds=24 * 3600,
    )


def get_cookie_transport(settings: Settings):
    if (
        settings.auth_cookie_samesite == "none"
        and not settings.auth_cookie_secure
        and not settings.dev
    ):
        warnings.warn(
            "Auth cookie SameSite=None without Secure in non-dev mode; "
            "set WHOMBAT_AUTH_COOKIE_SECURE=true for production.",
            stacklevel=2,
        )
    return CookieTransport(
        cookie_max_age=24 * 3600,
        cookie_name="whombatauth",
        cookie_secure=settings.auth_cookie_secure,
        cookie_domain=settings.domain,
        cookie_samesite=settings.auth_cookie_samesite,
    )


def get_auth_backend(
    settings: Settings,
    get_strategy,
) -> AuthenticationBackend:
    """Get the authentication backend."""
    cookie_transport = get_cookie_transport(settings)
    return AuthenticationBackend(
        name="database",
        transport=cookie_transport,
        get_strategy=get_strategy,
    )
