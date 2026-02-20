"""SoundEventAnnotation model for annotating individual sound events within clips."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Enum, Float, ForeignKey, Index, Table
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import AnnotationSource

if TYPE_CHECKING:
    from echoroo.models.clip_annotation import ClipAnnotation
    from echoroo.models.note import Note
    from echoroo.models.tag import Tag
    from echoroo.models.user import User


# Association table for sound event annotations and tags (many-to-many)
sound_event_annotation_tags = Table(
    "sound_event_annotation_tags",
    Base.metadata,
    Column(
        "sound_event_annotation_id",
        PG_UUID(as_uuid=True),
        ForeignKey("sound_event_annotations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "tag_id",
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class SoundEventAnnotation(UUIDMixin, TimestampMixin, Base):
    """Annotation for an individual sound event within a clip.

    Attributes:
        id: Unique identifier (UUID)
        clip_annotation_id: Foreign key to parent clip annotation
        created_by_id: Foreign key to user or system that created this annotation
        geometry: JSONB geometry descriptor (BoundingBox or TimeInterval)
        source: Source of the annotation (human or model)
        confidence: Optional confidence score (0.0 to 1.0)
    """

    __tablename__ = "sound_event_annotations"

    clip_annotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("clip_annotations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent clip annotation ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User or system that created this annotation",
    )
    geometry: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        doc="Geometry descriptor (BoundingBox or TimeInterval) with coordinates",
    )
    source: Mapped[AnnotationSource] = mapped_column(
        Enum(
            AnnotationSource,
            name="annotationsource",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AnnotationSource.HUMAN,
        nullable=False,
        doc="Source of the annotation",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Confidence score (0.0 to 1.0)",
    )

    # Relationships
    clip_annotation: Mapped[ClipAnnotation] = relationship(
        "ClipAnnotation",
        back_populates="sound_events",
        lazy="joined",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="joined",
    )
    tags: Mapped[list[Tag]] = relationship(
        "Tag",
        secondary=sound_event_annotation_tags,
        lazy="select",
    )
    notes: Mapped[list[Note]] = relationship(
        "Note",
        back_populates="sound_event_annotation",
        primaryjoin="Note.sound_event_annotation_id == SoundEventAnnotation.id",
        cascade="all, delete-orphan",
        lazy="select",
    )

    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)", name="ck_sea_confidence_range"),
        Index("ix_sound_event_annotations_clip_annotation_id", "clip_annotation_id"),
    )

    def __repr__(self) -> str:
        return f"<SoundEventAnnotation(id={self.id}, source={self.source})>"
