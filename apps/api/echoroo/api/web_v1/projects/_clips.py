"""Project clip write BFF adapters (spec/009 PR 3a).

Clip read endpoints (GET list + GET detail) already live in
:mod:`._media` (spec/009 PR D0) because they share dependency wiring
with the recording media + clip media streaming surface. PR 3a moves the
write surface — create, update, delete, auto-generate — onto
``/web-api/v1`` so the frontend can finish migrating off ``/api/v1`` for
the clip-management screens.

Endpoints (4):

* POST   ``/{pid}/recordings/{rid}/clips``           → ``CLIP_CREATE_ACTION``
* PATCH  ``/{pid}/recordings/{rid}/clips/{cid}``     → ``CLIP_UPDATE_ACTION``
* DELETE ``/{pid}/recordings/{rid}/clips/{cid}``     → ``CLIP_DELETE_ACTION``
* POST   ``/{pid}/recordings/{rid}/clips/generate``  → ``CLIP_GENERATE_ACTION``

The audio / spectrogram / download GETs are intentionally **NOT** moved
in this PR — they require alignment with the spec/009 PR D media-token
scoped-token pattern, which is tracked separately.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import clips as legacy_clips
from echoroo.core.actions import (
    CLIP_CREATE_ACTION,
    CLIP_DELETE_ACTION,
    CLIP_GENERATE_ACTION,
    CLIP_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.clip import (
    ClipCreate,
    ClipDetailResponse,
    ClipGenerateRequest,
    ClipGenerateResponse,
    ClipUpdate,
)

router = APIRouter()


@router.post(
    "/{project_id}/recordings/{recording_id}/clips",
    response_model=ClipDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create clip",
    description="BFF adapter for the legacy project clip create endpoint.",
)
async def create_clip(
    project_id: UUID,
    recording_id: UUID,
    request: ClipCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_clips.ClipServiceDep,
    db: DbSession,
) -> ClipDetailResponse:
    """Delegate clip creation to the legacy handler."""
    await gate_action(
        action=CLIP_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_clips.create_clip(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


# NOTE: ``/generate`` must be declared BEFORE ``/{clip_id}`` so FastAPI
# matches the literal segment first; otherwise the UUID parser on
# ``{clip_id}`` swallows the literal "generate" and 422s.
@router.post(
    "/{project_id}/recordings/{recording_id}/clips/generate",
    response_model=ClipGenerateResponse,
    summary="Generate clips",
    description="BFF adapter for the legacy auto-generate clips endpoint.",
)
async def generate_clips(
    project_id: UUID,
    recording_id: UUID,
    request: ClipGenerateRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_clips.ClipServiceDep,
    db: DbSession,
) -> ClipGenerateResponse:
    """Delegate clip auto-generation to the legacy handler."""
    await gate_action(
        action=CLIP_GENERATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_clips.generate_clips(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.patch(
    "/{project_id}/recordings/{recording_id}/clips/{clip_id}",
    response_model=ClipDetailResponse,
    summary="Update clip",
    description="BFF adapter for the legacy project clip update endpoint.",
)
async def update_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: ClipUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_clips.ClipServiceDep,
    db: DbSession,
) -> ClipDetailResponse:
    """Delegate clip update to the legacy handler."""
    await gate_action(
        action=CLIP_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_clips.update_clip(
        project_id=project_id,
        recording_id=recording_id,
        clip_id=clip_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/recordings/{recording_id}/clips/{clip_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete clip",
    description="BFF adapter for the legacy project clip delete endpoint.",
)
async def delete_clip(
    project_id: UUID,
    recording_id: UUID,
    clip_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_clips.ClipServiceDep,
    db: DbSession,
) -> None:
    """Delegate clip delete to the legacy handler."""
    await gate_action(
        action=CLIP_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_clips.delete_clip(
        project_id=project_id,
        recording_id=recording_id,
        clip_id=clip_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
