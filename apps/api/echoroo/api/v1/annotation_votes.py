"""Generic annotation vote endpoints.

Provides vote endpoints that work with ANY annotation in a project,
not just those from a specific detection run. This is used by the
similarity search results where annotations are created on-the-fly
and are not associated with a detection run.

Phase 3 (T124, FR-008 / FR-008a / FR-037): every path operation routes
through the central :func:`is_allowed` gate using the Action catalog in
:mod:`echoroo.core.actions`:

* ``GET  /votes`` (list) → :data:`ANNOTATION_VOTE_LIST_ACTION`
  (:data:`Permission.VIEW_DETECTION`)
* ``POST /votes`` (cast) → :data:`ANNOTATION_VOTE_CREATE_ACTION`
  (:data:`Permission.VOTE`) — Viewer 403 falls out naturally from the matrix.
* ``DELETE /votes`` (remove) → :data:`ANNOTATION_VOTE_CREATE_ACTION` (mutating
  vote management shares the VOTE permission contract, FR-037).

Phase 6 (T301 / FR-037 / FR-039): voter source classification is delegated to
:func:`echoroo.services.annotation_vote.classify_voter_source` and the
``(source, project_role_at_vote)`` snapshot is persisted on first vote via
``AnnotationVoteRepository.upsert``. Re-votes preserve the original snapshot
per FR-037 immutability. Response masking for non-Owner / non-Admin viewers
(FR-039) is applied by the service layer using
:func:`echoroo.services.annotation_vote.resolve_viewer_role`.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from echoroo.core.actions import (
    ANNOTATION_VOTE_CREATE_ACTION,
    ANNOTATION_VOTE_LIST_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
from echoroo.schemas.annotation_vote import VoteCastRequest, VoteSummaryResponse
from echoroo.services.annotation_vote import (
    AnnotationVoteService,
    classify_voter_source,
    resolve_viewer_role,
)

router = APIRouter(
    prefix="/projects/{project_id}/annotations",
    tags=["annotation-votes"],
)


def get_vote_service(db: DbSession) -> AnnotationVoteService:
    """Get AnnotationVoteService instance.

    Args:
        db: Database session

    Returns:
        AnnotationVoteService instance
    """
    return AnnotationVoteService(
        vote_repo=AnnotationVoteRepository(db),
        annotation_repo=AnnotationRepository(db),
    )


VoteServiceDep = Annotated[AnnotationVoteService, Depends(get_vote_service)]


@router.get(
    "/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary for annotation",
    description="Get vote counts and individual votes for any annotation in the project",
)
async def get_annotation_votes(
    project_id: UUID,
    annotation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Get vote summary for an annotation.

    Works with any annotation ID (detection run annotations, search
    annotations, or manually created annotations).

    Guarded by :data:`ANNOTATION_VOTE_LIST_ACTION`
    (:data:`Permission.VIEW_DETECTION`). Public / Restricted projects allow
    Guest reads via the canonical matrix; the gate enforces it.

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Vote summary response

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Annotation not found
    """
    project = await gate_action(
        action=ANNOTATION_VOTE_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # BOLA / IDOR guard (FR-008 / FR-037): the annotation must belong to
    # the gated project — verify via the
    # Annotation -> Recording -> Dataset -> Project chain before reading.
    annotation_repo = AnnotationRepository(db)
    if not await annotation_repo.exists_in_project(annotation_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )

    # FR-039: viewer role drives voter-id masking. Owner / Admin see UUIDs,
    # everyone else sees ``user_id=null`` for non-member / Trusted votes.
    viewer_user_id = getattr(current_user, "id", None) if current_user is not None else None
    viewer_role = await resolve_viewer_role(
        project_id=project_id,
        project=project,
        user_id=viewer_user_id,
        db=db,
    )
    return await vote_service.get_vote_summary(
        annotation_id=annotation_id,
        current_user_id=viewer_user_id,
        viewer_role=viewer_role,
        # Phase 13 P1.5 R3 (Codex follow-up): pass project-specific
        # consensus thresholds so GET summary computes status the same
        # way ``cast_vote`` does. Defaulting to 2 / 0.667 silently
        # disagrees with projects that override either field.
        min_votes=project.review_min_votes,
        threshold=project.review_consensus_threshold,
    )


@router.post(
    "/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Cast vote on annotation",
    description="Cast or update a vote on any annotation in the project",
)
async def cast_annotation_vote(
    project_id: UUID,
    annotation_id: UUID,
    request: VoteCastRequest,
    http_request: Request,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Cast or update a vote on an annotation.

    If the current user has already voted on this annotation, their existing
    vote is replaced. The annotation status is recomputed from all votes
    after each cast.

    Guarded by :data:`ANNOTATION_VOTE_CREATE_ACTION`
    (:data:`Permission.VOTE`). The matrix denies Viewer the VOTE permission,
    so Viewer attempts return 403 here without reaching the service layer
    (FR-037 / spec FR-009 §Viewer).

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        request: Vote cast request body (vote type, optional tag suggestion, note).
            Named ``request`` to preserve the existing OpenAPI contract; the
            FastAPI :class:`Request` is exposed as ``http_request``.
        http_request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        403: Permission denied (e.g. Viewer attempting to vote)
        404: Annotation not found
        422: Validation error
    """
    project = await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )

    # BOLA / IDOR guard (FR-008a / FR-037): the annotation must belong to
    # the gated project — verify via the
    # Annotation -> Recording -> Dataset -> Project chain before mutating.
    annotation_repo = AnnotationRepository(db)
    if not await annotation_repo.exists_in_project(annotation_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )

    # FR-037: classify the voter's source + role snapshot. Persisted only on
    # first creation by ``AnnotationVoteRepository.upsert`` — re-votes preserve
    # the original source / role per FR-037 immutability.
    source, role_at_vote = await classify_voter_source(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )
    http_request.state.annotation_vote_source = source.value

    # FR-039: viewer role for masking the response — same identity here, but
    # the helper centralises Owner/Admin/Member/Viewer/Authenticated mapping.
    viewer_role = await resolve_viewer_role(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )

    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

    summary = await vote_service.cast_vote(
        annotation_id=annotation_id,
        user_id=current_user.id,
        request=request,
        source=source,
        project_role_at_vote=role_at_vote,
        # Phase 13 P1.5 (T804): project_id is required on the vote row
        # (FR-061a integrity gate).
        project_id=project_id,
        viewer_role=viewer_role,
        min_votes=min_votes,
        threshold=threshold,
    )
    await db.commit()
    return summary


@router.delete(
    "/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vote from annotation",
    description="Remove the current user's vote from any annotation in the project",
)
async def delete_annotation_vote(
    project_id: UUID,
    annotation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Remove the current user's vote from an annotation.

    The annotation status is recomputed from remaining votes after deletion.

    Treated as a mutating vote action — guarded by
    :data:`ANNOTATION_VOTE_CREATE_ACTION` (:data:`Permission.VOTE`). Viewer
    therefore cannot delete a vote either, which matches the matrix.

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Annotation not found or no vote to delete
    """
    project = await gate_action(
        action=ANNOTATION_VOTE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # BOLA / IDOR guard (FR-008a / FR-037): the annotation must belong to
    # the gated project — verify via the
    # Annotation -> Recording -> Dataset -> Project chain before deleting.
    annotation_repo = AnnotationRepository(db)
    if not await annotation_repo.exists_in_project(annotation_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )

    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

    viewer_role = await resolve_viewer_role(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )

    summary = await vote_service.delete_vote(
        annotation_id=annotation_id,
        user_id=current_user.id,
        viewer_role=viewer_role,
        min_votes=min_votes,
        threshold=threshold,
    )
    await db.commit()
    return summary
