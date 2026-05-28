"""Web BFF public license list (spec/012 FR-001 / FR-002 / FR-017).

Cookie + CSRF surface that mirrors :mod:`echoroo.api.v1.licenses`. The
project-creation form (``/projects/new``) calls this endpoint to
populate the license dropdown live from admin-curated data. Both
surfaces share the same :class:`LicensePublicListResponse` payload and
delegate to
:meth:`echoroo.services.license.LicenseService.list_public`.

See ``specs/012-license-master-unification/contracts/web-licenses.yaml``
for the wire contract.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.license import LicensePublicListResponse
from echoroo.services.license import LicenseService

router = APIRouter(prefix="/licenses", tags=["licenses"])


@router.get(
    "",
    response_model=LicensePublicListResponse,
    summary="List active licenses (Web BFF)",
    description=(
        "Cookie-session mirror of ``GET /api/v1/licenses``. Returns every "
        "row in the master ``licenses`` table, ordered by ``short_name`` "
        "ascending. Status 200 is returned even when the master is empty "
        "(empty ``items`` list — the frontend renders an actionable empty "
        "state). FR-017: any authenticated caller may read; not gated to "
        "admins."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Session is missing or invalid.",
        },
    },
)
async def list_public_licenses(
    db: DbSession,
    current_user: CurrentUser,  # noqa: ARG001 — auth enforced by dependency
) -> LicensePublicListResponse:
    """Return the public license list."""
    service = LicenseService(db)
    return await service.list_public()


__all__ = ["router"]
