"""Module containing routers for user management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select

from echoroo import api, models, schemas, exceptions
from echoroo.routes.dependencies import Session, get_current_user_dependency
from echoroo.routes.dependencies.auth import get_users_api
from echoroo.routes.dependencies.settings import EchorooSettings
from echoroo.routes.dependencies.users import UserManager, get_user_manager
from echoroo.schemas.users import User, UserAdminUpdate, UserCreate, UserUpdate

__all__ = [
    "get_users_router",
    "get_admin_users_router",
]


def get_users_router(settings: EchorooSettings) -> APIRouter:
    users_router = APIRouter()

    fastapi_users = get_users_api(settings)
    current_user_required = get_current_user_dependency(settings)

    # Dependency to require superuser access
    async def require_superuser(
        user: schemas.User = Depends(current_user_required),
    ) -> schemas.User:
        if not user.is_superuser:
            raise exceptions.NotAuthorizedError("Superuser access required")
        return user

    admin_required = require_superuser

    users_router.include_router(fastapi_users.get_users_router(User, UserUpdate))

    @users_router.post("/first/", response_model=User)
    async def create_first_user(
        data: UserCreate,
        user_manager: Annotated[UserManager, Depends(get_user_manager)],
    ):
        """Create the first user."""
        if await user_manager.user_db.has_user():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A first user has already been created.",
            )

        # This is the first user, so make them an admin
        data.is_superuser = True

        user = await user_manager.create(data, safe=False)
        if not user.is_superuser:
            user = await user_manager.user_db.update(
                user, {"is_superuser": True}
            )
        return user

    @users_router.get(
        "/lookup/",
        response_model=schemas.SimpleUser,
    )
    async def lookup_user_by_username(
        session: Session,
        username: str,
        _: Annotated[schemas.SimpleUser, Depends(current_user_required)],
    ):
        """Resolve a user by username for authenticated callers."""

        return await api.users.get_by_username(session, username)

    return users_router


def get_admin_users_router(settings: EchorooSettings) -> APIRouter:
    admin_router = APIRouter()

    current_user_required = get_current_user_dependency(settings)

    # Dependency to require superuser access
    async def require_superuser(
        user: schemas.User = Depends(current_user_required),
    ) -> schemas.User:
        if not user.is_superuser:
            raise exceptions.NotAuthorizedError("Superuser access required")
        return user

    admin_required = require_superuser

    @admin_router.get("/", response_model=list[schemas.SimpleUser])
    async def list_users_admin(
        session: Session,
        _: Annotated[models.User, Depends(admin_required)],
    ):
        result = await session.execute(select(models.User))
        users = result.scalars().all()
        return [schemas.SimpleUser.model_validate(user) for user in users]

    @admin_router.post(
        "/",
        response_model=schemas.SimpleUser,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_user_admin(
        data: UserCreate,
        user_manager: Annotated[UserManager, Depends(get_user_manager)],
        _: Annotated[models.User, Depends(admin_required)],
    ):
        user = await user_manager.create(data, safe=False)
        return schemas.SimpleUser.model_validate(user)

    @admin_router.patch(
        "/{user_id}",
        response_model=schemas.SimpleUser,
    )
    async def update_user_admin(
        user_id: UUID,
        data: UserAdminUpdate,
        user_manager: Annotated[UserManager, Depends(get_user_manager)],
        _: Annotated[models.User, Depends(admin_required)],
    ):
        user = await user_manager.get(user_id)
        user = await user_manager.update(data, user, safe=False)
        return schemas.SimpleUser.model_validate(user)

    @admin_router.delete(
        "/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_user_admin(
        user_id: UUID,
        user_manager: Annotated[UserManager, Depends(get_user_manager)],
        _: Annotated[models.User, Depends(admin_required)],
    ):
        user = await user_manager.get(user_id)
        await user_manager.delete(user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return admin_router
