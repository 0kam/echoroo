"""API v1 router configuration."""

from fastapi import APIRouter

from echoroo.api.v1 import admin, auth, clips, datasets, h3, projects, recordings, setup, sites, users

# Create main API router with /api/v1 prefix
api_router = APIRouter(prefix="/api/v1")

# Include sub-routers
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
api_router.include_router(sites.router)
api_router.include_router(datasets.router)
api_router.include_router(recordings.router)
api_router.include_router(clips.router)
api_router.include_router(h3.router)
api_router.include_router(admin.router)
