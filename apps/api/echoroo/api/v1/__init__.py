"""API v1 router configuration."""

from fastapi import APIRouter

from echoroo.api.v1 import (
    admin,
    annotation_comments,
    annotation_projects,
    annotation_tasks,
    annotation_votes,
    annotations,
    auth,
    clips,
    confirmed_regions,
    custom_models,
    datasets,
    detection_runs,
    detections,
    h3,
    projects,
    recorders,
    recordings,
    setup,
    sites,
    tags,
    taxa,
    uploads,
    users,
    xeno_canto,
)
from echoroo.api.v1 import (
    search as search_module,
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
# Generic annotation vote endpoints (must be before search annotations_router
# to avoid route conflicts on /projects/{project_id}/annotations/{id}/votes)
api_router.include_router(annotation_votes.router)
# Phase 17 follow-up — register annotation comments router that
# echoroo/api/v1/annotation_comments.py declared in Phase 3 but never
# wired into the app factory (its module docstring still flagged this
# as a follow-up). Without this line contracts/detections.yaml's
# /projects/{id}/annotations/{annotationId}/comments path drifts from
# the live OpenAPI surface (Codex Round X follow-up #4).
api_router.include_router(annotation_comments.router)
# Search annotation creation router
api_router.include_router(search_module.annotations_router)
# Custom model router
api_router.include_router(custom_models.router)
# Xeno-canto proxy router
api_router.include_router(xeno_canto.router)

# Cross-model evaluation router (003-annotation A3)
from echoroo.api.v1 import evaluation as _evaluation  # noqa: E402

api_router.include_router(_evaluation.annotation_set_router)
api_router.include_router(_evaluation.run_router)

# Ground-truth annotation routers (003-annotation A2)
from echoroo.api.v1 import annotation_sets as _annotation_sets  # noqa: E402
from echoroo.api.v1 import segments as _segments  # noqa: E402
from echoroo.api.v1 import time_range_annotations as _time_range_annotations  # noqa: E402

api_router.include_router(_annotation_sets.router)
api_router.include_router(_segments.router)
api_router.include_router(_time_range_annotations.router)
