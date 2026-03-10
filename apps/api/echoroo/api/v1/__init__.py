"""API v1 router configuration."""

from fastapi import APIRouter

from echoroo.api.v1 import (
    admin,
    annotation_projects,
    annotation_tasks,
    annotations,
    auth,
    clips,
    confirmed_regions,
    datasets,
    detection_runs,
    detections,
    h3,
    projects,
    recorders,
    recordings,
    search as search_module,
    setup,
    sites,
    tags,
    taxa,
    uploads,
    users,
    xeno_canto,
)

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
api_router.include_router(tags.router)
api_router.include_router(taxa.router)
api_router.include_router(recorders.router)
api_router.include_router(annotation_projects.router)
api_router.include_router(annotation_tasks.router)
api_router.include_router(annotations.router)
api_router.include_router(admin.router)
# Detection review routers (003-detection-review)
api_router.include_router(detections.router)
api_router.include_router(confirmed_regions.router)
api_router.include_router(detection_runs.router)
api_router.include_router(detection_runs.models_router)
# Upload session router
api_router.include_router(uploads.router)
# Similarity search router
api_router.include_router(search_module.router)
# Search annotation creation router
api_router.include_router(search_module.annotations_router)
# Xeno-canto proxy router
api_router.include_router(xeno_canto.router)
