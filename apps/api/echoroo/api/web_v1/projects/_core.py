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

from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import selectinload

from echoroo.core.actions import PROJECT_GET_ACTION, RECORDING_LIST_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import (
    H3_RES_15,
    Permission,
    is_allowed,
    load_project_or_404,
)
from echoroo.core.response_filter import apply_response_filter
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.dataset import Dataset
from echoroo.models.enums import ProjectStatus, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.schemas.project import (
    ProjectListResponse,
    ProjectResponse,
)
from echoroo.schemas.recording import (
    PublicRecordingItem,
    PublicRecordingListResponse,
)

# ---------------------------------------------------------------------------
# Helpers — Phase 5 polish round 5 (重要 1): H3 generalisation for the
# Web UI recording-list surface.
#
# ``apply_response_filter`` only generalises the field literally named
# ``h3_index`` (it reads ``resource.h3_index_member`` + writes
# ``obj.h3_index``). The :class:`PublicRecordingItem` shape exposes the cell
# under the more readable name ``site_h3_index`` (it sits *on a Recording*,
# but represents the *Site's* H3, hence the prefix). We therefore mirror
# the well-tested adapter pattern from ``echoroo.api.v1.sites`` so the same
# stage-2 generalisation runs against the raw site H3 (e.g. res 15) and
# the coarsened cell is written back onto the Pydantic response field.
# ---------------------------------------------------------------------------


def _h3_resolution(h3_index: str | None) -> int:
    """Return the H3 resolution of ``h3_index`` (15 fallback for malformed)."""
    if h3_index is None:
        return H3_RES_15
    try:
        import h3 as _h3
    except ImportError:  # pragma: no cover - h3 is an application dependency
        return H3_RES_15
    try:
        return int(_h3.get_resolution(h3_index))
    except Exception:  # noqa: BLE001 - malformed stored data should not break filtering
        return H3_RES_15


