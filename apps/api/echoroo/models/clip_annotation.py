"""ClipAnnotation model for annotating audio clips."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, Table
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import ReviewStatus

if TYPE_CHECKING:
    from echoroo.models.annotation_task import AnnotationTask
    from echoroo.models.clip import Clip
    from echoroo.models.note import Note
    from echoroo.models.sound_event_annotation import SoundEventAnnotation
    from echoroo.models.tag import Tag
    from echoroo.models.user import User


# Association table for clip annotations and tags (many-to-many)
clip_annotation_tags = Table(
    "clip_annotation_tags",
    Base.metadata,
    Column(
        "clip_annotation_id",
        PG_UUID(as_uuid=True),
        ForeignKey("clip_annotations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class ClipAnnotation(UUIDMixin, TimestampMixin, Base):
    """Annotation result for a complete audio clip.

    Attributes:
        id: Unique identifier (UUID)
        task_id: Foreign key to associated annotation task (unique, one-to-one)
        clip_id: Foreign key to the annotated clip
        created_by_id: Foreign key to user who created this annotation
        review_status: Review status of this annotation
        reviewed_by_id: Optional foreign key to user who reviewed this annotation
        reviewed_at: Optional timestamp when review was completed
    """

    __tablename__ = "clip_annotations"

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_tasks.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        doc="Associated annotation task ID (one-to-one)",
    )
    clip_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("clips.id", ondelete="CASCADE"),
        nullable=False,
        doc="Annotated clip ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who created this annotation",
    )
    review_status: Mapped[ReviewStatus] = mapped_column(
        Enum(
            ReviewStatus,
            name="reviewstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ReviewStatus.UNREVIEWED,
        nullable=False,
        doc="Review status of this annotation",
    )
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who reviewed this annotation",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when review was completed",
    )

    # Relationships
    task: Mapped[AnnotationTask] = relationship(
        "AnnotationTask",
        back_populates="clip_annotation",
        lazy="joined",
    )
    clip: Mapped[Clip] = relationship(
        "Clip",
        lazy="joined",
    )
    created_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[created_by_id],
        lazy="joined",
    )
    reviewed_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[reviewed_by_id],
        lazy="joined",
    )
    tags: Mapped[list[Tag]] = relationship(
        "Tag",
        secondary=clip_annotation_tags,
        lazy="select",
    )
    sound_events: Mapped[list[SoundEventAnnotation]] = relationship(
        "SoundEventAnnotation",
        back_populates="clip_annotation",
        cascade="all, delete-orphan",
        lazy="select",
    )
    notes: Mapped[list[Note]] = relationship(
        "Note",
        back_populates="clip_annotation",
        primaryjoin="Note.clip_annotation_id == ClipAnnotation.id",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_clip_annotations_clip_id", "clip_id"),
        Index("ix_clip_annotations_review_status", "review_status"),
    )

    def __repr__(self) -> str:
        return f"<ClipAnnotation(id={self.id}, review_status={self.review_status})>"
