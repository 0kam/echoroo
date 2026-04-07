"""Generic annotation vote endpoints.

Provides vote endpoints that work with ANY annotation in a project,
not just those from a specific detection run. This is used by the
similarity search results where annotations are created on-the-fly
and are not associated with a detection run.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import select as sa_select

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.models.project import Project
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
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


@router.get(
    "/{annotation_id}/votes",
    response_model=VoteSummaryResponse,
    summary="Get vote summary for annotation",
    description="Get vote counts and individual votes for any annotation in the project",
)
async def get_annotation_votes(
    project_id: UUID,
    annotation_id: UUID,
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
) -> VoteSummaryResponse:
    """Get vote summary for an annotation.

    Works with any annotation ID (detection run annotations, search
    annotations, or manually created annotations).

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        current_user: Current authenticated user
        vote_service: Vote service instance

    Returns:
        Vote summary response

    Raises:
        401: Not authenticated
        404: Annotation not found
    """
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
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Cast or update a vote on an annotation.

    If the current user has already voted on this annotation, their existing
    vote is replaced. The annotation status is recomputed from all votes
    after each cast.

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        request: Vote cast request (vote type, optional tag suggestion, note)
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        404: Annotation not found
        422: Validation error
    """
    project_result = await db.execute(
        sa_select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    min_votes = project.review_min_votes if project else 2
    threshold = project.review_consensus_threshold if project else 0.667

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
    current_user: CurrentUser,
    vote_service: VoteServiceDep,
    db: DbSession,
) -> VoteSummaryResponse:
    """Remove the current user's vote from an annotation.

    The annotation status is recomputed from remaining votes after deletion.

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        current_user: Current authenticated user
        vote_service: Vote service instance
        db: Database session

    Returns:
        Updated vote summary response

    Raises:
        401: Not authenticated
        404: Annotation not found or no vote to delete
    """
    project_result = await db.execute(
        sa_select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    min_votes = project.review_min_votes if project else 2
    threshold = project.review_consensus_threshold if project else 0.667

    summary = await vote_service.delete_vote(
        annotation_id=annotation_id,
        user_id=current_user.id,
        min_votes=min_votes,
        threshold=threshold,
    )
    await db.commit()
    return summary
