"""Upload service for managing file upload sessions."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.core import s3
from echoroo.core.settings import get_settings
from echoroo.models.enums import UploadFileStatus, UploadSessionStatus
from echoroo.models.upload import UploadFile, UploadSession
from echoroo.repositories.dataset import DatasetRepository
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.upload import UploadFileRepository, UploadSessionRepository
from echoroo.schemas.upload import UploadFilePresignedResponse, UploadFileRequest


class UploadService:
    """Service for managing file upload sessions."""

    def __init__(
        self,
        session_repo: UploadSessionRepository,
        file_repo: UploadFileRepository,
        dataset_repo: DatasetRepository,
        project_repo: ProjectRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            session_repo: Upload session repository instance
            file_repo: Upload file repository instance
            dataset_repo: Dataset repository instance
            project_repo: Project repository instance
        """
        self.session_repo = session_repo
        self.file_repo = file_repo
        self.dataset_repo = dataset_repo
        self.project_repo = project_repo

    async def create_session(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        files: list[UploadFileRequest],
    ) -> tuple[UploadSession, list[UploadFilePresignedResponse]]:
        """Create upload session with presigned URLs.

        Validates permissions, file constraints, and generates presigned S3 PUT
        URLs for each file in the session.

        Args:
            user_id: ID of the requesting user
            project_id: Project UUID (for access control)
            dataset_id: Dataset UUID where files will be ingested
            files: List of file metadata entries to upload

        Returns:
            Tuple of (UploadSession instance, list of per-file presigned URL responses)

        Raises:
            HTTPException 403: User is not a project admin
            HTTPException 404: Dataset not found or does not belong to the project
            HTTPException 409: An active upload session already exists for this dataset
            HTTPException 422: Validation failure (bad extension, file too large, quota exceeded,
                               too many files)
        """
        settings = get_settings()

        # 1. Verify user is a project admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only project admins can create upload sessions",
            )

        # 2. Verify dataset exists and belongs to this project
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # 3. Check for existing active session
        active_session = await self.session_repo.get_active_by_dataset(dataset_id)
        if active_session is not None:
            # Auto-cancel stale ISSUED/UPLOADED sessions (user retried after a failure)
            if active_session.status in (
                UploadSessionStatus.ISSUED,
                UploadSessionStatus.UPLOADED,
            ):
                await self.session_repo.update_status(
                    active_session.id,
                    UploadSessionStatus.FAILED,
                    error="Superseded by new upload session",
                )
            else:
                # Session is actively processing (VALIDATING/VALIDATED/IMPORTING)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An active upload session is currently being processed for this dataset",
                )

        # 4. Validate file count
        if len(files) > settings.UPLOAD_MAX_SESSION_FILES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Too many files: maximum {settings.UPLOAD_MAX_SESSION_FILES} per session",
            )

        # 5. Validate each file's extension and size
        allowed_extensions = set(settings.UPLOAD_ALLOWED_EXTENSIONS)
        for file_req in files:
            ext = os.path.splitext(file_req.filename)[1].lower()
            if ext not in allowed_extensions:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"File '{file_req.filename}' has unsupported extension '{ext}'. "
                        f"Allowed: {', '.join(sorted(allowed_extensions))}"
                    ),
                )
            if file_req.size > settings.UPLOAD_MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"File '{file_req.filename}' exceeds maximum size of "
                        f"{settings.UPLOAD_MAX_FILE_SIZE} bytes"
                    ),
                )

        # 6. Validate total size against project quota (cumulative check)
        total_bytes = sum(f.size for f in files)
        current_usage = await self.session_repo.get_total_storage_by_project(project_id)
        if current_usage + total_bytes > settings.DEFAULT_STORAGE_QUOTA:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Upload would exceed project storage quota. "
                    f"Current usage: {current_usage} bytes, "
                    f"requested: {total_bytes} bytes, "
                    f"quota: {settings.DEFAULT_STORAGE_QUOTA} bytes"
                ),
            )

        # Create session record (no files yet, need session ID for object keys)
        expires_at = datetime.now(UTC) + timedelta(seconds=settings.UPLOAD_SESSION_TTL)
        session = UploadSession(
            dataset_id=dataset_id,
            created_by_id=user_id,
            status=UploadSessionStatus.ISSUED,
            total_files=len(files),
            total_bytes=total_bytes,
            expires_at=expires_at,
        )
        session = await self.session_repo.create(session)

        # Build UploadFile records and presigned URLs.
        # Use the public client so presigned URLs point to the browser-accessible endpoint.
        s3_client = s3.get_public_s3_client()
        upload_file_records: list[UploadFile] = []
        presigned_responses: list[UploadFilePresignedResponse] = []

        for file_req in files:
            ext = os.path.splitext(file_req.filename)[1].lower()
            file_uuid = uuid.uuid4()
            object_key = (
                f"uploads/{project_id}/{dataset_id}/{session.id}/{file_uuid}{ext}"
            )

            # Generate presigned PUT URL
            upload_url = s3.generate_presigned_upload_url(
                object_key=object_key,
                expiry_seconds=settings.S3_PRESIGNED_URL_EXPIRY,
                client=s3_client,
            )

            upload_file = UploadFile(
                id=file_uuid,
                session_id=session.id,
                original_filename=file_req.filename,
                object_key=object_key,
                file_size=file_req.size,
                checksum_sha256=file_req.checksum_sha256,
                status=UploadFileStatus.PENDING,
            )
            upload_file_records.append(upload_file)
            presigned_responses.append(
                UploadFilePresignedResponse(
                    file_id=str(file_uuid),
                    original_filename=file_req.filename,
                    upload_url=upload_url,
                )
            )

        # Persist file records
        await self.file_repo.create_many(upload_file_records)

        return session, presigned_responses

    async def complete_upload(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        session_id: UUID,
    ) -> dict[str, Any]:
        """Verify uploaded files and transition session to UPLOADED state.

        Checks S3 for each file's presence, updates per-file status accordingly,
        and advances the session status to UPLOADED when all files are confirmed.

        Args:
            user_id: ID of the requesting user
            project_id: Project UUID (for access control)
            dataset_id: Dataset UUID (for ownership verification)
            session_id: Upload session UUID to complete

        Returns:
            Dict with keys: session_id, status, verified_files, missing_files, mismatched_files

        Raises:
            HTTPException 403: User is not a project admin
            HTTPException 404: Session not found or does not belong to this dataset/project
            HTTPException 409: Session is not in ISSUED state
        """
        # 1. Verify user is a project admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only project admins can complete upload sessions",
            )

        # 2. Load and validate the session
        session = await self.session_repo.get_by_id(session_id)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload session not found",
            )

        # Verify dataset belongs to project
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # Verify session belongs to the specified dataset and user
        if session.dataset_id != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload session not found",
            )
        if session.created_by_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not own this upload session",
            )

        # 3. Require ISSUED state
        if session.status != UploadSessionStatus.ISSUED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Upload session is in '{session.status.value}' state; expected 'issued'",
            )

        # 4. Verify each file in S3
        s3_client = s3.get_s3_client()
        files = await self.file_repo.get_by_session(session_id)

        verified_files = 0
        missing_files = 0
        mismatched_files = 0

        for upload_file in files:
            result = s3.verify_object_exists(
                object_key=upload_file.object_key,
                expected_size=upload_file.file_size,
                client=s3_client,
            )

            if not result["exists"]:
                missing_files += 1
                # Leave file status as PENDING (not uploaded yet)
            elif not result["size_match"]:
                mismatched_files += 1
                # Mark as uploaded but size mismatch will be caught during validation
                await self.file_repo.update_status(upload_file.id, UploadFileStatus.UPLOADED)
                verified_files += 1
            else:
                verified_files += 1
                await self.file_repo.update_status(upload_file.id, UploadFileStatus.UPLOADED)

        # 5. If all files are verified, transition session to UPLOADED (CAS guard)
        if missing_files == 0:
            await self.session_repo.update_status(
                session_id,
                UploadSessionStatus.UPLOADED,
                expected_status=UploadSessionStatus.ISSUED,
            )
            new_status = UploadSessionStatus.UPLOADED
        else:
            # Some files still missing; session stays ISSUED for retry
            new_status = UploadSessionStatus.ISSUED

        return {
            "session_id": str(session_id),
            "status": new_status.value,
            "verified_files": verified_files,
            "missing_files": missing_files,
            "mismatched_files": mismatched_files,
        }

    async def get_session_status(
        self,
        user_id: UUID,
        project_id: UUID,
        dataset_id: UUID,
        session_id: UUID,
    ) -> UploadSession:
        """Get session with access check.

        Verifies user has project access, dataset belongs to the project, and
        the session belongs to the dataset.

        Args:
            user_id: ID of the requesting user
            project_id: Project UUID (for access control)
            dataset_id: Dataset UUID (for ownership verification)
            session_id: Upload session UUID to retrieve

        Returns:
            UploadSession instance with files eagerly loaded

        Raises:
            HTTPException 403: User does not have project access
            HTTPException 404: Dataset or session not found / ownership mismatch
        """
        # Verify user has any project access (members can view status)
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this project",
            )

        # Verify dataset belongs to the project
        dataset = await self.dataset_repo.get_by_id(dataset_id)
        if dataset is None or dataset.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dataset not found",
            )

        # Load session
        session = await self.session_repo.get_by_id(session_id)
        if session is None or session.dataset_id != dataset_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Upload session not found",
            )

        return session
