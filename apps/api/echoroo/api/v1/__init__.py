"""API v1 router configuration."""

from fastapi import APIRouter

from echoroo.api.v1 import (
    annotation_comments,
    auth,
    clips,
    confirmed_regions,
    datasets,
    detection_runs,
    detections,
    h3,
    licenses,
    projects,
    recordings,
    taxa,
    users,
    xeno_canto,
)
from echoroo.api.v1 import (
    search as search_module,
)

# Create main API router with /api/v1 prefix
api_router = APIRouter(prefix="/api/v1")

# Include sub-routers
# W2-3 PR-2: the public ``/api/v1/setup/*`` bootstrap routes were unmounted in
# favour of the ``/web-api/v1/setup/*`` BFF surface. The legacy handlers survive
# as importable helpers (``echoroo.api.v1.setup.{get_setup_status,initialize_setup}``)
# delegated to by ``echoroo.api.web_v1.setup``; only the v1 route registration
# is removed here.
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(projects.router)
# W2-3 PR-8: the public ``/api/v1/projects/{project_id}/sites/*`` routes were
# unmounted in favour of the ``/web-api/v1/.../sites/*`` BFF. The legacy handlers
# survive as importable helpers (``echoroo.api.v1.sites``) delegated to by
# ``echoroo.api.web_v1.projects._sites``; only the v1 route registration is
# removed here.
api_router.include_router(datasets.router)
api_router.include_router(recordings.router)
api_router.include_router(clips.router)
api_router.include_router(h3.router)
# W2-3 PR-9: the public ``/api/v1/projects/{project_id}/tags/*`` routes were
# unmounted in favour of the ``/web-api/v1/.../tags/*`` BFF. The legacy handlers
# survive as importable helpers (``echoroo.api.v1.tags``) delegated to by
# ``echoroo.api.web_v1.projects._tags``; only the v1 route registration is
# removed here.
api_router.include_router(taxa.router)
# W2-3 PR-1: the public ``/api/v1/recorders`` list route was unmounted in
# favour of the ``/web-api/v1/recorders`` BFF surface. The legacy handler
# survives as an importable helper (``echoroo.api.v1.recorders.list_recorders``)
# delegated to by ``echoroo.api.web_v1._recorders``; only the v1 route
# registration is removed here.
# W2-3 PR-11: the public ``/api/v1/admin/*`` routes (users / settings / licenses
# / recorders) were unmounted in favour of the ``/web-api/v1/admin/*`` BFF. The
# legacy handlers survive as importable helpers (``echoroo.api.v1.admin``)
# delegated to by ``echoroo.api.web_v1._admin_users`` / ``_admin_settings`` /
# ``_admin_licenses`` / ``_admin_recorders``; only the v1 route registration is
# removed here.
# spec/012 — public license list (FR-001/FR-002/FR-017). Bearer surface
# mirroring ``echoroo.api.web_v1.licenses``. Any authenticated caller
# may read; not gated to admins. (The ``/admin/licenses`` paths that used to
# require priority here were unmounted above, so the ordering constraint no
# longer applies.)
api_router.include_router(licenses.router)
# Detection review routers (003-detection-review)
api_router.include_router(detections.router)
api_router.include_router(confirmed_regions.router)
api_router.include_router(detection_runs.router)
# W2-3 PR-14: the browser-superseded detection-run routes (list / create / retry /
# cancel on ``detection_runs.router`` + ``available-models`` on
# ``detection_runs.models_router``) were unmounted in favour of the
# ``/web-api/v1/.../detection-runs*`` + ``/web-api/v1/detection-runs/available-models``
# BFF. The legacy handlers survive as importable helpers
# (``echoroo.api.v1.detection_runs``) delegated to by
# ``echoroo.api.web_v1.projects._detection_runs`` / ``echoroo.api.web_v1.detection_runs``;
# only ``detection_runs.router`` stays mounted (for the still-live get / update
# routes) and the route-less ``models_router`` include is removed here.
# W2-3 PR-10: the public ``/api/v1/.../datasets/{id}/upload-sessions*`` routes
# were unmounted in favour of the ``/web-api/v1/.../upload-sessions*`` BFF. The
# legacy handlers survive as importable helpers (``echoroo.api.v1.uploads``)
# delegated to by ``echoroo.api.web_v1.projects._uploads``; only the v1 route
# registration is removed here.
# Similarity search router
api_router.include_router(search_module.router)
# W2-3 PR-7: the generic ``/api/v1/projects/{project_id}/annotations/{id}/votes``
# endpoints were unmounted in favour of the ``/web-api/v1/.../votes`` BFF. The
# legacy handlers survive as importable helpers (``echoroo.api.v1.annotation_votes``)
# delegated to by ``echoroo.api.web_v1.projects._votes``; only the v1 route
# registration is removed here. (The former "must be before annotations_router"
# ordering note no longer applies — there is no v1 /votes route to collide.)
# Phase 17 follow-up — register annotation comments router that
# echoroo/api/v1/annotation_comments.py declared in Phase 3 but never
# wired into the app factory (its module docstring still flagged this
# as a follow-up). Without this line contracts/detections.yaml's
# /projects/{id}/annotations/{annotationId}/comments path drifts from
# the live OpenAPI surface (Codex Round X follow-up #4).
api_router.include_router(annotation_comments.router)
# W2-3 PR-18: the browser-superseded search routes (10 session CRUD/export/
# distribution/sample handlers + POST /batch + GET /jobs/{job_id} +
# GET /embedding-stats on ``search_module.router``, plus the search-annotation
# ``POST /projects/{project_id}/annotations`` on ``search_module.annotations_router``)
# were unmounted in favour of the ``/web-api/v1/.../search*`` +
# ``/web-api/v1/.../annotations`` BFF. The legacy handlers survive as importable
# helpers (``echoroo.api.v1.search.{sessions,batch,similarity,annotations}``)
# delegated to by ``echoroo.api.web_v1.projects._search``. The ``annotations_router``
# include is removed here; ``search_module.router`` stays mounted for the three
# KEEP routes (reference-audio / similar / similar-by-audio).
# W2-3 PR-15: the public ``/api/v1/projects/{project_id}/custom-models*`` routes
# (13 handlers: list / create / get / update / delete / train / status / apply /
# detection-runs / seed-samples / suggest-samples / sampling-rounds list+detail)
# were unmounted in favour of the ``/web-api/v1/.../custom-models*`` BFF. The
# legacy handlers survive as importable helpers (``echoroo.api.v1.custom_models``)
# delegated to by ``echoroo.api.web_v1.projects._custom_models``; only the v1
# route registration is removed here.
# Xeno-canto proxy router
api_router.include_router(xeno_canto.router)

# Cross-model evaluation router (003-annotation A3)
# W2-3 PR-5: the public ``/api/v1/annotation-sets/*/evaluate`` +
# ``/api/v1/evaluation-runs*`` routes were unmounted in favour of the
# project-scoped ``/web-api/v1/projects/{project_id}/...`` evaluation BFF. The
# legacy handlers survive as importable helpers (``echoroo.api.v1.evaluation``)
# delegated to by ``echoroo.api.web_v1.projects._annotation_sets``; only the v1
# route registrations are removed here.

# Ground-truth annotation routers (003-annotation A2)
from echoroo.api.v1 import annotation_sets as _annotation_sets  # noqa: E402

api_router.include_router(_annotation_sets.router)
# W2-3 PR-3/PR-4: the public ``/api/v1/segments/*`` and ``/api/v1/annotations/*``
# routes were unmounted in favour of the project-scoped
# ``/web-api/v1/projects/{project_id}/{segments,annotations}/*`` BFF. The legacy
# handlers survive as importable helpers (``echoroo.api.v1.segments`` /
# ``echoroo.api.v1.time_range_annotations``) delegated to by
# ``echoroo.api.web_v1.projects._annotation_sets``; only the v1 route
# registrations are removed here.
