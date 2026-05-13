"""Project membership + invitation endpoints (T511 / T512).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module (Phase 10 Batch 2):

* ``POST   /{project_id}/invitations/{token}/accept``  — accept invite (T511,
  FR-053 / FR-054).
* ``DELETE /{project_id}/invitations/{token}``         — recipient self-decline
  (T512, FR-107 / FR-101c / FR-054 / FR-055).

The router still has **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix.

Listing / inviting / patching / removing members lives elsewhere in
Phase 3 (T120-T127); this Batch 2 increment adds only the
recipient-side accept + decline so US5 (Trusted accept) and the FR-107
self-decline contract can be exercised end-to-end.

Spec rationale:
    * **Token resolution** — the URL-borne signed token is the single
      authentication factor for the recipient. The HMAC-SHA-256 signature
      is verified first (FR-052); a tampered / expired signature returns
      410 immediately. Only after the signature passes do we look up the
      DB row by ``token_hash`` (the SHA-256 digest of the raw token).
    * **Email match (FR-054)** — the caller's primary email is matched
      against the invitation's ``email_hash`` using NFKC + casefold on
      both sides. Mismatch on the *accept* path returns 403 because the
      contract spec wants the caller to learn the invite is *for someone
      else*; mismatch on the *decline* path returns 404 (enumeration
      mitigation, FR-055 — a recipient who knows the URL token would
      otherwise leak via the 403/404 split).
    * **Idempotency (FR-053)** — the ``X-Idempotency-Key`` header is
      mandatory on accept. The Redis-backed dedupe lives in the
      invitation service; replays return the same row without writing a
      duplicate ProjectMember / ProjectTrustedUser. Faults on the
      idempotency cache surface as HTTP 503 (fail-closed).
    * **Decline state machine** — pending → DECLINED is the only allowed
      transition. Already DECLINED is idempotent (still 204). All
      terminal states (accepted / expired / revoked) return 410. The
      404 statuses for token-unknown / cross-account use the same
      response code as email-mismatch so an attacker cannot enumerate
      (FR-055).
    * **Audit + email** — the post-commit side effects fire AFTER the
      main TX commits (mirrors the license / restricted-config endpoints).
      Failures are WARNING-logged and never undo the persisted state.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from echoroo.api.web_v1.projects._core import ProjectServiceDep
from echoroo.core.actions import (
    PROJECT_MEMBER_INVITE_ACTION,
    PROJECT_MEMBER_LIST_ACTION,
    PROJECT_MEMBER_REMOVE_ACTION,
    PROJECT_MEMBER_UPDATE_ROLE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.enums import ProjectInvitationKind
from echoroo.schemas.project import (
    ProjectMemberAddRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
)
from echoroo.services import invitation_service
from echoroo.services.invitation_service import (
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationInfraUnavailableError,
    InvitationStateError,
    InvitationTokenInvalidError,
    accept_invitation,
    decline_invitation_by_recipient,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
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
# T037 / T043 / T044 — /{project_id}/members
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    summary="List project members (Web UI)",
    description=(
        "Cookie-session Web UI surface mirroring the programmatic member "
        "list route. Owner / Admin only via the canonical MANAGE_MEMBERS gate."
    ),
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> list[ProjectMemberResponse]:
    """List members through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.list_members(current_user.id, project_id)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add project member (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "add route. Owner / Admin only via the canonical MANAGE_MEMBERS gate."
    ),
    responses={
        202: {"description": "Invitation email queued (FR-055 async path)"},
    },
)
async def add_project_member(
    project_id: UUID,
    payload: ProjectMemberAddRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Add a member through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_INVITE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    member = await service.add_member(current_user.id, project_id, payload)
    await db.commit()
    return member


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
    summary="Update member role (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "role update route. Owner / Admin only via MANAGE_MEMBERS."
    ),
)
async def update_project_member_role(
    project_id: UUID,
    user_id: UUID,
    payload: ProjectMemberUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Update a member role through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_UPDATE_ROLE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    member = await service.update_member_role(
        current_user.id,
        project_id,
        user_id,
        payload,
    )
    await db.commit()
    return member


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove project member (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "remove route. Owner / Admin only via MANAGE_MEMBERS."
    ),
)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Remove a member through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_REMOVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.remove_member(current_user.id, project_id, user_id)
    await db.commit()


