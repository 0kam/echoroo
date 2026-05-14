"""Project annotation BFF adapters.

Spec/009 PR D keeps this browser-facing mutation thin: the legacy
``/api/v1`` handler owns schema validation, permission gating, and service
orchestration. This module only exposes the same behavior on the first-party
session surface.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from echoroo.api.v1 import annotations as legacy_annotations
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser

router = APIRouter()


@router.post(
    "/{project_id}/clip-annotations/batch-tag",
    response_model=legacy_annotations.BatchTagResponse,
    summary="Batch tag clips",
    description="BFF adapter for the legacy batch clip-tagging endpoint.",
)
async def batch_tag_clips(
    project_id: UUID,
    request: legacy_annotations.BatchTagRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_annotations.AnnotationServiceDep,
    db: DbSession,
) -> legacy_annotations.BatchTagResponse:
    """Delegate batch clip tagging to the legacy handler."""
    return await legacy_annotations.batch_tag_clips(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
