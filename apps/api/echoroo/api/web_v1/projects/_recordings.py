"""Project recording write BFF adapters (spec/009 PR 2).

Recording read + media streaming live in :mod:`._media` (spec/009 PR D0).
This module isolates the destructive PATCH / DELETE mutations so the
mutation surface stays auditable independently of the read surface.

The legacy ``/api/v1`` handlers own service orchestration, BOLA / IDOR
guards, and Stage-2 response filtering. This module only exposes the same
behaviour on the first-party session surface (cookie + CSRF), gated by the
same ``RECORDING_UPDATE_ACTION`` / ``RECORDING_DELETE_ACTION`` Actions.

The ``/recordings/{id}/download`` endpoint is intentionally NOT BFF'd in
this PR — it requires alignment with the spec/009 PR D media-token
scoped-token pattern, which is tracked as a separate piece of work.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import recordings as legacy_recordings
from echoroo.core.actions import RECORDING_DELETE_ACTION, RECORDING_UPDATE_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.recording import RecordingDetailResponse, RecordingUpdate

router = APIRouter()


@router.patch(
    "/{project_id}/recordings/{recording_id}",
    response_model=RecordingDetailResponse,
    summary="Update recording",
    description="BFF adapter for the legacy project recording PATCH endpoint.",
)
async def update_recording(
    project_id: UUID,
    recording_id: UUID,
    request: RecordingUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
) -> RecordingDetailResponse:
    """Delegate recording PATCH to the legacy handler."""
    await gate_action(
        action=RECORDING_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_recordings.update_recording(
        project_id=project_id,
        recording_id=recording_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/recordings/{recording_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete recording",
    description="BFF adapter for the legacy project recording DELETE endpoint.",
)
async def delete_recording(
    project_id: UUID,
    recording_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_recordings.RecordingServiceDep,
    db: DbSession,
) -> None:
    """Delegate recording DELETE to the legacy handler."""
    await gate_action(
        action=RECORDING_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    await legacy_recordings.delete_recording(
        project_id=project_id,
        recording_id=recording_id,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
