"""Note model for comments on annotations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.clip_annotation import ClipAnnotation
    from echoroo.models.sound_event_annotation import SoundEventAnnotation
    from echoroo.models.user import User


class Note(UUIDMixin, TimestampMixin, Base):
    """Comment or review note attached to an annotation.

    Exactly one of clip_annotation_id or sound_event_annotation_id must be non-null,
    enforced by a CHECK constraint.

    Attributes:
        id: Unique identifier (UUID)
        created_by_id: Foreign key to user who wrote this note
        clip_annotation_id: Optional foreign key to clip annotation (mutually exclusive)
        sound_event_annotation_id: Optional foreign key to sound event annotation (mutually exclusive)
        content: Note text content
        is_review: Whether this note is a formal review comment
    """

    __tablename__ = "notes"

    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who wrote this note",
    )
    clip_annotation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("clip_annotations.id", ondelete="CASCADE"),
        nullable=True,
        doc="Associated clip annotation (mutually exclusive with sound_event_annotation_id)",
    )
    sound_event_annotation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sound_event_annotations.id", ondelete="CASCADE"),
        nullable=True,
        doc="Associated sound event annotation (mutually exclusive with clip_annotation_id)",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Note text content",
    )
    is_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        doc="Whether this note is a formal review comment",
    )

    # Relationships
    created_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )
    clip_annotation: Mapped[ClipAnnotation | None] = relationship(
        "ClipAnnotation",
        back_populates="notes",
        foreign_keys=[clip_annotation_id],
        lazy="joined",
    )
    sound_event_annotation: Mapped[SoundEventAnnotation | None] = relationship(
        "SoundEventAnnotation",
        back_populates="notes",
        foreign_keys=[sound_event_annotation_id],
        lazy="joined",
    )

    __table_args__ = (
        CheckConstraint(
            "(clip_annotation_id IS NOT NULL AND sound_event_annotation_id IS NULL) OR "
            "(clip_annotation_id IS NULL AND sound_event_annotation_id IS NOT NULL)",
            name="ck_note_exactly_one_parent",
        ),
        Index("ix_notes_clip_annotation_id", "clip_annotation_id"),
        Index("ix_notes_sound_event_annotation_id", "sound_event_annotation_id"),
    )

    def __repr__(self) -> str:
        return f"<Note(id={self.id}, is_review={self.is_review})>"
