"""Authentication dependencies."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend

from echoroo import models
from echoroo.routes.dependencies.session import Session
from echoroo.routes.dependencies.settings import EchorooSettings
from echoroo.routes.dependencies.users import get_user_manager
from echoroo.system import auth


def get_access_token_db(
    session: Session,
):
    """Get the access token database."""
    return auth.get_access_token_db(session)


async def get_database_strategy(
    token_db: Annotated[auth.TokenDatabase, Depends(get_access_token_db)],
):
    """Get the authentication strategy."""
    return auth.get_database_strategy(token_db)


def get_auth_backend(
    settings: EchorooSettings,
):
    """Get the authentication backend."""
    cookie_transport = auth.get_cookie_transport(settings)
    return AuthenticationBackend(
        name="database",
        transport=cookie_transport,
        get_strategy=get_database_strategy,
    )


def get_users_api(settings: EchorooSettings):
    """Get the users API."""
    auth_backend = get_auth_backend(settings)
    return FastAPIUsers[models.User, UUID](  # type: ignore
        get_user_manager,
        [auth_backend],
    )


def get_current_user_dependency(
    settings: EchorooSettings,
):
    """Get the current user."""
    fastapi_users = get_users_api(settings)
    return fastapi_users.current_user(active=True)


def get_current_admin_dependency(
    settings: EchorooSettings,
):
    """Return a dependency that requires the current user to be an admin."""

    fastapi_users = get_users_api(settings)
    return fastapi_users.current_user(active=True, superuser=True)


def get_optional_current_user_dependency(
    settings: EchorooSettings,
):
    """Return a dependency that allows unauthenticated access."""

    fastapi_users = get_users_api(settings)
    return fastapi_users.current_user(active=True, optional=True)