# ---------------------------------------------------------------------------
# T511 — POST /{project_id}/invitations/{token}/accept
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/invitations/{token}/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept an invitation (FR-053 / FR-054)",
    description=(
        "Recipient-driven accept. The signed URL token authenticates the "
        "URL itself; the caller's email must match the invitation's stored "
        "hash (FR-054). The ``X-Idempotency-Key`` header is required: "
        "replays under the same key return the same outcome (200), "
        "different tokens under the same key return 409, and any cache "
        "fault surfaces as 503."
    ),
    responses={
        403: {"description": "Caller email does not match invitation hash (FR-054)"},
        410: {"description": "Invitation expired or revoked"},
    },
)
async def accept_project_invitation(
    project_id: UUID,
    token: str,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
) -> dict[str, str]:
    """Consume a pending invitation under ``project_id``.

    Args:
        project_id: Path-bound parent project — used by the audit row;
            the row's authority is the token, not the project_id, but
            we keep the project_id in the URL for clarity and so future
            tightening can verify it matches the invitation row.
        token: Signed ``{raw}.{exp}.{mac}`` envelope from the email URL.
        idempotency_key: ``X-Idempotency-Key`` header — see FR-053.

    Returns:
        ``{"kind": "member" | "trusted", "project_id": ...}`` so the
        Web UI can route the freshly-accepted member to either the
        project landing page (Member) or the Trusted-overlay aware
        surface.

    Raises:
        401: Caller is unauthenticated (no Bearer / cookie principal).
        403: ``ERR_EMAIL_MISMATCH`` per FR-054 (accept surface).
        404: Token unknown / different project_id mismatch — FR-055
            keeps the response uniform so an attacker cannot enumerate
            valid tokens.
        409: ``X-Idempotency-Key`` reused with a different token, OR
            an active membership already exists for this user without
            a matching idempotency record (see invitation_service docs).
        410: Token expired / invitation in terminal state.
        503: Idempotency cache (Redis) unreachable; fail-closed.
    """
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
                "message": "X-Idempotency-Key header is required (FR-053).",
            },
        )

    settings = get_settings()
    redis = await get_redis_connection()

    try:
        outcome = await accept_invitation(
            db,
            signed_token=token,
            current_user_id=current_user.id,
            current_user_email=current_user.email,
            hmac_secret=settings.web_session_secret,
            redis=redis,
            idempotency_key=idempotency_key,
            project_id_scope=project_id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationTokenInvalidError as exc:
        # Tampered / expired signature OR token_hash unknown. Use 404 for
        # token-not-found (FR-055 enumeration mitigation) and 410 for
        # expired / structurally-invalid signatures.
        msg = str(exc).lower()
        if "not found" in msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "ERR_INVITATION_TOKEN_INVALID",
                "message": str(exc),
            },
        ) from exc
    except InvitationEmailMismatchError as exc:
        # FR-054: 403 on the accept path so the recipient learns the
        # invite is for someone else and can ask for re-issue. The
        # decline path uses 404 instead to keep the FR-055 contract.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ERR_EMAIL_MISMATCH",
                "message": str(exc),
            },
        ) from exc
    except InvitationStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "ERR_INVITATION_TERMINAL_STATE",
                "message": str(exc),
            },
        ) from exc
    except InvitationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVITATION_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    except InvitationInfraUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    invitation = outcome.invitation
    response_payload: dict[str, str] = {
        "kind": invitation.kind.value,
        "project_id": str(invitation.project_id),
    }
    if invitation.kind is ProjectInvitationKind.MEMBER and outcome.member is not None:
        response_payload["member_id"] = str(outcome.member.id)
    elif (
        invitation.kind is ProjectInvitationKind.TRUSTED
        and outcome.trusted_user is not None
    ):
        response_payload["trusted_user_id"] = str(outcome.trusted_user.id)

    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)
    return response_payload


# ---------------------------------------------------------------------------
# T512 — DELETE /{project_id}/invitations/{token}
# ---------------------------------------------------------------------------


@router.delete(
    "/{project_id}/invitations/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Recipient-driven self-decline (FR-107)",
    description=(
        "Pending → DECLINED state transition initiated by the recipient. "
        "Idempotent (already-DECLINED → 204). Terminal states "
        "(accepted / expired / revoked) → 410. Token unknown / cross-account / "
        "email mismatch all collapse to 404 per FR-055 enumeration "
        "mitigation. Owner / Admin revocation lives on a separate "
        "endpoint (future FR)."
    ),
    responses={
        404: {"description": "Invitation not found / cross-account (FR-055 enumeration mitigation)"},
        410: {"description": "Invitation already accepted / expired / revoked"},
    },
)
async def decline_project_invitation(
    project_id: UUID,
    token: str,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> None:
    """Recipient-driven self-decline.

    Args:
        project_id: Path-bound parent project — used by the audit row.
        token: Signed ``{raw}.{exp}.{mac}`` envelope.

    Raises:
        401: Caller is unauthenticated.
        404: Token unknown / cross-account mismatch / email mismatch
            (uniform per FR-055).
        410: accept / expired / revoked terminal state.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    settings = get_settings()

    # Phase 10 Batch 2 Round 2 fix (致命 3): the URL path's ``project_id``
    # is now passed into the service so a token whose invitation row
    # belongs to a *different* project surfaces uniformly as 404 (FR-055
    # enumeration mitigation). Previously the variable was discarded
    # which let an attacker who guessed a project_id confirm or deny
    # the existence of an arbitrary token under that project's URL.
    try:
        outcome = await decline_invitation_by_recipient(
            db,
            signed_token=token,
            current_user_id=current_user.id,
            current_user_email=current_user.email,
            hmac_secret=settings.web_session_secret,
            project_id_scope=project_id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationTokenInvalidError as exc:
        # FR-055: token unknown or signature failure both surface as 404
        # so the response shape is identical to the email-mismatch path.
        # An expired token is also 404 here (vs. 410 on the accept path)
        # because the spec sets the decline route to a uniform 404 for
        # *all* "cannot resolve / cannot match" outcomes, while terminal
        # states (accepted / expired / revoked) on a *valid, matched*
        # invitation surface as 410. The state-machine 410 path is taken
        # in the `InvitationStateError` branch below.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found",
        ) from exc
    except InvitationEmailMismatchError as exc:
        # FR-055: collapse to 404 on the decline surface so the caller
        # cannot infer that a *matching* token exists for someone else.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found",
        ) from exc
    except InvitationStateError as exc:
        # accepted / expired / revoked → 410 (terminal state, decline
        # is no longer possible).
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "ERR_INVITATION_TERMINAL_STATE",
                "message": str(exc),
            },
        ) from exc

    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)
    return None


__all__ = ["router"]
