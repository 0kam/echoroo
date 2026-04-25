"""Annotation comment endpoints.

Phase 3 (T125, FR-008 / FR-008a / FR-040): exposes the canonical comment
endpoints behind the central :func:`is_allowed` gate so the routing surface
and the Action wiring lock in early.

Action wiring:

* ``GET  /annotations/{annotation_id}/comments`` (list)   → :data:`ANNOTATION_COMMENT_LIST_ACTION`
  (:data:`Permission.VIEW_DETECTION`)
* ``POST /annotations/{annotation_id}/comments`` (create) → :data:`ANNOTATION_COMMENT_CREATE_ACTION`
  (:data:`Permission.COMMENT`)

FR-040 source determination follows the same algorithm as
:func:`echoroo.api.v1.annotation_votes._determine_vote_source`.

The router is **not** registered with the FastAPI app factory yet. That step
lives in a follow-up Phase 3 task per the implementation plan.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from echoroo.core.actions import (
    ANNOTATION_COMMENT_CREATE_ACTION,
    ANNOTATION_COMMENT_LIST_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import AnnotationVoteSource
from echoroo.models.project import Project
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_comment import AnnotationCommentRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.schemas.annotation_comment import (
    AnnotationCommentCreate,
    AnnotationCommentListResponse,
    AnnotationCommentResponse,
)

router = APIRouter(
    prefix="/projects/{project_id}/annotations",
    tags=["annotation-comments"],
)


async def _determine_comment_source(
    *,
    project_id: UUID,
    project: Project,
    user_id: UUID,
    db: DbSession,
) -> AnnotationVoteSource:
    """Determine the FR-040 ``source`` value for a freshly-posted comment.

    Returns one of ``member | guest_authenticated | trusted_user``,
    using the same resolution order as
    :func:`echoroo.api.v1.annotation_votes._determine_vote_source`.
    """
    project_repo = ProjectRepository(db)
    if await project_repo.is_project_owner(project_id, user_id):
        return AnnotationVoteSource.MEMBER
    if (await project_repo.get_member(project_id, user_id)) is not None:
        return AnnotationVoteSource.MEMBER

    # TODO(T501 / US5 — FR-041〜046): wire ``ProjectTrustedUser`` lookup here
    # once the model + repository are introduced; an unexpired overlay row
    # for ``(project_id, user_id)`` should map to ``TRUSTED_USER``.
    _ = project
    return AnnotationVoteSource.GUEST_AUTHENTICATED


# ---------------------------------------------------------------------------
# Path operations
# ---------------------------------------------------------------------------


@router.get(
    "/{annotation_id}/comments",
    response_model=AnnotationCommentListResponse,
    summary="List annotation comments",
    description="List comments for an annotation (FR-040, source badge per item)",
)
async def list_annotation_comments(
    project_id: UUID,
    annotation_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> AnnotationCommentListResponse:
    """List comments for an annotation.

    Guarded by :data:`ANNOTATION_COMMENT_LIST_ACTION`
    (:data:`Permission.VIEW_DETECTION`). Public / Restricted projects allow
    Guest reads via the canonical matrix.

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        db: Database session

    Returns:
        List of comments for the annotation.

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Annotation not found
    """
    await gate_action(
        action=ANNOTATION_COMMENT_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    annotation_repo = AnnotationRepository(db)
    if not await annotation_repo.exists_in_project(annotation_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )

    comment_repo = AnnotationCommentRepository(db)
    comments = await comment_repo.list_by_annotation(annotation_id, project_id)
    return AnnotationCommentListResponse(
        items=[AnnotationCommentResponse.model_validate(comment) for comment in comments]
    )


@router.post(
    "/{annotation_id}/comments",
    response_model=AnnotationCommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation comment",
    description="Post a comment on an annotation (FR-040, COMMENT permission)",
)
async def create_annotation_comment(
    project_id: UUID,
    annotation_id: UUID,
    payload: AnnotationCommentCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> AnnotationCommentResponse:
    """Create a new comment on an annotation.

    Guarded by :data:`ANNOTATION_COMMENT_CREATE_ACTION`
    (:data:`Permission.COMMENT`). The matrix denies Viewer the COMMENT
    permission, so Viewer attempts return 403 here without reaching the
    service layer (FR-040 / spec FR-009 §Viewer).

    Args:
        project_id: Project's UUID
        annotation_id: Annotation's UUID
        payload: Comment creation payload
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        db: Database session

    Returns:
        Created comment record with FR-040 source badge.

    Raises:
        401: Not authenticated
        403: Permission denied (e.g. Viewer attempting to comment)
        422: Validation error
        404: Annotation not found
    """
    project = await gate_action(
        action=ANNOTATION_COMMENT_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    annotation_repo = AnnotationRepository(db)
    if not await annotation_repo.exists_in_project(annotation_id, project_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotation not found",
        )

    # FR-040: classify the commenter's source. Recorded on request.state for
    # downstream observability and persisted on the comment row.
    source = await _determine_comment_source(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )
    request.state.annotation_comment_source = source

    comment_repo = AnnotationCommentRepository(db)
    comment = await comment_repo.create(
        annotation_id=annotation_id,
        project_id=project_id,
        commenter_user_id=current_user.id,
        body=payload.body.strip(),
        source=source,
    )
    await db.commit()
    return AnnotationCommentResponse.model_validate(comment)
