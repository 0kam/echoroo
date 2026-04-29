"""SearchSession model for persisting batch similarity search sessions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import SearchSessionStatus

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.recording_annotation import RecordingAnnotation
    from echoroo.models.user import User


class SearchSession(UUIDMixin, TimestampMixin, Base):
    """Persisted record of a batch similarity search session.

    Stores the configuration, status, and results of a batch search
    so users can review and revisit past searches.

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to the owning project
        user_id: Optional foreign key to the user who initiated the search
        name: Auto-generated or user-provided session name
        status: Execution status (pending, running, completed, failed)
        model_name: ML model used for embedding generation
        parameters: Search parameters (min_similarity, limit_per_species, dataset_id)
        species_config: List of species configurations used in the search
        results: Full BatchSearchResponse stored as JSONB
        result_count: Total number of matches found
        confirmed_count: Number of annotations confirmed by reviewers
        rejected_count: Number of annotations rejected by reviewers
        celery_job_id: Celery task ID for async job tracking
        reference_audio_keys: S3 object keys for uploaded reference audio files
        started_at: Timestamp when the search started execution
        completed_at: Timestamp when the search completed or failed
        error_message: Error details if status is FAILED
    """

    __tablename__ = "search_sessions"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning project ID",
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who initiated the search",
    )
    name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        doc="Auto-generated or user-provided session name",
    )
    status: Mapped[SearchSessionStatus] = mapped_column(
        Enum(
            SearchSessionStatus,
            name="searchsessionstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=SearchSessionStatus.PENDING,
        doc="Execution status",
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="ML model used for embedding generation",
    )
    parameters: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Search parameters (min_similarity, limit_per_species, dataset_id)",
    )
    species_config: Mapped[list[object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="List of species configurations used in the search",
    )
    results: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Full BatchSearchResponse stored as JSONB",
    )
    result_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of matches found",
    )
    confirmed_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of annotations confirmed by reviewers",
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of annotations rejected by reviewers",
    )
    celery_job_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        index=True,
        doc="Celery task ID for async job tracking",
    )
    reference_audio_keys: Mapped[list[str] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="S3 object keys for uploaded reference audio files",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the search started execution",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the search completed or failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error details if status is FAILED",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="raise",
    )
    user: Mapped[User | None] = relationship(
        "User",
        lazy="raise",
    )
    # Phase 13 P1.5 R2: rebound to ``RecordingAnnotation`` (Phase 14+ deferred).
    # See ``apps/api/echoroo/models/recording_annotation.py`` module docstring.
    annotations: Mapped[list[RecordingAnnotation]] = relationship(
        "RecordingAnnotation",
        back_populates="search_session",
        lazy="raise",
    )

    # Note: ``created_at`` already has ``index=True`` via ``TimestampMixin``,
    # which auto-generates ``ix_search_sessions_created_at``. Declaring it here
    # again would collide with the auto-generated index name and trigger
    # ``DuplicateTableError`` in ``Base.metadata.create_all``.
    __table_args__ = (
        Index("ix_search_sessions_project_id", "project_id"),
        Index("ix_search_sessions_user_id", "user_id"),
        Index("ix_search_sessions_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<SearchSession(id={self.id}, status={self.status}, project_id={self.project_id})>"
