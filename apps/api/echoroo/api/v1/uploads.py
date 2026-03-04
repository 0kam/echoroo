"""Upload session API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from echoroo.core import s3
from echoroo.core.database import DbSession
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


@router.post(
    "",
    response_model=CreateUploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create upload session",
    description=(
        "Create a new upload session and receive presigned S3 PUT URLs for each file. "
        "Requires project admin role. Only one active session is allowed per dataset at a time."
    ),
)
async def create_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    request: CreateUploadSessionRequest,
    current_user: CurrentUser,
    service: UploadServiceDep,
    db: DbSession,
    _rate_limit: None = Depends(upload_session_create_rate_limiter()),
) -> CreateUploadSessionResponse:
    """Create an upload session with presigned URLs.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        request: List of files to upload
        current_user: Current authenticated user
        service: Upload service instance
        db: Database session

    Returns:
        Session info with per-file presigned PUT URLs

    Raises:
        401: Not authenticated
        403: Not a project admin
        404: Dataset not found
        409: Active upload session already exists for this dataset
        422: Validation failure (extension, size, quota, or file count)
    """
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
        files=request.files,
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


@router.post(
    "/{session_id}/complete",
    response_model=CompleteUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Complete upload",
    description=(
        "Verify that all files have been uploaded to S3 and transition the session "
        "to UPLOADED state. Dispatches a Celery validation task when all files are confirmed. "
        "Requires project admin role."
    ),
)
async def complete_upload_session(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    service: UploadServiceDep,
    db: DbSession,
    _rate_limit: None = Depends(upload_session_complete_rate_limiter()),
) -> CompleteUploadResponse:
    """Complete an upload session after files have been uploaded to S3.

    Args:
        project_id: Project's UUID
        dataset_id: Dataset's UUID
        session_id: Upload session UUID
        current_user: Current authenticated user
        service: Upload service instance
        db: Database session

    Returns:
        Verification summary with file counts

    Raises:
        401: Not authenticated
        403: Not a project admin or not the session owner
        404: Session not found or does not belong to this dataset/project
        409: Session is not in ISSUED state
    """
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


@router.get(
    "/{session_id}",
    response_model=UploadSessionStatusResponse,
    summary="Get upload session status",
    description=(
        "Get the current status of an upload session with per-file details. "
        "Accessible to all project members."
    ),
)
async def get_upload_session_status(
    project_id: UUID,
    dataset_id: UUID,
    session_id: UUID,
    current_user: CurrentUser,
    service: UploadServiceDep,
) -> UploadSessionStatusResponse:
    """Get upload session status with per-file details.

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