def _public_recording_filter_resource(
    site_h3_index: str | None,
) -> SimpleNamespace:
    """Adapt a site H3 cell into the Stage-2 filter's ``h3_index_member`` contract.

    Mirrors :func:`echoroo.api.v1.sites._site_filter_resource` so the same
    generalisation logic (HIDDEN clamp, taxon sensitivity, project toggle,
    Public ceiling at H3_RES_9) runs against the raw site cell and produces
    a coarsened cell for non-member callers.
    """
    return SimpleNamespace(
        h3_index_member=site_h3_index,
        h3_index_member_resolution=_h3_resolution(site_h3_index),
        # Recording carries no taxon at this surface — sensitivity is taxon-only,
        # so leaving it None lets ``compute_effective_resolution`` fall through
        # to the Public/Restricted ceiling without a sensitivity override.
        taxon_id=None,
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


# =============================================================================
# Phase 5 polish round 4 (致命 1) — GET /{project_id}/recordings
# =============================================================================


@router.get(
    "/{project_id}/recordings",
    response_model=PublicRecordingListResponse,
    summary="List recordings (Guest-aware)",
    description=(
        "Paginated recording list for the Web UI surface. Mirrors the "
        "Guest-aware semantics of ``GET /{project_id}``: signed-out callers "
        "see Public + Active projects only (FR-016 / FR-018) and any other "
        "visibility/status combination is collapsed to ``404`` for "
        "anti-enumeration. Authenticated callers go through the standard "
        "Stage-1 permission gate (``recording.list`` -> ``VIEW_DETECTION``). "
        "The response shape is intentionally minimal (no S3 object key, no "
        "content hash, no user notes) — see "
        ":class:`PublicRecordingItem` for the privacy contract."
    ),
)
async def list_public_recordings(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
) -> PublicRecordingListResponse:
    """Paginated recordings for ``project_id`` with Guest enumeration safety.

    Decision tree:
        Guest:
            * Public + Active   -> 200 with empty/N rows.
            * Anything else     -> 404 (anti-enumeration, FR-018).
        Authenticated:
            * is_allowed True   -> 200.
            * is_allowed False  -> 403 (matrix-denied).
            * Project missing   -> 404.

    Privacy:
        Each row is :class:`PublicRecordingItem` — only the fields needed to
        wire the audio stream URL and a single-line label. The model
        explicitly does NOT include ``Recording.path`` (the S3 object key),
        ``Recording.hash``, ``Recording.note``, ``time_expansion`` raw
        value, or owner/dataset metadata that could leak attribution. Raw
        site coordinates are absent by construction; the H3 cell index is
        the coarsest spatial reference exposed (FR-030).
    """
    project = await load_project_or_404(db, project_id)

    # FR-018: same enumeration safety as ``GET /{project_id}``.
    if current_user is None and (
        project.visibility != ProjectVisibility.PUBLIC
        or project.status != ProjectStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project not found",
        )

    allowed, effective = is_allowed(
        action=RECORDING_LIST_ACTION,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        if current_user is None:
            # Defence-in-depth — a Guest who clears the visibility gate above
            # but is still matrix-denied (e.g. future Restricted-Public-meta
            # rule) collapses back to 404 to keep enumeration safety.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project not found",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="action denied"
        )

    # Belt-and-braces: the matrix should already gate this for Guests on
    # non-Public projects, but if a future change widens scope without
    # updating the visibility check above, drop back to 404.
    if Permission.VIEW_DETECTION not in effective:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project not found",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="action denied"
        )

    offset = (page - 1) * limit

    # Recording does not carry project_id directly — join via Dataset to keep
    # the BOLA / IDOR boundary explicit (Recording UUIDs from Project B must
    # never leak into Project A's list).
    base_query = (
        select(
            Recording,
            Site.h3_index.label("site_h3_index"),
        )
        .join(Dataset, Dataset.id == Recording.dataset_id)
        .outerjoin(Site, Site.id == Dataset.site_id)
        .where(Dataset.project_id == project_id)
        .order_by(Recording.created_at.desc())
    )
    count_query = (
        select(func.count(Recording.id))
        .join(Dataset, Dataset.id == Recording.dataset_id)
        .where(Dataset.project_id == project_id)
    )

    total_result = await db.execute(count_query)
    total: int = total_result.scalar_one()

    rows_result = await db.execute(base_query.offset(offset).limit(limit))
    rows = rows_result.all()

    normalized_role = getattr(
        request.state,
        "normalized_role",
        "Guest" if current_user is None else "Authenticated",
    )

    items: list[PublicRecordingItem] = []
    for recording, site_h3_index in rows:
        # Apply time_expansion to the raw duration so callers see playback
        # time, not the on-disk number. Same convention as Recording.effective_duration.
        duration_seconds: float | None
        try:
            duration_seconds = float(recording.duration) * float(
                recording.time_expansion or 1.0
            )
        except (TypeError, ValueError):  # pragma: no cover - defensive
            duration_seconds = None

        # Phase 5 polish round 5 (重要 1, FR-029 / FR-030): the schema field is
        # named ``site_h3_index`` (more readable than ``h3_index`` on a
        # Recording surface) but ``apply_response_filter`` only generalises
        # ``h3_index``. Drop the raw cell into a transient adapter shape that
        # exposes ``h3_index`` for the filter, run stage 2, then copy the
        # coarsened cell back onto our response field. Without this round-trip
        # a Site stored at res 15 would leak its full precision to Guests.
        adapter = SimpleNamespace(h3_index=site_h3_index)
        apply_response_filter(
            obj=adapter,
            effective_permissions=effective,
            normalized_role=normalized_role,
            project=project,
            resource=_public_recording_filter_resource(site_h3_index),
            taxon_sensitivity_map={},
            override_map={},
        )
        generalised_h3: str | None = getattr(adapter, "h3_index", None)

        item = PublicRecordingItem(
            id=recording.id,
            project_id=project_id,
            name=recording.filename,
            duration_seconds=duration_seconds,
            site_h3_index=generalised_h3,
        )
        # Defence-in-depth: re-route the assembled item through the filter so
        # FORBIDDEN_RAW_LOCATION_FIELDS scrubbing still applies if a future
        # schema extension accidentally adds a raw lat/lng field.
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

    return PublicRecordingListResponse(
        items=items,
        total=total,
        page=page,
        limit=limit,
    )


__all__ = ["router"]
