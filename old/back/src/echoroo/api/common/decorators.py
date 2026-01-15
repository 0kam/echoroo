"""Common decorators for API access control."""

from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, models

__all__ = ["require_ml_project_access"]

P = ParamSpec("P")
T = TypeVar("T")


def require_ml_project_access(
    edit_mode: bool = False,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator to verify user has access to an ML project.

    Automatically fetches the ML project by UUID and verifies the user
    has appropriate permissions (view or edit) by calling api.ml_projects.get().

    The ML project is fetched and added to kwargs as 'ml_project', making it
    available to the decorated function.

    Args:
        edit_mode: If True, require edit permissions. If False, require view permissions.
                  Note: Currently both modes use the same api.ml_projects.get() which
                  handles permission checking internally.

    Usage:
        @require_ml_project_access(edit_mode=True)
        async def create_something(
            session: AsyncSession,
            ml_project_uuid: UUID,
            user: models.User,
            ...
        ) -> ...:
            # ml_project is now available in kwargs and access is verified
            ml_project = kwargs.get("ml_project")
            ...

    The decorated function must have these parameters in its signature:
    - session: AsyncSession (or Session as dependency)
    - ml_project_uuid: UUID
    - user: models.User (or models.User | None for optional)

    Note: The decorator extracts ml_project_uuid from kwargs, not args,
    so it works best with FastAPI dependency injection where all parameters
    are passed as kwargs.
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract required parameters from kwargs
            # These are typically provided by FastAPI dependency injection
            session: AsyncSession | None = kwargs.get("session")
            ml_project_uuid: UUID | None = kwargs.get("ml_project_uuid")
            user: models.User | None = kwargs.get("user")

            if not all([session, ml_project_uuid]):
                raise ValueError(
                    "require_ml_project_access requires 'session' and 'ml_project_uuid' "
                    "parameters to be present in kwargs"
                )

            # Fetch ML project and verify access
            # api.ml_projects.get() internally calls can_view_ml_project() or can_edit_ml_project()
            # and raises PermissionDeniedError if user doesn't have access
            ml_project = await api.ml_projects.get(
                session,  # type: ignore
                ml_project_uuid,  # type: ignore
                user=user,
            )

            # Add ml_project to kwargs for use in the decorated function
            kwargs["ml_project"] = ml_project

            return await func(*args, **kwargs)

        return wrapper  # type: ignore
    return decorator  # type: ignore
