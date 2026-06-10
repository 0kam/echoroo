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

import logging
from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import datasets as legacy_datasets
from echoroo.api.v1 import recordings as legacy_recordings
from echoroo.core.actions import (
    DATASET_DATETIME_APPLY_ACTION,
    RECORDING_DELETE_ACTION,
    RECORDING_UPDATE_ACTION,
)
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.recording import (
    RecordingDetailResponse,
    RecordingReparseDatetimesRequest,
    RecordingReparseDatetimesResponse,
    RecordingUpdate,
)
from echoroo.services.audit_service import AuditLogService

logger = logging.getLogger(__name__)

router = APIRouter()


# Mirror the request-envelope helpers in ``web_v1/admin.py`` so audit rows
# produced by this module carry the same actor / request metadata.
def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


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


@router.post(
    "/{project_id}/recordings/reparse-datetimes",
    response_model=RecordingReparseDatetimesResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-parse recording datetimes for a dataset",
    description=(
        "Fire-and-forget Celery dispatch of ``reparse_recording_datetimes`` "
        "for every recording in the body's ``dataset_id``. Saves the supplied "
        "pattern / format / timezone onto the dataset and re-parses each "
        "recording's filename. Gated by ``DATASET_DATETIME_APPLY_ACTION`` "
        "(``MANAGE_DATASET_ADMIN``) — the same admin-only gate as the "
        "dataset-level datetime-config apply endpoint. Returns the queued "
        "task id and the affected recording count, and writes a project audit "
        "entry."
    ),
)
async def reparse_recording_datetimes(
    project_id: UUID,
    body: RecordingReparseDatetimesRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_datasets.DatasetServiceDep,
    db: DbSession,
) -> RecordingReparseDatetimesResponse:
    """Re-parse datetimes for all recordings in the body's dataset.

    Mirrors the dataset-level ``datetime-config/apply`` endpoint but is
    recording-scoped (the target dataset is supplied in the body). The dataset
    is validated to belong to the path project (404 otherwise) before the
    Celery task is dispatched.
    """
    # Gate: admin-only (DATASET_DATETIME_APPLY_ACTION → MANAGE_DATASET_ADMIN).
    await gate_action(
        action=DATASET_DATETIME_APPLY_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )

    # Validate dataset access + project membership. ``get_by_id`` raises 404
    # when the dataset is missing or belongs to a different project.
    await service.get_by_id(current_user.id, project_id, body.dataset_id)

    task_id, total_recordings = await service.apply_datetime_pattern(
        body.dataset_id, body.pattern, body.format, body.timezone
    )
    await db.commit()

    # Post-commit project audit — fresh session per the audit_service
    # contract (the request-scoped ``db`` already issued SELECTs). Failures
    # are WARNING-logged so the dispatch is never blocked (FR-088 soft alert).
    try:
        async with AsyncSessionLocal() as project_audit_session:
            try:
                await AuditLogService(project_audit_session).write_project_event(
                    actor_user_id=current_user.id,
                    project_id=project_id,
                    action="dataset.datetime_config.apply",
                    request_id=_request_id(http_request),
                    ip=_client_ip(http_request),
                    user_agent=_user_agent(http_request),
                    detail={
                        "dataset_id": str(body.dataset_id),
                        "task_id": task_id,
                        "total_recordings": total_recordings,
                        "pattern": body.pattern,
                        "format": body.format,
                        "timezone": body.timezone,
                    },
                )
                await project_audit_session.commit()
            except Exception:
                await project_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — audit must never block the dispatch
        logger.warning(
            "dataset.datetime_config.apply audit write failed (FR-088 soft "
            "alert): project_id=%s dataset_id=%s actor=%s error=%r",
            project_id,
            body.dataset_id,
            current_user.id,
            exc,
        )

    return RecordingReparseDatetimesResponse(
        task_id=task_id,
        total_recordings=total_recordings,
    )
