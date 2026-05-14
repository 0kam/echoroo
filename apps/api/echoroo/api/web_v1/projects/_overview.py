"""Project overview endpoint for the first-party Web UI surface."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from echoroo.api.web_v1.projects._core import ProjectServiceDep
from echoroo.core.actions import PROJECT_GET_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.schemas.project import ProjectOverviewResponse

router = APIRouter()


@router.get(
    "/{project_id}/overview",
    response_model=ProjectOverviewResponse,
    summary="Get project overview (Web UI)",
    description=(
        "Cookie-session Web UI surface mirroring the programmatic overview "
        "route. Uses the same VIEW_PROJECT_METADATA gate and ProjectService "
        "aggregation logic as the legacy handler."
    ),
    responses={
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
    },
)
async def get_project_overview(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectOverviewResponse:
    """Return project overview data through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_project_overview(current_user.id, project_id)


__all__ = ["router"]
