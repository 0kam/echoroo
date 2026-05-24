"""Project upload-session BFF adapters (spec/009 PR 3a).

Spec/009 PR 3a moves the upload-session orchestration endpoints from
``/api/v1`` to ``/web-api/v1``. The legacy handlers in
``/api/v1/uploads.py`` continue to own presigned URL issuance, S3 bucket
verification, Celery task dispatch, and per-file status aggregation; the
BFF layer only adds the cookie + CSRF gating and re-uses
:func:`gate_action` for the permission decision on mutations.

Endpoints (3):

* POST ``/{pid}/datasets/{did}/upload-sessions``                → ``UPLOAD_CREATE_ACTION``
* POST ``/{pid}/datasets/{did}/upload-sessions/{sid}/complete`` → ``UPLOAD_CREATE_ACTION``
* GET  ``/{pid}/datasets/{did}/upload-sessions/{sid}``          (legacy: service-layer access check)

The actual S3 PUT to a presigned URL is intentionally NOT BFF'd —
``uploadFileToPresignedUrl`` on the frontend hits S3 directly and does
not flow through the FastAPI app.

The status GET keeps the legacy auth-only behaviour (no central
``gate_action`` call) because the legacy handler also relies on its
service layer's access check. Introducing a new gate here would diverge
from the legacy contract mid-migration; a future task may introduce a
dedicated ``UPLOAD_GET_ACTION`` once the spec defines the read-
permission semantics.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from echoroo.api.v1 import uploads as legacy_uploads
from echoroo.core.actions import UPLOAD_CREATE_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.middleware.rate_limit import (
    upload_session_complete_rate_limiter,
    upload_session_create_rate_limiter,
)
from echoroo.schemas.upload import (
    CompleteUploadResponse,
    CreateUploadSessionRequest,
    CreateUploadSessionResponse,
    UploadSessionStatusResponse,
)

router = APIRouter()


@router.post(
    "/{project_id}/datasets/{dataset_id}/upload-sessions",
    response_model=CreateUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create upload session",
    description="BFF adapter for the legacy upload-session create endpoint.",
)
async def create_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    request_body: CreateUploadSessionRequest,
    request: Request,
    current_user: CurrentUser,
    service: legacy_uploads.UploadServiceDep,
    db: DbSession,
    _rate_limit: None = Depends(upload_session_create_rate_limiter()),
) -> CreateUploadSessionResponse:
    """Delegate upload-session creation to the legacy handler."""
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_uploads.create_upload_session(
        project_id=project_id,
        dataset_id=dataset_id,
        request_body=request_body,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        _rate_limit=_rate_limit,
    )


@router.post(
    "/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}/complete",
    response_model=CompleteUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Complete upload session",
    description="BFF adapter for the legacy upload-session complete endpoint.",
)
async def complete_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_uploads.UploadServiceDep,
    db: DbSession,
    _rate_limit: None = Depends(upload_session_complete_rate_limiter()),
) -> CompleteUploadResponse:
    """Delegate upload-session completion to the legacy handler."""
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_uploads.complete_upload_session(
        project_id=project_id,
        dataset_id=dataset_id,
        session_id=session_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        _rate_limit=_rate_limit,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}",
    response_model=UploadSessionStatusResponse,
    summary="Get upload session status",
    description="BFF adapter for the legacy upload-session status endpoint.",
)
async def get_upload_session_status(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    service: legacy_uploads.UploadServiceDep,
) -> UploadSessionStatusResponse:
    """Delegate upload-session status to the legacy handler."""
    return await legacy_uploads.get_upload_session_status(
        project_id=project_id,
        dataset_id=dataset_id,
        session_id=session_id,
        current_user=current_user,
        service=service,
    )
