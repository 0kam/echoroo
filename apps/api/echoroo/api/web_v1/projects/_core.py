"""Project CRUD endpoints — Phase 5 US1 Guest read surface + Phase 9 US4
Restricted discovery (T200, T201, T410).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``GET /``               — list projects visible to the caller. Per Phase 9
  / T410 / FR-019 the list includes Public **and** Restricted Active
  projects for *every* caller (Guest + Authenticated): Restricted projects
  expose only ``VIEW_PROJECT_METADATA, VIEW_DATASET_LIST`` so the Web UI
  surface for outsider discovery + ``mailto:`` join requests is wired
  without leaking detections / raw config. Authenticated callers
  additionally see Restricted projects they are members of via the
  membership clause (idempotent — Restricted already appears once via
  the visibility clause).
  (T201 + T410, FR-009 / FR-010 / FR-013 / FR-016 / FR-018 / FR-019 / FR-030)
* ``GET /{project_id}``   — fetch a single project (Guest only sees Public +
  Active, anything else 404 for enumeration safety).
  (T200, FR-009 / FR-010 / FR-016 / FR-018)

Mutation surfaces (``POST``, ``PATCH``, ``DELETE``) for the project root
resource live in :mod:`echoroo.api.v1.projects`; this module deliberately
covers only the Guest-aware read paths. License mutations (``PATCH
/{project_id}/license``) live in :mod:`._license`. Adding a mutation
handler here later is intentional — Phase 9 will lift the rest.

Permission engine integration:
    Read endpoints invoke :func:`echoroo.core.permissions.is_allowed`
    directly so the Guest path can return ``200`` (Public + Active),
    ``404`` (enumeration safety, FR-018) or ``403`` (Authenticated but
    matrix-denied) without going through ``gate_action`` which assumes
    a logged-in caller.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import selectinload

from echoroo.core.actions import (
    PROJECT_DELETE_ACTION,
    PROJECT_GET_ACTION,
    PROJECT_UPDATE_ACTION,
    RECORDING_LIST_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import (
    H3_RES_15,
    Permission,
    gate_action,
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
from echoroo.models.user import User
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.user import UserRepository
from echoroo.schemas.project import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSummaryListResponse,
    ProjectUpdateRequest,
)
from echoroo.schemas.recording import (
    PublicRecordingItem,
    PublicRecordingListResponse,
)
from echoroo.services.project import (
    ProjectService,
    build_project_summaries,
    resolve_current_user_role,
    scrub_owner_email_for_visibility,
)

# ---------------------------------------------------------------------------
# Helpers — Phase 5 polish round 5 (重要 1): H3 generalisation for the
# Web UI recording-list surface.
#
# ``apply_response_filter`` writes the coarsened value back onto both
# ``h3_index_member`` (canonical, post Phase 13 P4 / T807) and ``h3_index``
# (legacy alias retained for transitional callers). It reads the precise
# member cell from ``resource.h3_index_member``. The
# :class:`PublicRecordingItem` shape exposes the cell under the more
# readable name ``site_h3_index`` (it sits *on a Recording*, but
# represents the *Site's* H3, hence the prefix). We therefore mirror the
# adapter pattern from ``echoroo.api.v1.sites`` so the same stage-2
# generalisation runs against the raw site H3 (e.g. res 15) and the
# coarsened cell is written back onto the Pydantic response field.
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


def get_project_service(db: DbSession) -> ProjectService:
    """Build the shared project service used by legacy and BFF routers."""
    return ProjectService(ProjectRepository(db), UserRepository(db))


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


def _require_authenticated(current_user: User | None) -> User:
    """Return the authenticated caller or raise the existing 401 response."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user


# =============================================================================
# T201 — GET /  (list projects, Guest-aware)
# =============================================================================


