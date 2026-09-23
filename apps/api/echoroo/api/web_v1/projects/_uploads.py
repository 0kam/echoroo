"""Project upload-session BFF adapters (spec/009 PR 3a).

Spec/009 PR 3a moves the upload-session orchestration endpoints from
``/api/v1`` to ``/web-api/v1``. The legacy handlers in
``/api/v1/uploads.py`` continue to own upload-session creation, completion,
Celery task dispatch, and per-file status aggregation; the
BFF layer only adds the cookie + CSRF gating and re-uses
:func:`gate_action` for the permission decision on mutations.

Endpoints (6):

* POST ``/{pid}/datasets/{did}/upload-sessions``                → ``UPLOAD_CREATE_ACTION``
* GET  ``/{pid}/datasets/{did}/upload-sessions/active``         → ``UPLOAD_CREATE_ACTION``
* PUT  ``/{pid}/datasets/{did}/upload-sessions/{sid}/files/{fid}/chunks`` → ``UPLOAD_CREATE_ACTION``
* POST ``/{pid}/datasets/{did}/upload-sessions/{sid}/complete`` → ``UPLOAD_CREATE_ACTION``
* POST ``/{pid}/datasets/{did}/upload-sessions/{sid}/cancel``   → ``UPLOAD_CREATE_ACTION``
* GET  ``/{pid}/datasets/{did}/upload-sessions/{sid}``          (legacy: service-layer access check)

Upload chunks now flow through :func:`put_upload_chunk` so the API can stage,
resume, and reconcile them before completion.

The status GET keeps the legacy auth-only behaviour (no central
``gate_action`` call) because the legacy handler also relies on its
service layer's access check. Introducing a new gate here would diverge
from the legacy contract mid-migration; a future task may introduce a
dedicated ``UPLOAD_GET_ACTION`` once the spec defines the read-
permission semantics.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from echoroo.api.v1 import uploads as legacy_uploads
from echoroo.core.actions import UPLOAD_CREATE_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import CurrentUser
from echoroo.middleware.rate_limit import (
    upload_chunk_rate_limiter,
    upload_session_complete_rate_limiter,
    upload_session_create_rate_limiter,
)
from echoroo.schemas.upload import (
    ActiveUploadSessionResponse,
    ChunkAcceptedResponse,
    CompleteUploadRequest,
    CompleteUploadResponse,
    CreateUploadSessionRequest,
    CreateUploadSessionResponse,
    UploadSessionStatusResponse,
)

router = APIRouter()

# Admission state is deliberately per-process; this is sufficient for one API
# container and the Redis-backed rate limiter still applies across processes.
_chunk_in_flight: dict[UUID, int] = {}
_chunk_in_flight_lock = asyncio.Lock()


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
    request_body: CompleteUploadRequest | None = Body(None),
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
        request_body=request_body,
    )


@router.get(
    "/{project_id}/datasets/{dataset_id}/upload-sessions/active",
    response_model=ActiveUploadSessionResponse,
    summary="Caller's unfinished upload session",
)
async def get_active_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_uploads.UploadServiceDep,
    db: DbSession,
) -> ActiveUploadSessionResponse:
    """Return the caller's unfinished session for upload resume."""
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    session = await service.get_active_session(
        user_id=current_user.id,
        project_id=project_id,
        dataset_id=dataset_id,
    )
    if session is None:
        return ActiveUploadSessionResponse(session=None)
    return ActiveUploadSessionResponse(
        session=legacy_uploads.build_session_status_response(session)
    )


@router.put(
    "/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}/files/{file_id}/chunks",
    response_model=ChunkAcceptedResponse,
    responses={
        409: {
            "description": (
                "Offset conflict (object detail with received_bytes) or lifecycle "
                "conflict (string detail: session not accepting chunks)."
            ),
            "content": {
                "application/json": {
                    "schema": {
                        "oneOf": [
                            {
                                "type": "object",
                                "properties": {
                                    "detail": {
                                        "type": "object",
                                        "properties": {
                                            "detail": {"type": "string"},
                                            "received_bytes": {"type": "integer"},
                                        },
                                        "required": ["detail", "received_bytes"],
                                    }
                                },
                                "required": ["detail"],
                            },
                            {
                                "type": "object",
                                "properties": {"detail": {"type": "string"}},
                                "required": ["detail"],
                            },
                        ]
                    }
                }
            },
        },
        413: {"description": "Chunk larger than UPLOAD_CHUNK_SIZE or than the declared file size"},
        422: {"description": "X-Chunk-SHA256 malformed or does not match the body"},
        429: {"description": "Too many concurrent chunk requests for this user (Retry-After: 1)"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"},
                }
            },
            "description": "Raw chunk bytes; at most UPLOAD_CHUNK_SIZE.",
        }
    },
    summary="Append one chunk",
)
async def put_upload_chunk(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    file_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_uploads.UploadServiceDep,
    db: DbSession,
    offset: int = Query(..., ge=0),
    restart: bool = Query(False),
    x_chunk_sha256: str | None = Header(None, alias="X-Chunk-SHA256"),
    _rate_limit: None = Depends(upload_chunk_rate_limiter()),
) -> ChunkAcceptedResponse:
    """Append a raw request body to one staged upload file."""
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    settings = get_settings()
    async with _chunk_in_flight_lock:
        in_flight = _chunk_in_flight.get(current_user.id, 0)
        if in_flight >= settings.UPLOAD_MAX_CONCURRENT_CHUNKS_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many concurrent chunk requests",
                headers={"Retry-After": "1"},
            )
        _chunk_in_flight[current_user.id] = in_flight + 1

    try:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                announced_length = int(content_length)
            except ValueError:
                announced_length = 0
            if announced_length > settings.UPLOAD_CHUNK_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Chunk exceeds maximum size",
                )
        # Read the body incrementally: a request without Content-Length (or
        # chunked) must be refused as soon as it exceeds the cap, never buffered
        # whole first.
        chunks: list[bytes] = []
        total = 0
        async for piece in request.stream():
            total += len(piece)
            if total > settings.UPLOAD_CHUNK_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Chunk exceeds maximum size",
                )
            chunks.append(piece)
        data = b"".join(chunks)
        result = await service.append_chunk(
            user_id=current_user.id,
            project_id=project_id,
            dataset_id=dataset_id,
            session_id=session_id,
            file_id=file_id,
            offset=offset,
            data=data,
            chunk_sha256=x_chunk_sha256,
            restart=restart,
        )
        return ChunkAcceptedResponse(**result)
    finally:
        async with _chunk_in_flight_lock:
            remaining = _chunk_in_flight.get(current_user.id, 1) - 1
            if remaining > 0:
                _chunk_in_flight[current_user.id] = remaining
            else:
                _chunk_in_flight.pop(current_user.id, None)


@router.post(
    "/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel upload session",
)
async def cancel_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_uploads.UploadServiceDep,
    db: DbSession,
) -> Response:
    """Cancel an unfinished upload session."""
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.cancel_session(
        user_id=current_user.id,
        project_id=project_id,
        dataset_id=dataset_id,
        session_id=session_id,
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
