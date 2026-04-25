"""First-party session API (Cookie + CSRF) under ``/web-api/v1/*``."""

from fastapi import APIRouter

from echoroo.api.web_v1 import auth as auth_module

web_v1_router = APIRouter(prefix="/web-api/v1")
web_v1_router.include_router(auth_module.router)

__all__ = ["web_v1_router"]
