"""Similarity search API package.

Re-exports the FastAPI routers from sub-modules for backward compatibility.
The implementation is split into focused sub-modules:

- deps.py        : shared dependencies (service factories, type aliases)
- sessions.py    : search session CRUD endpoints
- similarity.py  : single-query similarity search endpoints
- batch.py       : batch species search and job status endpoints
- annotations.py : search annotation creation endpoint
- utils.py       : internal helper functions
"""

# The main `router` aggregates all search sub-routers.
# Imported as `search_module.router` in echoroo/api/v1/__init__.py.
from fastapi import APIRouter

from echoroo.api.v1.search.annotations import annotations_router
from echoroo.api.v1.search.batch import router as _batch_router
from echoroo.api.v1.search.sessions import router as _sessions_router
from echoroo.api.v1.search.similarity import router as _similarity_router

router = APIRouter(prefix="/projects/{project_id}/search", tags=["search"])

# Include all sub-routers into the main search router
router.include_router(_sessions_router)
router.include_router(_similarity_router)
router.include_router(_batch_router)

__all__ = ["router", "annotations_router"]
