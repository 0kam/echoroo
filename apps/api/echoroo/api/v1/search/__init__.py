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

# W2-3 PR-18: the browser-superseded batch (``batch.py`` — POST /batch +
# GET /jobs/{job_id}) and search-annotation (``annotations.py`` — POST on the
# ``/projects/{project_id}/annotations`` router) routes were unmounted in favour
# of the ``/web-api/v1/.../search/{batch,jobs}`` + ``/web-api/v1/.../annotations``
# BFF. The legacy handlers survive as importable helpers
# (``echoroo.api.v1.search.batch`` / ``echoroo.api.v1.search.annotations``)
# delegated to by ``echoroo.api.web_v1.projects._search``, so the ``_batch_router``
# include and the ``annotations_router`` import + re-export are removed here. Only
# the sessions + similarity sub-routers stay mounted (for the KEEP routes
# reference-audio / similar / similar-by-audio) on the aggregate ``router``.
from echoroo.api.v1.search.sessions import router as _sessions_router
from echoroo.api.v1.search.similarity import router as _similarity_router

router = APIRouter(prefix="/projects/{project_id}/search", tags=["search"])

# Include all sub-routers into the main search router
router.include_router(_sessions_router)
router.include_router(_similarity_router)

__all__ = ["router"]
