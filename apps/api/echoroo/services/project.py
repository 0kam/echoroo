"""Project service for business logic."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.pagination import paginate
from echoroo.models.dataset import Dataset
from echoroo.models.project import Project, ProjectMember
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.user import UserRepository
from echoroo.schemas.project import (
    ProjectCreateRequest,
    ProjectMemberAddRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
    ProjectOverviewResponse,
    ProjectOverviewSite,
    ProjectResponse,
    ProjectSummary,
    ProjectSummaryListResponse,
    ProjectUpdateRequest,
    RecordingCalendarEntry,
)
from echoroo.services.h3_utils import h3_to_center
from echoroo.services.license_service import record_initial_license

# ---------------------------------------------------------------------------
# Phase 9 polish round 3 致命 1 (2026-04-27): shared :class:`ProjectSummary`
# assembler used by both the programmatic ``GET /api/v1/projects`` surface
# (this module's :class:`ProjectService.list_projects`) and the Web UI
# ``GET /web-api/v1/projects/`` surface (``api/web_v1/projects/_core.py``).
#
# Contract: ``specs/006-permissions-redesign/contracts/projects.yaml:7``
# declares the contract for **both** ``/api/v1`` and ``/web-api/v1`` so the
# list endpoint must return :class:`ProjectSummary` rows on either prefix.
# Centralising the assembly here keeps the two routers byte-identical and
# prevents future drift (e.g. an extra leak field landing on one surface
# but not the other).
# ---------------------------------------------------------------------------


async def build_project_summaries(
    db: AsyncSession, projects: list[Project]
) -> list[ProjectSummary]:
    """Assemble contract-correct :class:`ProjectSummary` rows for ``projects``.

    The caller is responsible for:

    * Selecting the concrete ``Project`` rows visible to the principal
      (visibility / membership / status predicates).
    * Eager-loading ``Project.owner`` so the helper can derive the
      privacy-safe ``owner_display_name`` without an N+1.

    The helper itself only batches the ``dataset_count`` aggregation
    (single grouped query keyed by ``project_id``) and assembles the
    summary shape declared by ``contracts/projects.yaml:ProjectSummary``.

    The ``species_preview`` slot is currently returned as ``[]`` for every
    row — Phase 11 will wire the top-N species aggregator (a join against
    ``detections`` + ``tags``); the slot is preserved here so consumers
    can switch over without a schema migration.

    Args:
        db: Async database session used for the dataset-count batch query.
        projects: Project rows already filtered by the caller's visibility
            predicate. ``Project.owner`` MUST be eager-loaded.

    Returns:
        One :class:`ProjectSummary` per input project, in the same order.
    """
    project_ids = [p.id for p in projects]
    dataset_counts: dict[Any, int] = {}
    if project_ids:
        result = await db.execute(
            select(
                Dataset.project_id,
                func.count(Dataset.id).label("dataset_count"),
            )
            .where(Dataset.project_id.in_(project_ids))
            .group_by(Dataset.project_id)
        )
        dataset_counts = {row.project_id: int(row.dataset_count) for row in result}

    summaries: list[ProjectSummary] = []
    for project in projects:
        owner = project.owner
        # Privacy-safe display string: prefer the explicit display_name,
        # fall back to the email local-part so we never echo the full
        # address on a Public listing surface (FR-030). Empty / whitespace
        # only display_name falls through to the email branch.
        display_name_raw = (owner.display_name or "").strip() if owner is not None else ""
        if display_name_raw:
            owner_display_name = display_name_raw
        elif owner is not None and owner.email:
            owner_display_name = owner.email.split("@", 1)[0]
        else:
            owner_display_name = ""

        summaries.append(
            ProjectSummary(
                id=project.id,
                name=project.name,
                description=project.description,
                visibility=project.visibility,
                status=project.status,
                license=project.license,
                owner_display_name=owner_display_name,
                dataset_count=dataset_counts.get(project.id, 0),
                # Phase 11 backlog: top-N species across detections + tags.
                species_preview=[],
            )
        )
    return summaries


class ProjectService:
    """Service for project management business logic."""

    def __init__(self, project_repo: ProjectRepository, user_repo: UserRepository) -> None:
        """Initialize service with repositories.

        Args:
            project_repo: Project repository instance
            user_repo: User repository instance
        """
        self.project_repo = project_repo
        self.user_repo = user_repo

    async def list_projects(
        self, user_id: UUID, page: int = 1, limit: int = 20
    ) -> ProjectSummaryListResponse:
        """List all projects accessible by the current user.

        Phase 9 polish round 3 致命 1 (2026-04-27): the response shape is
        the contract-correct :class:`ProjectSummaryListResponse`
        (``contracts/projects.yaml:7`` covers both ``/api/v1`` and
        ``/web-api/v1``, and ``contracts/projects.yaml:375-383``
        ``ProjectListResponse`` declares ``items: ProjectSummary[]``).
        Returning the full :class:`ProjectResponse` (which includes
        ``restricted_config`` + owner sub-object + timestamps) on the
        programmatic surface was contract drift — :class:`ProjectSummary`
        structurally omits every internal-state field so a Restricted
        enumeration call cannot pivot from a row's metadata into anything
        else (FR-018 / FR-019 / FR-030).

        Phase 9 / T410 / FR-019: the visibility predicate already surfaces
        Public + Restricted Active projects to the caller regardless of
        membership; the repository handles the SQL union. With the response
        now being :class:`ProjectSummary`, the previous "scrub
        ``restricted_config`` to ``{}`` for outsiders" branch is unnecessary
        — the field is absent by construction.

        Args:
            user_id: Current user's UUID
            page: Page number (1-indexed)
            limit: Items per page (max 100)

        Returns:
            :class:`ProjectSummaryListResponse` with paginated summaries.
        """
        # Validate pagination parameters
        pagination = paginate(page, limit, default_page_size=20, max_page_size=100)

        projects, total = await self.project_repo.get_accessible_projects(
            user_id, pagination.page, pagination.page_size
        )

        # ``user_id`` is intentionally unused for the summary shape (the
        # contract row has no role-conditional fields), but we keep the
        # parameter so the service signature stays stable for callers that
        # already wire it through (e.g. the v1 router) and so a future
        # role-aware variant can land without changing the signature.

        items = await build_project_summaries(self.project_repo.db, projects)

        return ProjectSummaryListResponse(
            items=items,
            total=total,
            page=pagination.page,
        )

    async def create_project(
        self, user_id: UUID, request: ProjectCreateRequest
    ) -> ProjectResponse:
        """Create a new project.

        The user who creates the project becomes the owner. T320 / FR-085:
        the request schema marks ``license`` as required so a missing or
        empty value 422s before reaching this service. T320 / FR-087: the
        initial license selection is mirrored into
        :class:`ProjectLicenseHistory` so the consumer-facing audit trail
        starts at row 1 rather than row 2.

        Args:
            user_id: User creating the project
            request: Project creation data

        Returns:
            Created project

        Raises:
            HTTPException: If user not found
        """
        # Verify user exists
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Create project
        project = Project(
            name=request.name,
            description=request.description,
            visibility=request.visibility,
            license=request.license,
            restricted_config=request.restricted_config,
            owner_id=user_id,
        )

        created_project = await self.project_repo.create(project)

        # T320 (FR-085 + FR-087): record the initial license selection in
        # the same transaction as the project insert so a rollback keeps
        # the project + history in sync. The endpoint owns the final
        # ``await db.commit()``; here we only stage the row.
        await record_initial_license(
            session=self.project_repo.db,
            project_id=created_project.id,
            license=created_project.license,
            actor_user_id=user_id,
        )

        return ProjectResponse.model_validate(created_project)

    async def get_project(self, user_id: UUID, project_id: UUID) -> ProjectResponse:
        """Get project details.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Returns:
            Project details

        Raises:
            HTTPException: If project not found or access denied
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check access (owner or member)
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return ProjectResponse.model_validate(project)

    async def update_project(
        self, user_id: UUID, project_id: UUID, request: ProjectUpdateRequest
    ) -> ProjectResponse:
        """Update project settings.

        Only project admins (owner or admin role) can update projects.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            request: Update data

        Returns:
            Updated project

        Raises:
            HTTPException: If project not found or user is not admin
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Update fields
        if request.name is not None:
            project.name = request.name
        if request.description is not None:
            project.description = request.description
        if request.visibility is not None:
            project.visibility = request.visibility
        if request.license is not None:
            project.license = request.license
        if request.restricted_config is not None:
            project.restricted_config = request.restricted_config
        if request.status is not None:
            project.status = request.status

        updated_project = await self.project_repo.update(project)
        return ProjectResponse.model_validate(updated_project)

    async def delete_project(self, user_id: UUID, project_id: UUID) -> None:
        """Delete a project.

        Only the project owner can delete projects.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Raises:
            HTTPException: If project not found or user is not owner
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if user is owner
        if project.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project owner",
            )

        await self.project_repo.delete(project_id)

    async def list_members(self, user_id: UUID, project_id: UUID) -> list[ProjectMemberResponse]:
        """List all members of a project.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Returns:
            List of project members

        Raises:
            HTTPException: If project not found or access denied
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check access
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        members = await self.project_repo.list_members(project_id)
        return [ProjectMemberResponse.model_validate(m) for m in members]

    async def add_member(
        self, user_id: UUID, project_id: UUID, request: ProjectMemberAddRequest
    ) -> ProjectMemberResponse:
        """Add a member to a project.

        Only project admins can add members.

        Args:
            user_id: Current user's UUID (must be admin)
            project_id: Project's UUID
            request: Member data (email and role)

        Returns:
            Created project member

        Raises:
            HTTPException: If project not found, user not admin, target user not found,
                          or user already member
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if current user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Find target user by email
        target_user = await self.user_repo.get_by_email(request.email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Check if user is already a member
        existing_member = await self.project_repo.get_member(project_id, target_user.id)
        if existing_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already member",
            )

        # Create member
        member = ProjectMember(
            user_id=target_user.id,
            project_id=project_id,
            role=request.role,
            joined_at=datetime.now(UTC),
            invited_by_id=user_id,
        )

        created_member = await self.project_repo.add_member(member)
        return ProjectMemberResponse.model_validate(created_member)

    async def update_member_role(
        self,
        user_id: UUID,
        project_id: UUID,
        member_user_id: UUID,
        request: ProjectMemberUpdateRequest,
    ) -> ProjectMemberResponse:
        """Update a member's role.

        Only project admins can update member roles. Cannot change the owner's role.

        Args:
            user_id: Current user's UUID (must be admin)
            project_id: Project's UUID
            member_user_id: Target member's user ID
            request: New role

        Returns:
            Updated project member

        Raises:
            HTTPException: If project not found, user not admin, member not found,
                          or attempting to change owner role
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if current user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Cannot change owner role (owner is not in members table)
        if project.owner_id == member_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change owner role",
            )

        # Get member
        member = await self.project_repo.get_member(project_id, member_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )

        # Update role
        member.role = request.role
        updated_member = await self.project_repo.update_member(member)
        return ProjectMemberResponse.model_validate(updated_member)

    async def get_project_overview(
        self, user_id: UUID, project_id: UUID
    ) -> ProjectOverviewResponse:
        """Get aggregated overview data for a project.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Returns:
            ProjectOverviewResponse with sites, calendar, and totals

        Raises:
            HTTPException: If project not found or access denied
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        site_rows = await self.project_repo.get_overview_sites(project_id)
        calendar_rows = await self.project_repo.get_recording_calendar(project_id)
        total_recordings, total_sites, total_duration = (
            await self.project_repo.get_overview_totals(project_id)
        )

        sites: list[ProjectOverviewSite] = []
        for row in site_rows:
            m = row._mapping
            h3_index: str = m["h3_index"]
            try:
                lat, lng = h3_to_center(h3_index)
            except Exception:
                lat, lng = None, None
            sites.append(
                ProjectOverviewSite(
                    id=m["id"],
                    name=m["name"],
                    h3_index=h3_index,
                    latitude=lat,
                    longitude=lng,
                    dataset_count=int(m["dataset_count"]),
                    recording_count=int(m["recording_count"]),
                )
            )

        calendar: list[RecordingCalendarEntry] = [
            RecordingCalendarEntry(
                year=int(row._mapping["year"]),
                month=int(row._mapping["month"]),
                site_count=int(row._mapping["site_count"]),
                recording_count=int(row._mapping["recording_count"]),
            )
            for row in calendar_rows
        ]

        return ProjectOverviewResponse(
            sites=sites,
            recording_calendar=calendar,
            total_recordings=total_recordings,
            total_sites=total_sites,
            total_duration=total_duration,
        )

    async def remove_member(
        self, user_id: UUID, project_id: UUID, member_user_id: UUID
    ) -> None:
        """Remove a member from a project.

        Only project admins can remove members. Cannot remove the owner.

        Args:
            user_id: Current user's UUID (must be admin)
            project_id: Project's UUID
            member_user_id: Member's user ID to remove

        Raises:
            HTTPException: If project not found, user not admin, member not found,
                          or attempting to remove owner
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if current user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Cannot remove owner
        if project.owner_id == member_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove owner",
            )

        # Check if member exists
        member = await self.project_repo.get_member(project_id, member_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )

        await self.project_repo.remove_member(project_id, member_user_id)
