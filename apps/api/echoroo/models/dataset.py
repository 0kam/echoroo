"""Dataset model for audio file collections."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import DatasetStatus, DatasetVisibility

if TYPE_CHECKING:
    from echoroo.models.license import License
    from echoroo.models.project import Project
    from echoroo.models.recorder import Recorder
    from echoroo.models.recording import Recording
    from echoroo.models.site import Site
    from echoroo.models.user import User


class Dataset(UUIDMixin, TimestampMixin, Base):
    """Collection of audio recordings imported from a directory.

    Attributes:
        id: Unique identifier (UUID)
        site_id: Foreign key to parent site (required)
        project_id: Foreign key to project (denormalized for queries)
        recorder_id: Optional foreign key to recording device
        license_id: Optional foreign key to content license
        created_by_id: User who created dataset
        name: Dataset name (max 200 chars)
        description: Optional description
        audio_dir: Relative path to audio directory
        visibility: Dataset visibility (private/public)
        status: Import status
        doi: Optional Digital Object Identifier
        gain: Optional recording gain in dB
        note: Optional internal notes
        datetime_pattern: Regex for datetime extraction
        datetime_format: strftime format string
        total_files: Total audio files discovered
        processed_files: Files successfully imported
        processing_error: Error message if failed
    """

    __tablename__ = "datasets"

    site_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent site ID",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent project ID (denormalized)",
    )
    recorder_id: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("recorders.id", ondelete="SET NULL"),
        nullable=True,
        doc="Recording device ID",
    )
    license_id: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("licenses.id", ondelete="SET NULL"),
        nullable=True,
        doc="Content license ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who created dataset",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Dataset name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Dataset description",
    )
    audio_dir: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        doc="Relative path to audio directory",
    )
    visibility: Mapped[DatasetVisibility] = mapped_column(
        Enum(
            DatasetVisibility,
            name="datasetvisibility",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DatasetVisibility.PRIVATE,
        nullable=False,
        doc="Dataset visibility level",
    )
    status: Mapped[DatasetStatus] = mapped_column(
        Enum(
            DatasetStatus,
            name="datasetstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DatasetStatus.PENDING,
        nullable=False,
        doc="Import status",
    )
    doi: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Digital Object Identifier",
    )
    gain: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Recording gain in dB",
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Internal notes",
    )
    datetime_pattern: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Regex pattern for datetime extraction",
    )
    datetime_format: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="strftime format string",
    )
    total_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Total audio files discovered",
    )
    processed_files: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Files successfully imported",
    )
    processing_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error message if failed",
    )

    # Relationships
    site: Mapped[Site] = relationship(
        "Site",
        back_populates="datasets",
        lazy="joined",
    )
    project: Mapped[Project] = relationship(
        "Project",
        lazy="joined",
    )
    recorder: Mapped[Recorder | None] = relationship(
        "Recorder",
        lazy="joined",
    )
    license: Mapped[License | None] = relationship(
        "License",
        lazy="joined",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )
    recordings: Mapped[list[Recording]] = relationship(
        "Recording",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_dataset_project_name"),
        Index("ix_datasets_project_id", "project_id"),
        Index("ix_datasets_site_id", "site_id"),
        Index("ix_datasets_status", "status"),
        Index("ix_datasets_visibility", "visibility"),
    )

    def __repr__(self) -> str:
        return f"<Dataset(id={self.id}, name={self.name})>"
