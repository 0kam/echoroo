"""Annotation comment endpoints (Phase 3 scaffolding).

Phase 3 (T125, FR-008 / FR-008a / FR-040): exposes the canonical comment
endpoints behind the central :func:`is_allowed` gate so the routing surface
and the Action wiring lock in early. Full persistence is deferred until the
``AnnotationComment`` ORM model + repository land (baseline migration 0001
already provisions the ``annotation_comments`` table — see
``apps/api/alembic/versions/0001_baseline_permissions_redesign.py`` §T020c).

Action wiring:

* ``GET  /annotations/{annotation_id}/comments`` (list)   → :data:`ANNOTATION_COMMENT_LIST_ACTION`
  (:data:`Permission.VIEW_DETECTION`)
* ``POST /annotations/{annotation_id}/comments`` (create) → :data:`ANNOTATION_COMMENT_CREATE_ACTION`
  (:data:`Permission.COMMENT`)

The service / repository layer is intentionally not implemented in this task;
both handlers raise ``HTTPException(501)`` after the gate succeeds. This makes
the Stage-1 contract testable today (matrix-by-matrix unauth/forbidden cases
return the canonical 401/403) while keeping the 200/201 response stub
explicitly opt-out so the harness will not silently accept fake data.

FR-040 source determination follows the same algorithm as
:func:`echoroo.api.v1.annotation_votes._determine_vote_source` and will be
wired at the same time as :class:`AnnotationComment` persistence — see the
TODO blocks below.

The router is **not** registered with the FastAPI app factory yet. That step
lives in a follow-up Phase 3 task per the implementation plan.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select as sa_select

from echoroo.core.actions import (
    ANNOTATION_COMMENT_CREATE_ACTION,
    ANNOTATION_COMMENT_LIST_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import Action, is_allowed
from echoroo.middleware.auth import CurrentUser
from echoroo.models.project import Project
from echoroo.repositories.project import ProjectRepository

router = APIRouter(
    prefix="/projects/{project_id}/annotations",
    tags=["annotation-comments"],
)


# ---------------------------------------------------------------------------
# Request / response stubs
# ---------------------------------------------------------------------------


class AnnotationCommentCreate(BaseModel):
    """Request body for ``POST /annotations/{annotation_id}/comments``.

    Mirrors the contract in
    ``specs/006-permissions-redesign/contracts/detections.yaml`` (FR-040).
    """

    body: str = Field(..., max_length=2000, description="Comment body, ≤ 2000 chars")


class AnnotationCommentResponse(BaseModel):
    """Single comment record (FR-040 source badge)."""

    id: UUID
    annotation_id: UUID
    body: str
    source: str = Field(
        ...,
        description="FR-040 author badge: member / guest_authenticated / trusted_user",
    )


class AnnotationCommentListResponse(BaseModel):
    """``GET /annotations/{annotation_id}/comments`` response wrapper."""

    items: list[AnnotationCommentResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers (Phase 3 permission gate — mirrors annotation_votes.py)
# ---------------------------------------------------------------------------


async def _load_project(db: DbSession, project_id: UUID) -> Project:
    """Load the Project ORM row needed by :func:`is_allowed`."""
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


async def _gate(
    *,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    db: DbSession,
) -> Project:
    """Run the Stage-1 :func:`is_allowed` gate for ``action`` on ``project_id``."""
    project = await _load_project(db, project_id)
    allowed, _ = is_allowed(
        action=action,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="action denied")
    return project


async def _determine_comment_source(
    *,
    project_id: UUID,
    project: Project,
    user_id: UUID,
    db: DbSession,
) -> str:
    """Determine the FR-040 ``source`` value for a freshly-posted comment.

    Returns one of ``"member" | "guest_authenticated" | "trusted_user"``,
    using the same resolution order as
    :func:`echoroo.api.v1.annotation_votes._determine_vote_source`.
    """
    project_repo = ProjectRepository(db)
    if await project_repo.is_project_owner(project_id, user_id):
        return "member"
    if (await project_repo.get_member(project_id, user_id)) is not None:
        return "member"

    # TODO(T501 / US5 — FR-041〜046): wire ``ProjectTrustedUser`` lookup here
    # once the model + repository are introduced; an unexpired overlay row
    # for ``(project_id, user_id)`` should map to ``"trusted_user"``.
    _ = project
    return "guest_authenticated"


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
        Paginated list of comments (currently empty — see scaffolding note).

    Raises:
        401: Not authenticated
        403: Permission denied
        501: Persistence not yet implemented (see module docstring)
    """
    await _gate(
        action=ANNOTATION_COMMENT_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    # TODO(T020c / future US task): once ``AnnotationComment`` model + repo
    # land, replace this stub with an actual list query scoped to
    # ``annotation_id`` and a paginated response. Until then, surface a clear
    # 501 so callers do not interpret an empty 200 list as authoritative.
    _ = annotation_id
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="annotation comments persistence not yet implemented",
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
        501: Persistence not yet implemented (see module docstring)
    """
    project = await _gate(
        action=ANNOTATION_COMMENT_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # FR-040: classify the commenter's source. Recorded on request.state for
    # downstream observability; persistence happens once the
    # ``AnnotationComment`` ORM model is introduced.
    source = await _determine_comment_source(
        project_id=project_id,
        project=project,
        user_id=current_user.id,
        db=db,
    )
    request.state.annotation_comment_source = source
    # TODO(T020c / future US task): once ``AnnotationComment`` model + repo
    # exist, persist ``payload.body`` together with ``source`` (immutable
    # FR-040) and return the canonical row.
    _ = annotation_id, payload
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        detail="annotation comments persistence not yet implemented",
    )
