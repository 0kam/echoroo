"""Upload session and file repositories for database operations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.dataset import Dataset
from echoroo.models.enums import UploadFileStatus, UploadSessionStatus
from echoroo.models.upload import UploadFile, UploadSession

# Statuses that indicate an active (in-progress) session
_ACTIVE_STATUSES = (
    UploadSessionStatus.ISSUED,
    UploadSessionStatus.UPLOADED,
    UploadSessionStatus.VALIDATING,
    UploadSessionStatus.VALIDATED,
    UploadSessionStatus.IMPORTING,
)

# Statuses that indicate a stale mid-processing session
_STALE_STATUSES = (
    UploadSessionStatus.UPLOADED,
    UploadSessionStatus.VALIDATING,
    UploadSessionStatus.VALIDATED,
    UploadSessionStatus.IMPORTING,
)


class UploadSessionRepository:
    """Repository for UploadSession entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def create(self, session: UploadSession) -> UploadSession:
        """Persist a new upload session (with its files pre-attached).

        Args:
            session: UploadSession instance to create

        Returns:
            Created session instance with relationships refreshed
        """
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session, ["dataset", "created_by", "files"])
        return session

    async def get_by_id(self, session_id: UUID) -> UploadSession | None:
        """Get an upload session by ID with files eagerly loaded.

        Args:
            session_id: Upload session UUID

        Returns:
            UploadSession instance or None if not found
        """
        result = await self.db.execute(
            select(UploadSession)
            .where(UploadSession.id == session_id)
            .options(
                selectinload(UploadSession.files),
                selectinload(UploadSession.dataset),
                selectinload(UploadSession.created_by),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_dataset(self, dataset_id: UUID) -> UploadSession | None:
        """Find the most recent active session for a dataset.

        An active session is one with status in (ISSUED, UPLOADED, VALIDATING, VALIDATED).

        Args:
            dataset_id: Dataset UUID

        Returns:
            Most recently created active UploadSession or None
        """
        result = await self.db.execute(
            select(UploadSession)
            .where(
                UploadSession.dataset_id == dataset_id,
                UploadSession.status.in_(_ACTIVE_STATUSES),
            )
            .options(selectinload(UploadSession.files))
            .order_by(UploadSession.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        session_id: UUID,
        status: UploadSessionStatus,
        error: str | None = None,
        expected_status: UploadSessionStatus | None = None,
    ) -> bool:
        """Update the status of an upload session with optional CAS guard.

        Args:
            session_id: Upload session UUID
            status: New status value
            error: Optional error message (set when status is FAILED)
            expected_status: If provided, only update if current status matches (CAS guard)

        Returns:
            True if the row was updated, False if the expected_status guard prevented it
        """
        values: dict[str, object] = {"status": status, "updated_at": datetime.now(UTC)}
        if error is not None:
            values["error"] = error

        conditions = [UploadSession.id == session_id]
        if expected_status is not None:
            conditions.append(UploadSession.status == expected_status)

        result = await self.db.execute(
            update(UploadSession).where(*conditions).values(**values)
        )
        await self.db.flush()
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]

    async def update_progress(
        self,
        session_id: UUID,
        validated_files: int | None = None,
        imported_files: int | None = None,
    ) -> None:
        """Update progress counters for a session.

        Args:
            session_id: Upload session UUID
            validated_files: Updated validated file count (omit to leave unchanged)
            imported_files: Updated imported file count (omit to leave unchanged)
        """
        values: dict[str, object] = {"updated_at": datetime.now(UTC)}
        if validated_files is not None:
            values["validated_files"] = validated_files
        if imported_files is not None:
            values["imported_files"] = imported_files

        await self.db.execute(
            update(UploadSession).where(UploadSession.id == session_id).values(**values)
        )
        await self.db.flush()

    async def get_expired_sessions(self) -> list[UploadSession]:
        """Return sessions whose presigned URLs have expired and were never uploaded.

        Returns:
            List of ISSUED sessions past their expiry time
        """
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(UploadSession).where(
                UploadSession.status == UploadSessionStatus.ISSUED,
                UploadSession.expires_at < now,
            )
        )
        return list(result.scalars().all())

    async def get_stale_sessions(self, max_age_hours: int = 24) -> list[UploadSession]:
        """Return sessions stuck in an intermediate processing state.

        Stale means the session is in UPLOADED or VALIDATING status and has not
        been updated within max_age_hours.

        Args:
            max_age_hours: Number of hours without an update before a session is stale

        Returns:
            List of stale UploadSession instances
        """
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        result = await self.db.execute(
            select(UploadSession).where(
                UploadSession.status.in_(_STALE_STATUSES),
                UploadSession.updated_at < cutoff,
            )
        )
        return list(result.scalars().all())

    async def get_total_storage_by_project(self, project_id: UUID) -> int:
        """Get total storage consumed by committed and active upload sessions for a project.

        Sums file_size from UploadFile records where:
        - The session's dataset belongs to the given project
        - The file status is IMPORTED, VALID, UPLOADED, or PENDING (committed or in-flight)
        - The session is not FAILED

        This query joins UploadFile -> UploadSession -> Dataset to reach the project_id.

        Args:
            project_id: Project UUID

        Returns:
            Total bytes consumed (0 if none)
        """
        committed_statuses = (
            UploadFileStatus.PENDING,
            UploadFileStatus.UPLOADED,
            UploadFileStatus.VALID,
            UploadFileStatus.IMPORTED,
        )
        result = await self.db.execute(
            select(func.coalesce(func.sum(UploadFile.file_size), 0))
            .join(UploadSession, UploadFile.session_id == UploadSession.id)
            .join(Dataset, UploadSession.dataset_id == Dataset.id)
            .where(
                Dataset.project_id == project_id,
                UploadFile.status.in_(committed_statuses),
                UploadSession.status != UploadSessionStatus.FAILED,
            )
        )
        return int(result.scalar_one())

    async def delete(self, session_id: UUID) -> None:
        """Delete an upload session and cascade-delete its files.

        Args:
            session_id: Upload session UUID
        """
        await self.db.execute(delete(UploadSession).where(UploadSession.id == session_id))
        await self.db.flush()


class UploadFileRepository:
    """Repository for UploadFile entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def create_many(self, files: list[UploadFile]) -> list[UploadFile]:
        """Bulk-insert upload file records.

        Args:
            files: List of UploadFile instances to persist

        Returns:
            List of created UploadFile instances
        """
        self.db.add_all(files)
        await self.db.flush()
        for f in files:
            await self.db.refresh(f)
        return files

    async def get_by_session(self, session_id: UUID) -> list[UploadFile]:
        """Return all files belonging to an upload session.

        Args:
            session_id: Upload session UUID

        Returns:
            List of UploadFile instances ordered by original_filename
        """
        result = await self.db.execute(
            select(UploadFile)
            .where(UploadFile.session_id == session_id)
            .order_by(UploadFile.original_filename)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        file_id: UUID,
        status: UploadFileStatus,
        **kwargs: object,
    ) -> None:
        """Update the status of an upload file with optional metadata.

        Args:
            file_id: Upload file UUID
            status: New status value
            **kwargs: Optional fields to update alongside status.
                Supported keys: validation_error, duration, samplerate,
                channels, bit_depth, recording_id, content_type
        """
        allowed_keys = {
            "validation_error",
            "duration",
            "samplerate",
            "channels",
            "bit_depth",
            "recording_id",
            "content_type",
        }
        values: dict[str, object] = {
            "status": status,
            "updated_at": datetime.now(UTC),
        }
        for key, value in kwargs.items():
            if key in allowed_keys:
                values[key] = value

        await self.db.execute(
            update(UploadFile).where(UploadFile.id == file_id).values(**values)
        )
        await self.db.flush()

    async def get_valid_files(self, session_id: UUID) -> list[UploadFile]:
        """Return files that passed validation for a session.

        Args:
            session_id: Upload session UUID

        Returns:
            List of UploadFile instances with status VALID
        """
        result = await self.db.execute(
            select(UploadFile).where(
                UploadFile.session_id == session_id,
                UploadFile.status == UploadFileStatus.VALID,
            )
        )
        return list(result.scalars().all())

    async def count_by_status(self, session_id: UUID) -> dict[str, int]:
        """Count files grouped by status for a session.

        Args:
            session_id: Upload session UUID

        Returns:
            Mapping of status value string to file count
        """
        result = await self.db.execute(
            select(UploadFile.status, func.count(UploadFile.id).label("cnt"))
            .where(UploadFile.session_id == session_id)
            .group_by(UploadFile.status)
        )
        return {row.status.value: row.cnt for row in result.all()}
