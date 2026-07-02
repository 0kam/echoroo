"""Upload session API endpoints.

Phase 3 (T122, FR-006 / FR-028a / FR-110): mutating upload endpoints
(``POST`` session create / ``POST`` session complete) now route through the
central :func:`is_allowed` gate using the Action catalog in
:mod:`echoroo.core.actions`. Read endpoints (``GET`` status) keep the existing
service-layer access check.

Out-of-scope for this task (tracked in T128/T129):

* EXIF strip on uploaded media (FR-028a).
* The mandatory recording-permission acknowledge checkbox in the create-session
  request body (FR-110).

Both are flagged with TODO comments below.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from echoroo.core import s3
from echoroo.core.actions import UPLOAD_CREATE_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.middleware.rate_limit import (
    upload_session_complete_rate_limiter,
    upload_session_create_rate_limiter,
)
from echoroo.models.enums import UploadSessionStatus
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.upload import UploadFileRepository, UploadSessionRepository
from echoroo.schemas.upload import (
    CompleteUploadResponse,
    CreateUploadSessionRequest,
    CreateUploadSessionResponse,
    UploadFileStatusResponse,
    UploadSessionStatusResponse,
)
from echoroo.services.upload import UploadService

router = APIRouter(
    prefix="/projects/{project_id}/datasets/{dataset_id}/upload-sessions",
    tags=["uploads"],
)


def get_upload_service(db: DbSession) -> UploadService:
    """Create UploadService with injected database session.

    Args:
        db: Database session

    Returns:
        UploadService instance
    """
    return UploadService(
        session_repo=UploadSessionRepository(db),
        file_repo=UploadFileRepository(db),
        dataset_repo=DatasetRepository(db),
        project_repo=ProjectRepository(db),
    )


UploadServiceDep = Annotated[UploadService, Depends(get_upload_service)]


def _compute_progress_percent(
    session_status: UploadSessionStatus,
    total_files: int,
    validated_files: int,
    imported_files: int,
) -> float:
    """Compute import progress percentage from session state.

    Args:
        session_status: Current session lifecycle status
        total_files: Total number of files in the session
        validated_files: Number of files that passed validation
        imported_files: Number of files successfully imported

    Returns:
        Progress percentage in range [0.0, 100.0]
    """
    if session_status == UploadSessionStatus.IMPORTED:
        return 100.0
    if session_status == UploadSessionStatus.FAILED:
        return 0.0
    if session_status in (UploadSessionStatus.ISSUED, UploadSessionStatus.UPLOADED):
        return 0.0
    if session_status == UploadSessionStatus.VALIDATING and total_files > 0:
        return round(validated_files / total_files * 50.0, 1)
    if session_status == UploadSessionStatus.VALIDATED:
        return 50.0
    if session_status == UploadSessionStatus.IMPORTING and total_files > 0:
        return round(50.0 + imported_files / total_files * 50.0, 1)
    return 0.0


# W2-3 PR-10: the browser-facing ``/api/v1/projects/{project_id}/datasets/
# {dataset_id}/upload-sessions*`` routes were unmounted in favour of the
# ``/web-api/v1/.../upload-sessions*`` BFF (``echoroo.api.web_v1.projects._uploads``).
# The three handlers below are left as plain importable functions (no ``@router``
# decorators) because the BFF delegates to them via ``legacy_uploads.<fn>(...)``
# and reuses ``UploadServiceDep``.
async def create_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    request_body: CreateUploadSessionRequest,
    request: Request,
    current_user: CurrentUser,
    service: UploadServiceDep,
    db: DbSession,
    _rate_limit: None = Depends(upload_session_create_rate_limiter()),
) -> CreateUploadSessionResponse:
    """Create an upload session with presigned URLs.

    Guarded by :data:`UPLOAD_CREATE_ACTION` (:data:`Permission.UPLOAD`).

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        request_body: List of files to upload
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        service: Upload service instance
        db: Database session

    Returns:
        Session info with per-file presigned PUT URLs

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Dataset not found
        409: Active upload session already exists for this dataset
        422: Validation failure (extension, size, quota, or file count)
    """
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # TODO(T128, FR-110): require an explicit `recording_permissions_acknowledged`
    # boolean on `CreateUploadSessionRequest` and reject the session if it is not
    # set. The schema and service layer changes are tracked in T128.

    # Ensure S3 bucket exists before generating presigned URLs
    try:
        s3.ensure_bucket_exists()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage service unavailable",
        ) from exc

    session, presigned_files = await service.create_session(
        user_id=current_user.id,
        project_id=project_id,
        dataset_id=dataset_id,
        files=request_body.files,
    )
    await db.commit()

    return CreateUploadSessionResponse(
        session_id=str(session.id),
        status=session.status.value,
        expires_at=session.expires_at,
        total_files=session.total_files,
        total_bytes=session.total_bytes,
        files=presigned_files,
    )


async def complete_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: UploadServiceDep,
    db: DbSession,
    _rate_limit: None = Depends(upload_session_complete_rate_limiter()),
) -> CompleteUploadResponse:
    """Complete an upload session after files have been uploaded to S3.

    Guarded by :data:`UPLOAD_CREATE_ACTION` (:data:`Permission.UPLOAD`).

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        session_id: Upload session UUID
        request: FastAPI request
        current_user: Current authenticated user
        service: Upload service instance
        db: Database session

    Returns:
        Verification summary with file counts

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Session not found or does not belong to this dataset/project
        409: Session is not in ISSUED state
    """
    await gate_action(
        action=UPLOAD_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # TODO(T129, FR-028a): invoke EXIF / metadata strip on each uploaded
    # object before validation kicks off. The implementation will live in the
    # upload validation worker; this endpoint will simply assume the strip ran
    # successfully once T129 lands.

    result = await service.complete_upload(
        user_id=current_user.id,
        project_id=project_id,
        dataset_id=dataset_id,
        session_id=session_id,
    )
    await db.commit()

    # Dispatch Celery validation task when all files are verified
    if result["status"] == UploadSessionStatus.UPLOADED.value:
        try:
            from echoroo.workers.upload_tasks import validate_upload_session

            validate_upload_session.delay(str(session_id))
        except Exception:
            # Task dispatch failure is non-fatal; the session is already in UPLOADED state
            # and can be retried manually or by the beat scheduler
            import logging
            logging.getLogger(__name__).error(
                "Failed to dispatch validation task for session %s", session_id, exc_info=True,
            )

    return CompleteUploadResponse(
        session_id=result["session_id"],
        status=result["status"],
        verified_files=result["verified_files"],
        missing_files=result["missing_files"],
        mismatched_files=result["mismatched_files"],
    )


async def get_upload_session_status(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    service: UploadServiceDep,
) -> UploadSessionStatusResponse:
    """Get upload session status with per-file details.

    Read endpoint — keeps the existing service-layer access check rather than
    routing through the central gate. A future task may introduce a dedicated
    ``UPLOAD_GET_ACTION`` once the spec defines the read-permission semantics.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        session_id: Upload session UUID
        current_user: Current authenticated user
        service: Upload service instance

    Returns:
        Full session status with per-file details and progress percentage

    Raises:
        401: Not authenticated
        403: User does not have project access
        404: Dataset or session not found
    """
    session = await service.get_session_status(
        user_id=current_user.id,
        project_id=project_id,
        dataset_id=dataset_id,
        session_id=session_id,
    )

    progress_percent = _compute_progress_percent(
        session_status=session.status,
        total_files=session.total_files,
        validated_files=session.validated_files,
        imported_files=session.imported_files,
    )

    file_responses = [
        UploadFileStatusResponse(
            file_id=str(f.id),
            original_filename=f.original_filename,
            status=f.status.value,
            file_size=f.file_size,
            duration=f.duration,
            samplerate=f.samplerate,
            channels=f.channels,
            validation_error=f.validation_error,
            recording_id=str(f.recording_id) if f.recording_id else None,
        )
        for f in session.files
    ]

    return UploadSessionStatusResponse(
        session_id=str(session.id),
        status=session.status.value,
        total_files=session.total_files,
        total_bytes=session.total_bytes,
        validated_files=session.validated_files,
        imported_files=session.imported_files,
        progress_percent=progress_percent,
        error=session.error,
        files=file_responses,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
