"""Upload session and file models for S3-based audio file ingestion."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import UploadFileStatus, UploadSessionStatus

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.recording import Recording
    from echoroo.models.user import User


class UploadSession(UUIDMixin, TimestampMixin, Base):
    """Upload session tracking presigned URL issuance through import completion.

    Attributes:
        id: Unique identifier (UUID)
        dataset_id: Foreign key to parent dataset
        created_by_id: User who initiated the upload
        status: Current lifecycle state
        total_files: Number of files in this session
        total_bytes: Total expected bytes across all files
        validated_files: Number of files that passed validation
        imported_files: Number of files successfully imported as recordings
        error: Error message if session failed
        expires_at: Expiry time for presigned URLs
        created_at: Session creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "upload_sessions"

    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent dataset ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who initiated the upload",
    )
    status: Mapped[UploadSessionStatus] = mapped_column(
        Enum(
            UploadSessionStatus,
            name="uploadsessionstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=UploadSessionStatus.ISSUED,
        nullable=False,
        doc="Current lifecycle state",
    )
    total_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of files in this session",
    )
    total_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        nullable=False,
        doc="Total expected bytes across all files",
    )
    validated_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of files that passed validation",
    )
    imported_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of files successfully imported as recordings",
    )
    error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if session failed",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Expiry time for presigned URLs",
    )

    # Relationships
    dataset: Mapped[Dataset] = relationship(
        "Dataset",
        lazy="joined",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )
    files: Mapped[list[UploadFile]] = relationship(
        "UploadFile",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_upload_sessions_dataset_id", "dataset_id"),
        Index("ix_upload_sessions_status", "status"),
        Index("ix_upload_sessions_expires_at", "expires_at"),
        Index("ix_upload_sessions_dataset_id_status", "dataset_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<UploadSession(id={self.id}, dataset_id={self.dataset_id}, status={self.status})>"


class UploadFile(UUIDMixin, TimestampMixin, Base):
    """Individual file within an upload session.

    Attributes:
        id: Unique identifier (UUID)
        session_id: Foreign key to parent upload session
        original_filename: Original filename as provided by the client
        object_key: S3 object key for this file
        file_size: Expected file size in bytes
        checksum_sha256: SHA-256 checksum for integrity verification
        status: Current file status
        content_type: Detected MIME type
        duration: Audio duration in seconds (extracted by ffprobe)
        samplerate: Sample rate in Hz
        channels: Number of audio channels
        bit_depth: Bits per sample
        validation_error: Validation failure message if invalid
        recording_id: Foreign key to created recording (after import)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    __tablename__ = "upload_files"

    session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("upload_sessions.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent upload session ID",
    )
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Original filename as provided by the client",
    )
    object_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
        doc="S3 object key for this file",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        doc="Expected file size in bytes",
    )
    checksum_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="SHA-256 checksum for integrity verification",
    )
    status: Mapped[UploadFileStatus] = mapped_column(
        Enum(
            UploadFileStatus,
            name="uploadfilestatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=UploadFileStatus.PENDING,
        nullable=False,
        doc="Current file status",
    )
    content_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Detected MIME type",
    )
    duration: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Audio duration in seconds (extracted by ffprobe)",
    )
    samplerate: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Sample rate in Hz",
    )
    channels: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Number of audio channels",
    )
    bit_depth: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc="Bits per sample",
    )
    validation_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Validation failure message if invalid",
    )
    recording_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="SET NULL"),
        nullable=True,
        doc="Foreign key to created recording (after import)",
    )

    # Relationships
    session: Mapped[UploadSession] = relationship(
        "UploadSession",
        back_populates="files",
    )
    recording: Mapped[Recording | None] = relationship(
        "Recording",
        lazy="joined",
    )

    __table_args__ = (
        Index("ix_upload_files_session_id", "session_id"),
        Index("ix_upload_files_object_key", "object_key", unique=True),
        Index("ix_upload_files_status", "status"),
        Index("ix_upload_files_recording_id", "recording_id"),
    )

    def __repr__(self) -> str:
        return f"<UploadFile(id={self.id}, filename={self.original_filename}, status={self.status})>"
