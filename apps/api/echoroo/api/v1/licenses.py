"""Public license list endpoint (spec/012 FR-001 / FR-002 / FR-017).

This Bearer-authenticated surface returns the master ``licenses`` table
to ANY authenticated caller — it is intentionally NOT gated to admins
(FR-017). The companion cookie-session surface lives at
``echoroo.api.web_v1.licenses``; both share the same response shape and
service layer (:meth:`echoroo.services.license.LicenseService.list_public`).

See ``specs/012-license-master-unification/contracts/licenses.yaml`` for
the wire contract this module implements.
"""

from __future__ import annotations

from fastapi import APIRouter

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.license import LicensePublicListResponse
from echoroo.services.license import LicenseService

router = APIRouter(prefix="/licenses", tags=["licenses"])


@router.get(
    "",
    response_model=LicensePublicListResponse,
    summary="List active licenses (Bearer)",
    description=(
        "Return every row in the master ``licenses`` table, ordered by "
        "``short_name`` ascending. Status 200 is returned even when the "
        "master is empty — the response is an empty ``items`` list. "
        "FR-017: this surface is readable by ANY authenticated caller "
        "(programmatic Bearer key, non-admin). Project-creation tooling "
        "consumes this endpoint to populate the license dropdown live "
        "from admin-curated data."
    ),
)
async def list_public_licenses(
    db: DbSession,
    current_user: CurrentUser,  # noqa: ARG001 — auth enforced by dependency
) -> LicensePublicListResponse:
    """Return the public license list."""
    service = LicenseService(db)
    return await service.list_public()


__all__ = ["router"]
