"""Project annotation-vote BFF adapters (spec/009 PR 3a).

Spec/009 PR 3a moves the generic annotation-vote endpoints (used by
search-result review screens where annotations are created on the fly
and are not tied to a detection-run) from ``/api/v1`` to ``/web-api/v1``.
The legacy ``/api/v1/annotation_votes.py`` handlers continue to own the
BOLA / IDOR guard, voter source classification, viewer-role response
masking (FR-037 / FR-039), and consensus recomputation; the BFF layer
only adds the cookie + CSRF gating and re-uses :func:`gate_action` for
the permission decision.

Endpoints (3):

* GET    ``/{pid}/annotations/{aid}/votes`` → ``ANNOTATION_VOTE_LIST_ACTION``
* POST   ``/{pid}/annotations/{aid}/votes`` → ``ANNOTATION_VOTE_CREATE_ACTION``
* DELETE ``/{pid}/annotations/{aid}/votes`` → ``ANNOTATION_VOTE_CREATE_ACTION``

The detection-vote path (``/detections/{did}/votes`` — used by the
detection review grid) is intentionally NOT in scope here. That surface
needs the detection BFF module to be extended and is tracked
separately; the frontend still calls ``/api/v1`` for it.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import annotation_votes as legacy_annotation_votes
from echoroo.core.actions import (
    ANNOTATION_VOTE_CREATE_ACTION,
    ANNOTATION_VOTE_LIST_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.annotation_vote import VoteCastRequest, VoteSummaryResponse

router = APIRouter()


@router.get(
    "/{project_id}/annotations/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary for annotation",
    description="BFF adapter for the legacy generic annotation vote summary endpoint.",
)
async def get_annotation_votes(
    project_id: UUID,
    annotation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    vote_service: legacy_annotation_votes.VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Delegate generic annotation vote summary to the legacy handler."""
    await gate_action(
        action=ANNOTATION_VOTE_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_votes.get_annotation_votes(
        project_id=project_id,
        annotation_id=annotation_id,
        request=request,
        current_user=current_user,
        vote_service=vote_service,
        db=db,
    )


@router.post(
    "/{project_id}/annotations/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Cast vote on annotation",
    description="BFF adapter for the legacy generic annotation cast-vote endpoint.",
)
async def cast_annotation_vote(
    project_id: UUID,
    annotation_id: UUID,
    request: VoteCastRequest,
    http_request: Request,
    current_user: CurrentUser,
    vote_service: legacy_annotation_votes.VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Delegate generic annotation cast-vote to the legacy handler."""
    await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_annotation_votes.cast_annotation_vote(
        project_id=project_id,
        annotation_id=annotation_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        vote_service=vote_service,
        db=db,
    )


@router.delete(
    "/{project_id}/annotations/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vote from annotation",
    description="BFF adapter for the legacy generic annotation delete-vote endpoint.",
)
async def delete_annotation_vote(
    project_id: UUID,
    annotation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    vote_service: legacy_annotation_votes.VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Delegate generic annotation delete-vote to the legacy handler."""
    await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_annotation_votes.delete_annotation_vote(
        project_id=project_id,
        annotation_id=annotation_id,
        request=request,
        current_user=current_user,
        vote_service=vote_service,
        db=db,
    )
