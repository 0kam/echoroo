"""Project ownership transfer endpoint (Phase 12 / T700, FR-057-059).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``
``/projects/{id}/transfer-ownership``.

Path operations owned by this module:

* ``POST /{project_id}/transfer-ownership`` — Owner moves ownership to
  an existing Admin (FR-057). The handler is intentionally tiny: the
  business logic lives in :mod:`echoroo.services.ownership_service` so
  the same service can be reused by a future programmatic
  ``/api/v1/projects/{id}/transfer-ownership`` route.

Authentication and transport
----------------------------
* Cookie-session principal resolved via :data:`OptionalCurrentUser`
  (the production middleware chain populates it).
* CSRF enforcement happens upstream in
  :class:`echoroo.middleware.csrf.CsrfMiddleware`.
* ``X-Idempotency-Key`` is mandatory (FR-058). The header value is
  passed through to the service which dedupes via the append-only
  ``project_audit_log`` row written by a prior call.

Error envelope mapping
----------------------
* 400 ``ERR_INVALID_TRANSFER_TARGET`` — target is not an active Admin
  of the project (FR-057).
* 401 — caller is not authenticated.
* 403 — caller is not the Owner of the project.
* 404 — project_id does not resolve.
* 409 ``ERR_CONFLICT`` — idempotency key reuse with a different target.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from echoroo.core.actions import PROJECT_TRANSFER_OWNERSHIP_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.services import ownership_service
from echoroo.services.ownership_service import (
    InvalidTransferTargetError,
    ProjectNotFoundError,
    TransferConflictError,
    peek_replay_outcome,
    transfer_ownership,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers (mirror the rest of the projects/* router for audit-row envelope)
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


# ---------------------------------------------------------------------------
# Schemas — kept local because the contract body is a single field
# ---------------------------------------------------------------------------


class TransferOwnershipRequest(BaseModel):
    """Body for ``POST /{project_id}/transfer-ownership`` (FR-057).

    The contract declares ``additionalProperties: false`` so we mirror
    that with Pydantic ``extra='forbid'``; unknown keys surface as 422.
    """

    model_config = ConfigDict(extra="forbid")

    new_owner_user_id: UUID = Field(
        ...,
        description=(
            "User receiving ownership. Must be a current active Admin of "
            "the project (FR-057)."
        ),
    )


class TransferOwnershipResponse(BaseModel):
    """Outcome envelope returned to the Owner UI."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    previous_owner_id: UUID
    new_owner_id: UUID
    replayed: bool = Field(
        ...,
        description=(
            "True iff the call hit the FR-058 idempotency replay branch "
            "(no DB mutation performed; the original transfer's outcome "
            "is echoed)."
        ),
    )


# ---------------------------------------------------------------------------
# T700 — POST /{project_id}/transfer-ownership
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/transfer-ownership",
    response_model=TransferOwnershipResponse,
    status_code=status.HTTP_200_OK,
    summary="Transfer project ownership (FR-057)",
    description=(
        "Move ``Project.owner_id`` to an existing Admin. Requires the "
        "Owner principal (``TRANSFER_OWNERSHIP`` permission, Owner-only "
        "matrix cell). Idempotent on ``X-Idempotency-Key``; replays of the "
        "same key + target return ``replayed=true``, replays with a "
        "different target return 409 ``ERR_CONFLICT``."
    ),
    responses={
        400: {"description": "Invalid transfer target (ERR_INVALID_TRANSFER_TARGET)"},
        409: {"description": "Idempotency-key replay with mismatched target (ERR_CONFLICT)"},
    },
)
async def transfer_project_ownership(
    project_id: UUID,
    payload: TransferOwnershipRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
) -> TransferOwnershipResponse:
    """Run the FR-057 ownership transfer flow."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ERR_IDEMPOTENCY_KEY_REQUIRED",
                "message": "X-Idempotency-Key header is required (FR-058).",
            },
        )

    # Phase 12 R2 致命 C3: idempotency replay short-circuit BEFORE
    # gate_action(). An HTTP retry from the original Owner whose
    # ownership has since transferred would otherwise fail the gate
    # with 403 — robbing the caller of the cached outcome they should
    # legitimately observe per FR-058. The peek probes the outbox dedupe
    # row using the same scoped key the service writes; on a hit we
    # return the cached outcome immediately. A target mismatch surfaces
    # 409 (TransferConflictError) here just like inside the service.
    try:
        cached = await peek_replay_outcome(
            db,
            project_id=project_id,
            idempotency_key=idempotency_key,
            new_owner_user_id=payload.new_owner_user_id,
            requester_id=current_user.id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except TransferConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    if cached is not None:
        return TransferOwnershipResponse(
            project_id=cached.project_id,
            previous_owner_id=cached.previous_owner_id,
            new_owner_id=cached.new_owner_id,
            replayed=True,
        )

    # Stage-1 gate: only Owner holds TRANSFER_OWNERSHIP. ``gate_action``
    # also raises 404 if the project is missing and 403 for archived
    # projects (Step 1 mutation block) — the handler does not need to
    # repeat those checks.
    await gate_action(
        action=PROJECT_TRANSFER_OWNERSHIP_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    try:
        outcome = await transfer_ownership(
            db,
            project_id=project_id,
            new_owner_user_id=payload.new_owner_user_id,
            requester_id=current_user.id,
            idempotency_key=idempotency_key,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvalidTransferTargetError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ERR_INVALID_TRANSFER_TARGET",
                "message": str(exc),
            },
        ) from exc
    except TransferConflictError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    except ProjectNotFoundError as exc:
        # Defence-in-depth: gate_action already 404's on missing project,
        # but a TOCTOU race (the project was deleted between the gate
        # lookup and the SELECT FOR UPDATE) collapses to the same code.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        ) from exc

    await db.commit()
    await ownership_service.trigger_post_commit_side_effects(outcome)

    return TransferOwnershipResponse(
        project_id=outcome.project_id,
        previous_owner_id=outcome.previous_owner_id,
        new_owner_id=outcome.new_owner_id,
        replayed=outcome.replayed,
    )


__all__ = ["router"]
