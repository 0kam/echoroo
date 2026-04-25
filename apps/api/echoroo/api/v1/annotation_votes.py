"""Generic annotation vote endpoints.

Provides vote endpoints that work with ANY annotation in a project,
not just those from a specific detection run. This is used by the
similarity search results where annotations are created on-the-fly
and are not associated with a detection run.

Phase 3 (T124, FR-008 / FR-008a / FR-037): every path operation now routes
through the central :func:`is_allowed` gate using the Action catalog in
:mod:`echoroo.core.actions`:

* ``GET  /votes`` (list) → :data:`ANNOTATION_VOTE_LIST_ACTION`
  (:data:`Permission.VIEW_DETECTION`)
* ``POST /votes`` (cast) → :data:`ANNOTATION_VOTE_CREATE_ACTION`
  (:data:`Permission.VOTE`) — Viewer 403 falls out naturally from the matrix.
* ``DELETE /votes`` (remove) → :data:`ANNOTATION_VOTE_CREATE_ACTION` (mutating
  vote management shares the VOTE permission contract, FR-037).

FR-037 source determination is computed at vote creation time from the
voter's *active* relationship with the project (member / authenticated guest /
trusted user) — see :func:`_determine_vote_source`. The legacy ``annotation_votes``
ORM table does not yet expose a ``source`` column (the baseline migration
0001 in the permissions-redesign branch adds it but the runtime model has not
been refactored). Until the model is migrated, the computed source is recorded
in ``request.state`` for downstream observability but cannot be persisted; the
TODO below tracks the follow-up that will wire :func:`_determine_vote_source`
into the repository's upsert path.
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
from echoroo.models.project import Project
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.annotation_vote import VoteCastRequest, VoteSummaryResponse
from echoroo.services.annotation_vote import AnnotationVoteService

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


async def _determine_vote_source(
    *,
    project_id: UUID,
    project: Project,
    user_id: UUID,
    db: DbSession,
) -> str:
    """Determine the FR-037 ``source`` value for a freshly-cast vote.

    Returns one of ``"member" | "guest_authenticated" | "trusted_user"``.

    Resolution order (per spec.md US2 #2 / US5 #9 / FR-037):

    1. If the user is the project owner OR a row exists in
       ``project_members`` for ``(project_id, user_id)`` → ``"member"``.
    2. Else if a *currently active* trusted-user overlay exists → ``"trusted_user"``.
       (Phase 5 / US5 will wire :class:`ProjectTrustedUser` here. The repository
       does not yet exist — :data:`_TRUSTED_USER_TODO` flags the follow-up.)
    3. Otherwise the voter is an authenticated non-member → ``"guest_authenticated"``.
    """
    project_repo = ProjectRepository(db)
    if await project_repo.is_project_owner(project_id, user_id):
        return "member"
    if (await project_repo.get_member(project_id, user_id)) is not None:
        return "member"

    # TODO(T501 / US5 — FR-041〜046): once ``ProjectTrustedUser`` model + repo
    # land, add an ``is_active_trusted_user(project_id, user_id, now)`` lookup
    # here and return ``"trusted_user"`` when the overlay row is unexpired.
    _ = project  # reserved for restricted_config trusted policy (US5)
    return "guest_authenticated"


_TRUSTED_USER_TODO = (
    "ProjectTrustedUser repository missing — trusted-user source classification "
    "deferred to Phase 5 (T501)."
)


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
    await gate_action(
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

    return await vote_service.get_vote_summary(
        annotation_id=annotation_id,
        current_user_id=current_user.id,
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

    # FR-037: classify the voter's source. The legacy ORM model does not yet
    # expose a ``source`` column (baseline migration 0001 adds it but the
    # SQLAlchemy mapping has not been refactored). Stash on request.state so
    # the response filter / observability layer can read it; persistence is
    # tracked in the follow-up TODO below.
    source = await _determine_vote_source(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )
    http_request.state.annotation_vote_source = source
    # TODO(T020c / T501): once ``annotation_votes`` model gains the
    # ``source`` + ``project_role_at_vote`` columns (FR-037 immutable),
    # forward ``source`` and the snapshot role into
    # ``AnnotationVoteRepository.upsert`` so the column is populated
    # transactionally with the vote row.

    min_votes = project.review_min_votes
    threshold = project.review_consensus_threshold

    summary = await vote_service.cast_vote(
        annotation_id=annotation_id,
        user_id=current_user.id,
        request=request,
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

    summary = await vote_service.delete_vote(
        annotation_id=annotation_id,
        user_id=current_user.id,
        min_votes=min_votes,
        threshold=threshold,
    )
    await db.commit()
    return summary
