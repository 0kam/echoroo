"""Project annotation-vote BFF adapters (spec/009 PR 3a + W2-1).

Spec/009 PR 3a moved the generic annotation-vote endpoints (used by
search-result review screens where annotations are created on the fly
and are not tied to a detection-run) from ``/api/v1`` to ``/web-api/v1``.
W2-1 extends the same pattern to the detection-vote path (used by the
detection review grid). The legacy ``/api/v1/annotation_votes.py`` and
``/api/v1/detections.py`` handlers continue to own the BOLA / IDOR
guard, voter source classification, viewer-role response masking
(FR-037 / FR-039), and consensus recomputation; the BFF layer only adds
the cookie + CSRF gating and re-uses :func:`gate_action` for the
permission decision.

Endpoints (6):

* GET    ``/{pid}/annotations/{aid}/votes`` → ``ANNOTATION_VOTE_LIST_ACTION``
* POST   ``/{pid}/annotations/{aid}/votes`` → ``ANNOTATION_VOTE_CREATE_ACTION``
* DELETE ``/{pid}/annotations/{aid}/votes`` → ``ANNOTATION_VOTE_CREATE_ACTION``
* GET    ``/{pid}/detections/{did}/votes`` → ``ANNOTATION_VOTE_LIST_ACTION``
* POST   ``/{pid}/detections/{did}/votes`` → ``ANNOTATION_VOTE_CREATE_ACTION``
* DELETE ``/{pid}/detections/{did}/votes`` → ``ANNOTATION_VOTE_CREATE_ACTION``

The detection-vote adapters delegate to the legacy
``detections.py`` handlers (``get_votes`` / ``cast_vote`` /
``delete_vote``), which use their own ``VoteServiceDep`` distinct from
the annotation-votes module dependency.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import annotation_votes as legacy_annotation_votes
from echoroo.api.v1 import detections as legacy_detections
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


@router.get(
    "/{project_id}/detections/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary for detection",
    description="BFF adapter for the legacy detection vote summary endpoint.",
)
async def get_detection_votes(
    project_id: UUID,
    detection_id: UUID,
    request: Request,
    current_user: CurrentUser,
    vote_service: legacy_detections.VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Delegate detection vote summary to the legacy handler."""
    await gate_action(
        action=ANNOTATION_VOTE_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.get_votes(
        project_id=project_id,
        detection_id=detection_id,
        request=request,
        current_user=current_user,
        vote_service=vote_service,
        db=db,
    )


@router.post(
    "/{project_id}/detections/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Cast vote on detection",
    description="BFF adapter for the legacy detection cast-vote endpoint.",
)
async def cast_detection_vote(
    project_id: UUID,
    detection_id: UUID,
    request: VoteCastRequest,
    http_request: Request,
    current_user: CurrentUser,
    vote_service: legacy_detections.VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Delegate detection cast-vote to the legacy handler."""
    await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_detections.cast_vote(
        project_id=project_id,
        detection_id=detection_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        vote_service=vote_service,
        db=db,
    )


@router.delete(
    "/{project_id}/detections/{detection_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vote from detection",
    description="BFF adapter for the legacy detection delete-vote endpoint.",
)
async def delete_detection_vote(
    project_id: UUID,
    detection_id: UUID,
    request: Request,
    current_user: CurrentUser,
    vote_service: legacy_detections.VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Delegate detection delete-vote to the legacy handler."""
    await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_detections.delete_vote(
        project_id=project_id,
        detection_id=detection_id,
        request=request,
        current_user=current_user,
        vote_service=vote_service,
        db=db,
    )
