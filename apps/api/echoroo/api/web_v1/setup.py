"""First-run setup BFF adapters (W2-2-A).

Transport-only BFF adapter; legacy :mod:`echoroo.api.v1.setup` owns all
DB-backed setup semantics (403 already-setup guard, no-store headers).

The browser-facing setup wizard talks to ``/web-api/v1/setup/*`` so it
shares the same first-party transport surface as the rest of the Web UI.
These two endpoints run *before any user, session, or CSRF token exists*
(their purpose is to create the very first admin user), so they are
listed in :data:`echoroo.core.auth_paths.PUBLIC_AUTH_PATHS` (auth +
CSRF bypass) and classified ``SETUP_BOOTSTRAP`` in
:mod:`echoroo.core.endpoint_allowlist` (they do not call ``gate_action``).

This layer adds NO business logic, NO response translation, and NO extra
``db.commit``: each adapter injects the SAME dependencies as the legacy
handler and delegates with verbatim kwargs. In particular, the
``POST /initialize`` adapter forwards the SAME ``Response`` object the
legacy handler mutates. The no-store ``Cache-Control`` / ``Pragma`` /
``Expires`` headers are applied by :class:`~echoroo.middleware.no_store_setup.NoStoreSetupMiddleware`
(which now matches both the ``/api/v1/setup`` and ``/web-api/v1/setup``
prefixes). Forwarding the same ``Response`` object also preserves any
headers the legacy handler sets inline — belt-and-suspenders to keep
transport-only parity with the legacy contract.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from echoroo.api.v1 import setup as legacy_setup
from echoroo.core.database import DbSession
from echoroo.schemas.setup import (
    SetupCompleteResponse,
    SetupInitializeRequest,
    SetupStatusResponse,
)

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get(
    "/status",
    response_model=SetupStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get setup status",
    description=(
        "Cookie/CSRF-exempt mirror of ``GET /api/v1/setup/status``. "
        "Delegates to the legacy handler, which owns all setup semantics."
    ),
)
async def get_setup_status(
    db: DbSession,
) -> SetupStatusResponse:
    """Delegate the setup-status probe to the legacy handler."""
    return await legacy_setup.get_setup_status(db=db)


@router.post(
    "/initialize",
    response_model=SetupCompleteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize system setup",
    description=(
        "Cookie/CSRF-exempt mirror of ``POST /api/v1/setup/initialize``. "
        "Delegates to the legacy handler, which owns the 403 already-setup "
        "guard and sets the no-store response headers on the forwarded "
        "``Response`` object."
    ),
    responses={
        201: {
            "description": "Setup completed successfully, admin user created",
        },
        403: {
            "description": "Setup already completed or users already exist",
        },
        422: {
            "description": "Validation error (invalid email or short password)",
        },
    },
)
async def initialize_setup(
    request: Request,
    response: Response,
    payload: SetupInitializeRequest,
    db: DbSession,
) -> SetupCompleteResponse:
    """Delegate setup initialization to the legacy handler.

    No-store headers (``Cache-Control``, ``Pragma``, ``Expires``) are
    applied by :class:`~echoroo.middleware.no_store_setup.NoStoreSetupMiddleware`,
    which now matches both the ``/api/v1/setup`` and ``/web-api/v1/setup``
    prefixes. Forwarding the SAME ``Response`` object the legacy handler
    mutates is belt-and-suspenders: it preserves any headers the legacy
    handler sets inline and keeps transport-only parity with the legacy
    contract, but the middleware is no longer the sole source of those
    headers on this route.
    """
    return await legacy_setup.initialize_setup(
        request=request,
        response=response,
        payload=payload,
        db=db,
    )


__all__ = ["router"]
