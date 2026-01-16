"""API v1 router configuration."""

from fastapi import APIRouter

from echoroo.api.v1 import admin, auth, projects, setup, users

# Create main API router with /api/v1 prefix
api_router = APIRouter(prefix="/api/v1")

# Include sub-routers
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(admin.router)
