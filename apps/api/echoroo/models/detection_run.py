"""DetectionRun model for ML detection job tracking."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import DetectionRunStatus

if TYPE_CHECKING:
    from echoroo.models.annotation import Annotation
    from echoroo.models.dataset import Dataset
    from echoroo.models.project import Project


class DetectionRun(UUIDMixin, TimestampMixin, Base):
    """ML detection run for a project or dataset.

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to parent project
        dataset_id: Optional foreign key to specific dataset
        model_name: Name of the detection model used
        model_version: Version of the detection model
        parameters: Optional JSONB parameters passed to the model
        status: Current execution status of the run
        annotation_count: Number of annotations created by this run
        started_at: When the run started executing
        completed_at: When the run finished (success or failure)
        error_message: Error details if the run failed
    """

    __tablename__ = "detection_runs"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent project ID",
    )
    dataset_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="SET NULL"),
        nullable=True,
        doc="Optional dataset ID to scope the run",
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        doc="Name of the detection model",
    )
    model_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Version of the detection model",
    )
    parameters: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Optional model parameters as JSON",
    )
    status: Mapped[DetectionRunStatus] = mapped_column(
        Enum(
            DetectionRunStatus,
            name="detectionrunstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DetectionRunStatus.PENDING,
        nullable=False,
        doc="Current execution status",
    )
    annotation_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Number of annotations created by this run",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the run started executing",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the run finished (success or failure)",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error details if the run failed",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="joined",
    )
    dataset: Mapped[Dataset | None] = relationship(
        "Dataset",
        lazy="joined",
    )
    annotations: Mapped[list[Annotation]] = relationship(
        "Annotation",
        back_populates="detection_run",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_detection_runs_project_id", "project_id"),
        Index("ix_detection_runs_dataset_id", "dataset_id"),
        Index("ix_detection_runs_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<DetectionRun(id={self.id}, model={self.model_name}, status={self.status})>"
