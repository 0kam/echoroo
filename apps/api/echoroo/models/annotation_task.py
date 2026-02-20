"""AnnotationTask model for individual clip annotation assignments."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import AnnotationTaskStatus

if TYPE_CHECKING:
    from echoroo.models.annotation_project import AnnotationProject
    from echoroo.models.clip import Clip
    from echoroo.models.clip_annotation import ClipAnnotation
    from echoroo.models.user import User


class AnnotationTask(UUIDMixin, TimestampMixin, Base):
    """Individual annotation task assigning a clip to an annotation project.

    Attributes:
        id: Unique identifier (UUID)
        annotation_project_id: Foreign key to parent annotation project
        clip_id: Foreign key to the audio clip to be annotated
        assigned_to_id: Optional foreign key to assigned annotator
        status: Task workflow status
        priority: Task priority (higher = more urgent)
    """

    __tablename__ = "annotation_tasks"

    annotation_project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent annotation project ID",
    )
    clip_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("clips.id", ondelete="CASCADE"),
        nullable=False,
        doc="Clip to be annotated",
    )
    assigned_to_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Assigned annotator user ID",
    )
    status: Mapped[AnnotationTaskStatus] = mapped_column(
        Enum(
            AnnotationTaskStatus,
            name="annotationtaskstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AnnotationTaskStatus.PENDING,
        nullable=False,
        doc="Task workflow status",
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        doc="Task priority (higher value = higher priority)",
    )

    # Relationships
    annotation_project: Mapped[AnnotationProject] = relationship(
        "AnnotationProject",
        back_populates="tasks",
        lazy="joined",
    )
    clip: Mapped[Clip] = relationship(
        "Clip",
        lazy="joined",
    )
    assigned_to: Mapped[User | None] = relationship(
        "User",
        lazy="joined",
    )
    clip_annotation: Mapped[ClipAnnotation | None] = relationship(
        "ClipAnnotation",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        UniqueConstraint("annotation_project_id", "clip_id", name="uq_annotation_task_project_clip"),
        Index("ix_annotation_tasks_project_status", "annotation_project_id", "status"),
        Index("ix_annotation_tasks_assigned_to_id", "assigned_to_id"),
    )

    def __repr__(self) -> str:
        return f"<AnnotationTask(id={self.id}, status={self.status})>"