@router.get(
    "/",
    response_model=ProjectSummaryListResponse,
    summary="List projects (Guest-aware)",
    description=(
        "Return projects visible to the caller. Per Phase 9 / T410 / FR-019, "
        "**Public + Restricted Active** projects are visible to every caller "
        "(Guest + Authenticated); each row is shaped as the contract "
        "``ProjectSummary`` (id / name / description / visibility / status / "
        "license / owner_display_name / dataset_count / species_preview) so "
        "the raw ``restricted_config`` blob can never leak through "
        "enumeration. Owner / Admin can still inspect the toggle state via "
        "the dedicated ``GET /projects/{id}/restricted-config`` Phase 8 "
        "endpoint. Authenticated callers additionally see Restricted "
        "projects they are members of (already covered by the visibility "
        "clause; the membership clause is kept for Dormant / Archived "
        "membership rows). The response filter still scrubs forbidden "
        "raw-coordinate fields as defence-in-depth (FR-016, FR-018, "
        "FR-019, FR-030)."
    ),
)
async def list_projects(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
) -> ProjectSummaryListResponse:
    """List projects accessible to the caller.

    FR-016: Public + Active is always visible.
    FR-019 (Phase 9 T410): Restricted + Active is visible to every caller as
        meta only — the response shape is :class:`ProjectSummary` so raw
        ``restricted_config`` is structurally absent, not merely scrubbed
        post-hoc (Phase 9 polish round 2 致命 1, contracts/projects.yaml
        ``ProjectSummary``).

    Args:
        request: Used by the response-filter cache and audit chain.
        current_user: Authenticated user or ``None`` (Guest).
        db: Database session.
        page: 1-indexed page number.
        limit: Items per page (1..100).

    Returns:
        Paginated :class:`ProjectSummaryListResponse`. Each row already
        passes through :func:`apply_response_filter` to scrub forbidden raw
        coordinate keys (defence-in-depth — :class:`ProjectSummary` does
        not expose them by design).
    """
    offset = (page - 1) * limit

    # Build the visibility predicate. FR-016 (Public meta) + FR-019
    # (Restricted meta) — both flavours surface to Guest + Authenticated;
    # Dormant / Archived stay hidden to outsiders (only the membership
    # clause for Authenticated callers can lift them).
    public_or_restricted_active = (
        Project.visibility.in_([ProjectVisibility.PUBLIC, ProjectVisibility.RESTRICTED])
    ) & (Project.status == ProjectStatus.ACTIVE)

    visibility_clause: ColumnElement[bool]
    if current_user is None:
        # Phase 9 T410 / FR-019: Guest sees Public + Restricted Active. The
        # detail / detection / config rows are still gated by the
        # permission engine (Restricted ``allow_detection_view`` etc.); the
        # list surface only carries meta.
        visibility_clause = public_or_restricted_active
        base_query = (
            select(Project)
            .where(visibility_clause)
            .options(selectinload(Project.owner))
            .order_by(Project.created_at.desc())
        )
        count_query = select(func.count(Project.id)).where(visibility_clause)
    else:
        # Authenticated: union of (Public OR Restricted) + Active and any
        # project the caller actually belongs to (covers Dormant / Archived
        # member-only access). Owners are always included via
        # ``Project.owner_id == current_user.id``. Phase 9 polish round 2
        # Major 3: filter ``ProjectMember.removed_at IS NULL`` so previously
        # removed members no longer surface their old projects under the
        # membership clause (mirrors ``models/project.py:215``
        # ``ux_project_members_active`` partial-unique semantics).
        member_subquery = select(ProjectMember.project_id).where(
            ProjectMember.user_id == current_user.id,
            ProjectMember.removed_at.is_(None),
        )
        visibility_clause = or_(
            public_or_restricted_active,
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
        count_query = select(func.count(func.distinct(Project.id))).where(visibility_clause)

    total_result = await db.execute(count_query)
    total: int = total_result.scalar_one()

    rows_result = await db.execute(base_query.offset(offset).limit(limit))
    projects = list(rows_result.scalars().unique().all())

    # Phase 9 polish round 3 致命 1 (2026-04-27): contract ``ProjectSummary``
    # assembly is delegated to the shared helper
    # :func:`echoroo.services.project.build_project_summaries` so the
    # programmatic ``/api/v1/projects`` surface and this Web UI surface
    # stay byte-identical (a future leak field added to one router would
    # otherwise drift from the other). The helper batches the
    # ``dataset_count`` aggregation into a single grouped query and
    # resolves ``owner_display_name`` from the eager-loaded
    # ``Project.owner`` row with the email-local-part fallback (FR-030).
    items = await build_project_summaries(db, projects)

    # Defence-in-depth: ``ProjectSummary`` declares no raw coordinate
    # field, but route the assembled rows through the response filter so
    # a future schema extension (e.g. accidentally adding a ``latitude``
    # field) would still get scrubbed. The filter also exercises the
    # Stage-1 cache lookup so the gate state matches the rest of this
    # router.
    normalized_role = getattr(
        request.state,
        "normalized_role",
        "Guest" if current_user is None else "Authenticated",
    )
    for project, item in zip(projects, items, strict=True):
        # Guest principal cannot be matrix-blocked here because the
        # visibility predicate above already restricts to Public /
        # Restricted Active. Authenticated callers use ``is_allowed`` to
        # populate the effective permission set the filter consults.
        _, effective = is_allowed(
            action=PROJECT_GET_ACTION,
            user=current_user,
            project=project,
            request=request,
        )
        apply_response_filter(
            obj=item,
            effective_permissions=effective,
            normalized_role=normalized_role,
            project=project,
            resource=item,
            taxon_sensitivity_map={},
            override_map={},
        )

    # Phase 9 polish round 3 Major 1 (2026-04-27): contract
    # ``ProjectListResponse`` (contracts/projects.yaml:375-383) declares
    # only ``items / total / page`` — no ``limit``. The previous shape
    # echoed ``limit`` back for symmetry with the legacy v1 surface, but
    # that was contract drift. Clients know the page size from their
    # request query.
    return ProjectSummaryListResponse(
        items=items,
        total=total,
        page=page,
    )


@router.post(
    "/",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create project (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic project "
        "create route. Any authenticated session may create a project; "
        "the creator becomes the owner."
    ),
)
async def create_project(
    payload: ProjectCreateRequest,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectResponse:
    """Create a project through the first-party BFF surface."""
    user = _require_authenticated(current_user)

    project = await service.create_project(user.id, payload)
    await db.commit()
    return project


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
        project.visibility != ProjectVisibility.PUBLIC or project.status != ProjectStatus.ACTIVE
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="action denied")

    # Defence-in-depth: ProjectResponse does not expose raw coords, but apply
    # the filter so the contract holds for downstream Detection/Recording
    # responses that share the same plumbing (FR-030).
    response = ProjectResponse.model_validate(project)
    # Phase 9 polish round 2 致命 1 (2026-04-27): scrub owner.email back
    # to ``None`` on every path that is not "Authenticated caller +
    # Restricted project". The Authenticated + Restricted branch keeps
    # the value populated so the US4 AC2 mailto: hook works.
    scrub_owner_email_for_visibility(response, project=project, current_user=current_user)
    # Phase 9 polish round 2 Major 2 (2026-04-27): resolve the caller's
    # effective project role so the Web UI can gate the Restricted
    # "Request access" callout without probing the admin-only
    # ``GET /members`` endpoint.
    response.current_user_role = await resolve_current_user_role(
        db, project=project, current_user=current_user
    )
    normalized_role = getattr(
        request.state,
        "normalized_role",
        "Guest" if current_user is None else "Authenticated",
    )
    if Permission.VIEW_PROJECT_METADATA not in effective:
        # Should not happen — is_allowed already returned True for this perm.
        # Belt-and-braces in case a future Action change widens scope.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="action denied")
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


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic PATCH "
        "route. Owner / Admin only via the canonical EDIT_PROJECT gate."
    ),
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectResponse:
    """Update a project through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    project = await service.update_project(current_user.id, project_id, payload)
    await db.commit()
    return project


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic DELETE "
        "route. Owner only via the canonical DELETE_PROJECT gate."
    ),
)
async def delete_project(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Delete a project through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.delete_project(current_user.id, project_id)
    await db.commit()


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
    dataset_id: UUID | None = Query(None, description="Filter by dataset UUID"),
    site_id: UUID | None = Query(None, description="Filter by site UUID"),
    search: str | None = Query(None, description="Case-insensitive filename search"),
    datetime_from: datetime | None = Query(None, description="Filter from datetime"),
    datetime_to: datetime | None = Query(None, description="Filter to datetime"),
    samplerate: int | None = Query(None, ge=1, description="Filter by sample rate"),
    sort_by: str = Query(
        "datetime",
        pattern="^(filename|datetime|duration|samplerate|channels)$",
        description="Sort column",
    ),
    sort_order: str = Query(
        "desc",
        pattern="^(asc|desc)$",
        description="Sort order",
    ),
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
        project.visibility != ProjectVisibility.PUBLIC or project.status != ProjectStatus.ACTIVE
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
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="action denied")

    # Belt-and-braces: the matrix should already gate this for Guests on
    # non-Public projects, but if a future change widens scope without
    # updating the visibility check above, drop back to 404.
    if Permission.VIEW_DETECTION not in effective:
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project not found",
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="action denied")

    offset = (page - 1) * limit

    # Recording does not carry project_id directly — join via Dataset to keep
    # the BOLA / IDOR boundary explicit (Recording UUIDs from Project B must
    # never leak into Project A's list).
    # Phase 13 P4 / T807: Site column is ``h3_index_member`` (full rename,
    # spec data-model §3.10). The SELECT alias ``site_h3_index`` is kept
    # because the wire field on :class:`PublicRecordingItem` is named
    # ``site_h3_index`` (more readable on a Recording surface).
    base_query = (
        select(
            Recording,
            Site.h3_index_member.label("site_h3_index"),
        )
        .join(Dataset, Dataset.id == Recording.dataset_id)
        .outerjoin(Site, Site.id == Dataset.site_id)
        .where(Dataset.project_id == project_id)
    )
    count_query = (
        select(func.count(Recording.id))
        .join(Dataset, Dataset.id == Recording.dataset_id)
        .where(Dataset.project_id == project_id)
    )
    filters: list[ColumnElement[bool]] = []
    if dataset_id is not None:
        filters.append(Recording.dataset_id == dataset_id)
    if site_id is not None:
        filters.append(Dataset.site_id == site_id)
    if search:
        filters.append(Recording.filename.ilike(f"%{search}%"))
    if datetime_from is not None:
        filters.append(Recording.datetime >= datetime_from)
    if datetime_to is not None:
        filters.append(Recording.datetime <= datetime_to)
    if samplerate is not None:
        filters.append(Recording.samplerate == samplerate)
    if filters:
        base_query = base_query.where(*filters)
        count_query = count_query.where(*filters)

    sort_columns = {
        "filename": Recording.filename,
        "datetime": Recording.datetime,
        "duration": Recording.duration,
        "samplerate": Recording.samplerate,
        "channels": Recording.channels,
    }
    sort_column = sort_columns.get(sort_by, Recording.datetime)
    if sort_order == "asc":
        base_query = base_query.order_by(sort_column.asc().nulls_last())
    else:
        base_query = base_query.order_by(sort_column.desc().nulls_last())

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
            duration_seconds = float(recording.duration) * float(recording.time_expansion or 1.0)
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
            dataset_id=recording.dataset_id,
            name=recording.filename,
            duration_seconds=duration_seconds,
            samplerate=recording.samplerate,
            channels=recording.channels,
            datetime=recording.datetime,
            datetime_parse_status=recording.datetime_parse_status,
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
