"""Common FastAPI dependencies for echoroo."""

from echoroo.routes.dependencies.auth import (
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.dependencies.session import Session
from echoroo.routes.dependencies.settings import EchorooSettings
from echoroo.routes.dependencies.users import get_user_db, get_user_manager

__all__ = [
    "Session",
    "EchorooSettings",
    "get_user_db",
    "get_user_manager",
    "get_current_user_dependency",
    "get_optional_current_user_dependency",
]
