"""Project CRUD endpoints — Phase 5 US1 Guest read surface (T200, T201).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``GET /``               — list projects visible to the caller (Guest sees
  Public + Active only; Authenticated additionally sees own Restricted).
  (T201, FR-009 / FR-010 / FR-016 / FR-018 / FR-030)
* ``GET /{project_id}``   — fetch a single project (Guest only sees Public +
  Active, anything else 404 for enumeration safety).
  (T200, FR-009 / FR-010 / FR-016 / FR-018)

Mutation surfaces (``POST``, ``PUT``, ``DELETE``) live in
:mod:`echoroo.api.v1.projects` for Phase 3; this module deliberately covers
only the read paths needed for the Guest contract. Adding a mutation handler
here later is intentional — Phase 9 will lift the rest.

Permission engine integration:
    Read endpoints invoke :func:`echoroo.core.permissions.is_allowed`
    directly so the Guest path can return ``200`` (Public + Active),
    ``404`` (enumeration safety, FR-018) or ``403`` (Authenticated but
    matrix-denied) without going through ``gate_action`` which assumes
    a logged-in caller.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import selectinload

from echoroo.core.actions import PROJECT_GET_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import (
    Permission,
    is_allowed,
    load_project_or_404,
)
from echoroo.core.response_filter import apply_response_filter
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.enums import ProjectStatus, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.schemas.project import (
    ProjectListResponse,
    ProjectResponse,
)

router = APIRouter()


# =============================================================================
# T201 — GET /  (list projects, Guest-aware)
# =============================================================================


@router.get(
    "/",
    response_model=ProjectListResponse,
    summary="List projects (Guest-aware)",
    description=(
        "Return projects visible to the caller. Guests (no session) see only "
        "Public + Active projects. Authenticated callers additionally see "
        "Restricted projects they are members of. Response filter "
        "(``apply_response_filter``) is invoked per row to scrub raw "
        "coordinates and apply H3 generalisation (FR-016, FR-018, FR-030)."
    ),
)
async def list_projects(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
) -> ProjectListResponse:
    """List projects accessible to the caller.

    FR-016: Public + Active is always visible.
    FR-018: Restricted projects are *not* enumerated to Guests — they only
        surface to Authenticated callers who hold an active membership.

    Args:
        request: Used by the response-filter cache and audit chain.
        current_user: Authenticated user or ``None`` (Guest).
        db: Database session.
        page: 1-indexed page number.
        limit: Items per page (1..100).

    Returns:
        Paginated :class:`ProjectListResponse`. Each row already passes through
        :func:`apply_response_filter` so raw lat/lng never reach the wire.
    """
    offset = (page - 1) * limit

    # Build the visibility predicate.
    public_active = (Project.visibility == ProjectVisibility.PUBLIC) & (
        Project.status == ProjectStatus.ACTIVE
    )

    visibility_clause: ColumnElement[bool]
    if current_user is None:
        # FR-018: Guest enumeration is restricted to Public + Active.
        visibility_clause = public_active
        base_query = (
            select(Project)
            .where(visibility_clause)
            .options(selectinload(Project.owner))
            .order_by(Project.created_at.desc())
        )
        count_query = select(func.count(Project.id)).where(visibility_clause)
    else:
        # Authenticated: union of Public + Active and Restricted projects the
        # caller actually belongs to (active membership). Owners are always
        # included via ``Project.owner_id == current_user.id``.
        member_subquery = (
            select(ProjectMember.project_id)
            .where(
                ProjectMember.user_id == current_user.id,
                ProjectMember.removed_at.is_(None),
            )
        )
        visibility_clause = or_(
            public_active,
            Project.owner_id == current_user.id,
            Project.id.in_(member_subquery),
        )
        base_query = (
            select(Project)
            .distinct()
            .where(visibility_clause)
            .options(selectinload(Project.owner))
            .order_by(Project.created_at.desc())
        )
        count_query = select(func.count(func.distinct(Project.id))).where(
            visibility_clause
        )

    total_result = await db.execute(count_query)
    total: int = total_result.scalar_one()

    rows_result = await db.execute(base_query.offset(offset).limit(limit))
    projects = list(rows_result.scalars().unique().all())

    # Phase 5 NOTE (T201, FR-030): ProjectResponse does not currently expose raw
    # lat/lng, but apply_response_filter still scrubs the forbidden field set
    # as a defence-in-depth precaution per ``response_filter`` contract.
    items: list[ProjectResponse] = []
    for project in projects:
        # Guest principal cannot be matrix-blocked here because the filter
        # above already restricts to Public + Active.
        _, effective = is_allowed(
            action=PROJECT_GET_ACTION,
            user=current_user,
            project=project,
            request=request,
        )
        normalized_role = getattr(
            request.state, "normalized_role", "Guest" if current_user is None else "Authenticated"
        )
        item = ProjectResponse.model_validate(project)
        apply_response_filter(
            obj=item,
            effective_permissions=effective,
            normalized_role=normalized_role,
            project=project,
            resource=item,
            taxon_sensitivity_map={},
            override_map={},
        )
        items.append(item)

    return ProjectListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


# =============================================================================
# T200 — GET /{project_id}  (detail, Guest-aware)
# =============================================================================


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project (Guest-aware)",
    description=(
        "Return a single project. Guests may only fetch Public + Active "
        "projects — anything else returns 404 (anti-enumeration, FR-018). "
        "Authenticated callers go through the standard permission gate."
    ),
)
async def get_project(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> ProjectResponse:
    """Read a single project.

    Decision tree:
        Guest:
            * Public + Active   -> 200 with response filter applied.
            * Anything else     -> 404 (anti-enumeration, FR-018).
        Authenticated:
            * is_allowed True   -> 200 with response filter applied.
            * is_allowed False  -> 403 (matrix-denied).
            * Project missing   -> 404.

    Args:
        project_id: Target project UUID.
        request: Used by the gate to stash stage-1 state.
        current_user: Authenticated user or ``None`` (Guest).
        db: Database session.

    Returns:
        :class:`ProjectResponse` with H3 generalisation + raw-coordinate scrub
        already applied (defence in depth — the ProjectResponse schema does
        not expose lat/lng directly).
    """
    project = await load_project_or_404(db, project_id)

    # FR-018: Guest enumeration safety. Anything other than
    # ``Public + Active`` looks like 404 to a signed-out caller — never
    # 403, which would leak existence.
    if current_user is None and (
        project.visibility != ProjectVisibility.PUBLIC
        or project.status != ProjectStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )

    allowed, effective = is_allowed(
        action=PROJECT_GET_ACTION,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        # Authenticated callers see 403 (the project exists; they cannot read
        # it). Guests cannot reach this branch because the visibility gate
        # above already 404'd them.
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project not found",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="action denied"
        )

    # Defence-in-depth: ProjectResponse does not expose raw coords, but apply
    # the filter so the contract holds for downstream Detection/Recording
    # responses that share the same plumbing (FR-030).
    response = ProjectResponse.model_validate(project)
    normalized_role = getattr(
        request.state,
        "normalized_role",
        "Guest" if current_user is None else "Authenticated",
    )
    if Permission.VIEW_PROJECT_METADATA not in effective:
        # Should not happen — is_allowed already returned True for this perm.
        # Belt-and-braces in case a future Action change widens scope.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="action denied"
        )
    apply_response_filter(
        obj=response,
        effective_permissions=effective,
        normalized_role=normalized_role,
        project=project,
        resource=response,
        taxon_sensitivity_map={},
        override_map={},
    )
    return response


__all__ = ["router"]
