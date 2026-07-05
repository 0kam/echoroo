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

from fastapi import APIRouter, HTTPException, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.user import User
from echoroo.schemas.license import LicensePublicListResponse
from echoroo.services.license import LicenseService

router = APIRouter(prefix="/licenses", tags=["Programmatic API — Licenses"])


def _require_authenticated(current_user: User | None) -> User:
    """Return the authenticated caller or raise 401.

    spec/012 FR-017 / spec/007 guard contract: the lint
    (``scripts/lint_permission_guard.py``) requires every non-allowlisted
    path operation to invoke a canonical guard helper inside its body.
    ``_require_authenticated`` is the spec/007-sanctioned helper for
    surfaces whose semantics collapse to "any authenticated caller"
    (no project context exists). Mirrors the pattern used by
    ``apps/api/echoroo/api/web_v1/taxa.py`` and
    ``apps/api/echoroo/api/web_v1/account/dsr.py``.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user


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
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Bearer token is missing or invalid.",
        },
    },
)
async def list_public_licenses(
    db: DbSession,
    current_user: CurrentUser,
) -> LicensePublicListResponse:
    """Return the public license list."""
    _require_authenticated(current_user)
    service = LicenseService(db)
    return await service.list_public()


__all__ = ["router"]
